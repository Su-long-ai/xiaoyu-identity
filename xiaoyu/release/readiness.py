from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Optional

from xiaoyu.core.temporal import TemporalFactService
from xiaoyu.persistence import (
    Database,
    ExternalErasureFenceStore,
    applied_versions,
)
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.migrations.v12_authority_cutover import (
    LEGACY_AUTHORITY_TABLES,
)
from xiaoyu.release.migration import (
    AuthorityCutoverController,
    AuthorityCutoverEvidence,
    AuthorityCutoverGate,
)
from xiaoyu.runtime.product_context import (
    CanonicalReadShadowEvaluator,
)


@dataclass(frozen=True)
class CanonicalCutoverCandidate:
    identity_id: str
    ready: bool
    blockers: tuple[str, ...]
    evidence: Optional[AuthorityCutoverEvidence]
    read_evidence_digest: Optional[str]
    write_evidence_digest: Optional[str]
    schema_version: int
    evaluated_at: str


class CanonicalCutoverReadiness:
    """Machine-gated cutover candidate. It never activates authority itself."""

    def __init__(
        self,
        db: Database,
        *,
        read_status_path,
        write_status_path,
        max_evidence_age_s: float = 86400.0,
    ) -> None:
        if float(max_evidence_age_s) <= 0:
            raise ValueError(
                "max_evidence_age_s must be positive"
            )
        self.db = db
        self.read_path = Path(read_status_path)
        self.write_path = Path(write_status_path)
        self.max_evidence_age_s = float(max_evidence_age_s)

    @staticmethod
    def _load(path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        try:
            value = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _digest_evidence(payload: dict) -> Optional[str]:
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            return None
        return "sha256:" + hashlib.sha256(
            json.dumps(
                evidence,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _parse_time(value) -> Optional[datetime]:
        try:
            result = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)

    @staticmethod
    def _legacy_present(db: Database) -> bool:
        with db.transaction() as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'"
                ).fetchall()
            }
        return any(
            table in tables
            for table in LEGACY_AUTHORITY_TABLES
        )

    @staticmethod
    def _db_erasure_generation(
        db: Database,
        identity_id: str,
    ) -> int:
        with db.transaction() as conn:
            row = conn.execute(
                """SELECT COALESCE(MAX(erasure_generation),0)
                   FROM fact_authority_revisions
                   WHERE identity_id=?""",
                (identity_id,),
            ).fetchone()
        return int(row[0] or 0)

    @staticmethod
    def _external_erasure_generation(
        db: Database,
        identity_id: str,
    ) -> int:
        row = ExternalErasureFenceStore(
            db.path
        ).identity(identity_id)
        return (
            0
            if row is None
            else int(row["erasure_generation"])
        )

    def _status_blockers(
        self,
        *,
        label: str,
        payload: Optional[dict],
        identity_id: str,
        schema_version: int,
        now: datetime,
    ) -> list[str]:
        prefix = label.upper()
        if payload is None:
            return [prefix + "_STATUS_MISSING"]
        blockers = []
        if str(payload.get("identity_id") or "") != identity_id:
            blockers.append(prefix + "_IDENTITY_MISMATCH")
        if int(payload.get("schema_version") or 0) != schema_version:
            blockers.append(prefix + "_SCHEMA_STALE")
        expected = self._digest_evidence(payload)
        if (
            expected is None
            or expected
            != str(payload.get("evidence_digest") or "")
        ):
            blockers.append(prefix + "_EVIDENCE_DIGEST_INVALID")
        if not bool(payload.get("candidate_ready")):
            blockers.append(prefix + "_NOT_CANDIDATE_READY")
        stamp = self._parse_time(payload.get("updated_at"))
        if stamp is None:
            blockers.append(prefix + "_TIMESTAMP_INVALID")
        elif (
            now - stamp
        ).total_seconds() > self.max_evidence_age_s:
            blockers.append(prefix + "_EVIDENCE_STALE")
        elif stamp > now:
            blockers.append(prefix + "_TIMESTAMP_FUTURE")
        return blockers

    def evaluate(
        self,
        *,
        identity_id: str,
        principal_id: str = "owner",
        evaluated_at: Optional[datetime] = None,
    ) -> CanonicalCutoverCandidate:
        now = (
            evaluated_at or datetime.now(timezone.utc)
        ).astimezone(timezone.utc)
        schema_version = max(
            applied_versions(self.db),
            default=0,
        )
        read = self._load(self.read_path)
        write = self._load(self.write_path)
        blockers = []
        blockers.extend(
            self._status_blockers(
                label="read",
                payload=read,
                identity_id=identity_id,
                schema_version=schema_version,
                now=now,
            )
        )
        blockers.extend(
            self._status_blockers(
                label="write",
                payload=write,
                identity_id=identity_id,
                schema_version=schema_version,
                now=now,
            )
        )

        live_read_ready = False
        if not any(
            value.startswith("READ_")
            for value in blockers
        ):
            try:
                current = CanonicalReadShadowEvaluator(
                    self.db
                ).evaluate(
                    identity_id=identity_id,
                    principal_id=principal_id,
                )
                live_read_ready = current.ready
                if not current.ready:
                    blockers.append(
                        "LIVE_READ_DRIFT:"
                        + ",".join(current.blockers())
                    )
            except Exception as exc:
                blockers.append(
                    "LIVE_READ_EVALUATION_FAILED:"
                    + type(exc).__name__
                )

        source_order_ok = True
        shadow_caught_up = True
        if self._legacy_present(self.db):
            try:
                LegacyShadowBackfill(
                    self.db
                ).require_cutover_ready(identity_id)
            except Exception as exc:
                source_order_ok = False
                shadow_caught_up = False
                blockers.append(
                    "LEGACY_BACKFILL_NOT_READY:"
                    + type(exc).__name__
                )

        rebuild_equal = False
        try:
            with tempfile.TemporaryDirectory() as td:
                target = Database(
                    Path(td) / "rebuild.sqlite3"
                )
                report = TemporalFactService(
                    self.db
                ).rebuild_into(
                    target,
                    identity_id=identity_id,
                )
                rebuild_equal = (
                    report["snapshot"]
                    == TemporalFactService(
                        self.db
                    ).authority_snapshot(
                        identity_id=identity_id
                    )
                )
        except Exception as exc:
            blockers.append(
                "R9_REBUILD_FAILED:"
                + type(exc).__name__
            )
        if not rebuild_equal:
            blockers.append("R9_REBUILD_MISMATCH")

        external_generation = (
            self._external_erasure_generation(
                self.db, identity_id
            )
        )
        db_generation = self._db_erasure_generation(
            self.db, identity_id
        )
        if external_generation != db_generation:
            blockers.append(
                "ERASURE_GENERATION_MISMATCH"
            )

        controller = AuthorityCutoverController(self.db)
        writer_fence = controller.writer_fence_installed()
        if not writer_fence:
            blockers.append("OLD_WRITER_NOT_FENCED")

        write_ready = (
            write is not None
            and not any(
                value.startswith("WRITE_")
                for value in blockers
            )
        )
        evidence = AuthorityCutoverEvidence(
            shadow_caught_up=shadow_caught_up,
            rebuild_equal=rebuild_equal,
            unresolved_conflicts=0,
            erasure_generation_source=external_generation,
            erasure_generation_shadow=db_generation,
            source_order_ok=source_order_ok,
            old_writer_fenced=writer_fence,
            canonical_read_path_ready=live_read_ready,
            canonical_write_path_ready=write_ready,
        )
        decision = AuthorityCutoverGate.evaluate(evidence)
        for blocker in decision.blockers:
            if blocker not in blockers:
                blockers.append(blocker)

        blockers = list(dict.fromkeys(blockers))
        return CanonicalCutoverCandidate(
            identity_id=identity_id,
            ready=not blockers,
            blockers=tuple(blockers),
            evidence=evidence,
            read_evidence_digest=(
                None
                if read is None
                else str(
                    read.get("evidence_digest") or ""
                )
            ),
            write_evidence_digest=(
                None
                if write is None
                else str(
                    write.get("evidence_digest") or ""
                )
            ),
            schema_version=schema_version,
            evaluated_at=now.isoformat(
                timespec="microseconds"
            ),
        )
