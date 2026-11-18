from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Optional, Tuple

from xiaoyu.contracts.common import canonical_json, datetime_to_text
from xiaoyu.persistence import Database
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.migrations.v12_authority_cutover import (
    LEGACY_AUTHORITY_TABLES,
)


class MigrationRollbackPolicy(str, Enum):
    FORWARD_ONLY = "FORWARD_ONLY"


class AuthorityMode(str, Enum):
    SHADOW = "SHADOW"
    CANONICAL = "CANONICAL"


class AuthorityCutoverBlocked(RuntimeError):
    pass


class AuthorityRollbackForbidden(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthorityCutoverEvidence:
    shadow_caught_up: bool
    rebuild_equal: bool
    unresolved_conflicts: int
    erasure_generation_source: int
    erasure_generation_shadow: int
    source_order_ok: bool
    old_writer_fenced: bool
    canonical_read_path_ready: bool = False
    canonical_write_path_ready: bool = False


@dataclass(frozen=True)
class AuthorityCutoverDecision:
    ready: bool
    blockers: Tuple[str, ...]
    rollback_policy: MigrationRollbackPolicy = MigrationRollbackPolicy.FORWARD_ONLY


@dataclass(frozen=True)
class AuthorityCutoverState:
    identity_id: str
    mode: AuthorityMode
    activated_at: Optional[str]
    activation_digest: Optional[str]
    legacy_event_high_watermark: int
    legacy_memory_change_seq: int
    forward_only: bool


class AuthorityCutoverGate:
    """Deterministic gate for the single-authority switch."""

    @staticmethod
    def evaluate(evidence: AuthorityCutoverEvidence) -> AuthorityCutoverDecision:
        blockers = []
        if not evidence.shadow_caught_up:
            blockers.append("SHADOW_NOT_CAUGHT_UP")
        if not evidence.rebuild_equal:
            blockers.append("REBUILD_MISMATCH")
        if int(evidence.unresolved_conflicts) != 0:
            blockers.append("UNRESOLVED_CONFLICTS")
        if int(evidence.erasure_generation_source) != int(
            evidence.erasure_generation_shadow
        ):
            blockers.append("ERASURE_GENERATION_MISMATCH")
        if not evidence.source_order_ok:
            blockers.append("SOURCE_ORDER_MISMATCH")
        if not evidence.old_writer_fenced:
            blockers.append("OLD_WRITER_NOT_FENCED")
        if not evidence.canonical_read_path_ready:
            blockers.append("CANONICAL_READ_PATH_NOT_READY")
        if not evidence.canonical_write_path_ready:
            blockers.append("CANONICAL_WRITE_PATH_NOT_READY")
        return AuthorityCutoverDecision(
            ready=not blockers,
            blockers=tuple(blockers),
        )


class AuthorityCutoverController:
    """Durable, one-way authority switch.

    The controller never fabricates product-readiness evidence. It verifies the
    database-level writer-fence mechanism itself, but callers must explicitly
    prove that canonical product reads and writes are ready before activation.
    """

    def __init__(
        self,
        db: Database,
        *,
        backfill: Optional[LegacyShadowBackfill] = None,
    ) -> None:
        self.db = db
        self.backfill = backfill or LegacyShadowBackfill(db)

    @staticmethod
    def _trigger_name(table: str, operation: str) -> str:
        return "xiaoyu_fence_%s_%s" % (
            table,
            operation.lower(),
        )

    def writer_fence_installed(self) -> bool:
        with self.db.transaction() as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'"
                ).fetchall()
            }
            required = {
                self._trigger_name(table, operation)
                for table in LEGACY_AUTHORITY_TABLES
                if table in tables
                for operation in ("INSERT", "UPDATE", "DELETE")
            }
            present = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger'"
                ).fetchall()
            }
        return required.issubset(present)

    def state(self, identity_id: str) -> AuthorityCutoverState:
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT identity_id,mode,activated_at,
                          activation_digest,
                          legacy_event_high_watermark,
                          legacy_memory_change_seq,forward_only
                   FROM authority_cutover_state
                   WHERE identity_id=?""",
                (identity_id,),
            ).fetchone()
        if row is None:
            return AuthorityCutoverState(
                identity_id=identity_id,
                mode=AuthorityMode.SHADOW,
                activated_at=None,
                activation_digest=None,
                legacy_event_high_watermark=0,
                legacy_memory_change_seq=0,
                forward_only=True,
            )
        return AuthorityCutoverState(
            identity_id=str(row["identity_id"]),
            mode=AuthorityMode(str(row["mode"])),
            activated_at=row["activated_at"],
            activation_digest=row["activation_digest"],
            legacy_event_high_watermark=int(
                row["legacy_event_high_watermark"]
            ),
            legacy_memory_change_seq=int(
                row["legacy_memory_change_seq"]
            ),
            forward_only=bool(row["forward_only"]),
        )

    @staticmethod
    def _legacy_authority_tables_present(conn) -> bool:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        return any(
            table in tables
            for table in LEGACY_AUTHORITY_TABLES
        )

    @staticmethod
    def _table_exists(conn, table: str) -> bool:
        return conn.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name=?""",
            (table,),
        ).fetchone() is not None

    @classmethod
    def _legacy_event_high_watermark(cls, conn) -> int:
        if not cls._table_exists(conn, "events"):
            return 0
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(event_id),0) FROM events"
            ).fetchone()[0]
        )

    @classmethod
    def _memory_change_seq(cls, conn) -> int:
        if cls._table_exists(conn, "settings"):
            row = conn.execute(
                "SELECT value FROM settings WHERE key='memory_change_seq'"
            ).fetchone()
            if row is not None:
                try:
                    return int(json.loads(str(row[0])))
                except (
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ):
                    pass
        if not cls._table_exists(conn, "memories"):
            return 0
        row = conn.execute(
            "SELECT COALESCE(MAX(change_seq),0) FROM memories"
        ).fetchone()
        return int(row[0] or 0)

    def activate(
        self,
        *,
        identity_id: str,
        evidence: AuthorityCutoverEvidence,
        activated_at: Optional[datetime] = None,
    ) -> AuthorityCutoverState:
        existing = self.state(identity_id)
        if existing.mode is AuthorityMode.CANONICAL:
            return existing

        # Legacy migrations must prove source-order convergence. A fresh
        # canonical-only database has no legacy authority to backfill/fence.
        with self.db.transaction() as conn:
            legacy_present = self._legacy_authority_tables_present(conn)
        if legacy_present:
            self.backfill.require_cutover_ready(identity_id)

        effective = replace(
            evidence,
            old_writer_fenced=self.writer_fence_installed(),
        )
        decision = AuthorityCutoverGate.evaluate(effective)
        if not decision.ready:
            raise AuthorityCutoverBlocked(
                ",".join(decision.blockers)
            )

        stamp = datetime_to_text(
            (activated_at or datetime.now(timezone.utc))
            .astimezone(timezone.utc),
            "activated_at",
        )

        with self.db.transaction(immediate=True) as conn:
            other = conn.execute(
                """SELECT identity_id FROM authority_cutover_state
                   WHERE mode='CANONICAL' AND identity_id!=?
                   LIMIT 1""",
                (identity_id,),
            ).fetchone()
            if other is not None:
                raise AuthorityCutoverBlocked(
                    "ANOTHER_IDENTITY_ALREADY_CANONICAL"
                )

            event_high = self._legacy_event_high_watermark(conn)
            memory_seq = self._memory_change_seq(conn)
            activation_payload = {
                "identity_id": identity_id,
                "activated_at": stamp,
                "legacy_event_high_watermark": event_high,
                "legacy_memory_change_seq": memory_seq,
                "evidence": asdict(effective),
                "rollback_policy":
                    MigrationRollbackPolicy.FORWARD_ONLY.value,
            }
            digest = "sha256:" + hashlib.sha256(
                canonical_json(activation_payload).encode("utf-8")
            ).hexdigest()

            conn.execute(
                """INSERT INTO authority_cutover_state(
                       identity_id,mode,activated_at,activation_digest,
                       legacy_event_high_watermark,
                       legacy_memory_change_seq,forward_only
                   ) VALUES(?, 'CANONICAL', ?, ?, ?, ?, 1)
                   ON CONFLICT(identity_id) DO UPDATE SET
                       mode='CANONICAL',
                       activated_at=excluded.activated_at,
                       activation_digest=excluded.activation_digest,
                       legacy_event_high_watermark=
                           excluded.legacy_event_high_watermark,
                       legacy_memory_change_seq=
                           excluded.legacy_memory_change_seq,
                       forward_only=1""",
                (
                    identity_id,
                    stamp,
                    digest,
                    event_high,
                    memory_seq,
                ),
            )

        return self.state(identity_id)

    def verify_legacy_writer_frozen(
        self,
        identity_id: str,
    ) -> bool:
        state = self.state(identity_id)
        if state.mode is not AuthorityMode.CANONICAL:
            return False
        with self.db.transaction() as conn:
            event_high = self._legacy_event_high_watermark(conn)
            memory_seq = self._memory_change_seq(conn)
        return (
            event_high == state.legacy_event_high_watermark
            and memory_seq == state.legacy_memory_change_seq
            and self.writer_fence_installed()
        )

    def rollback_to_shadow(self, identity_id: str) -> None:
        state = self.state(identity_id)
        if state.mode is AuthorityMode.CANONICAL:
            raise AuthorityRollbackForbidden(
                "canonical authority cutover is forward-only"
            )
        raise AuthorityRollbackForbidden(
            "no rollback transition exists; remain in SHADOW"
        )
