from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Optional

from xiaoyu.core.export import NativeCanonicalExporter
from xiaoyu.core.identity import SelfAuthorityService
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.core.temporal import TemporalFactService
from xiaoyu.persistence import (
    Database,
    ExternalErasureFenceStore,
    applied_versions,
    apply_migrations,
)
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.release.migration import (
    AuthorityCutoverController,
    AuthorityCutoverEvidence,
)
from xiaoyu.runtime.product_store import CanonicalProductStore


@dataclass(frozen=True)
class CanonicalWriteReadinessEvidence:
    event_idempotency: bool
    memory_lifecycle: bool
    persona_revision: bool
    proposal_decisions: bool
    purpose_write: bool
    presentation_write: bool
    export_complete: bool
    rebuild_equal: bool
    legacy_watermarks_unchanged: bool
    post_cutover_write: bool

    @property
    def ready(self) -> bool:
        return all(asdict(self).values())

    def blockers(self) -> tuple[str, ...]:
        return tuple(
            name.upper()
            for name, value in asdict(self).items()
            if not value
        )


@dataclass(frozen=True)
class CanonicalWriteShadowStatus:
    identity_id: str
    candidate_ready: bool
    blockers: tuple[str, ...]
    evidence_digest: str
    updated_at: str
    schema_version: int = 0


class CanonicalWriteShadowDrill:
    """Run destructive product-write acceptance only on a disposable DB copy."""

    VERSION = 1

    def __init__(
        self,
        source_db: Database,
        status_path,
    ) -> None:
        self.source_db = source_db
        self.status_path = Path(status_path)

    @staticmethod
    def _table_exists(conn, table: str) -> bool:
        return conn.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name=?""",
            (table,),
        ).fetchone() is not None

    @classmethod
    def _legacy_watermarks(cls, db: Database) -> tuple[int, int]:
        with db.transaction() as conn:
            event_high = (
                int(
                    conn.execute(
                        "SELECT COALESCE(MAX(event_id),0) FROM events"
                    ).fetchone()[0]
                )
                if cls._table_exists(conn, "events")
                else 0
            )
            memory_seq = 0
            if cls._table_exists(conn, "settings"):
                row = conn.execute(
                    """SELECT value FROM settings
                       WHERE key='memory_change_seq'"""
                ).fetchone()
                if row is not None:
                    try:
                        memory_seq = int(
                            json.loads(str(row[0]))
                        )
                    except (
                        TypeError,
                        ValueError,
                        json.JSONDecodeError,
                    ):
                        memory_seq = 0
            if (
                memory_seq == 0
                and cls._table_exists(conn, "memories")
            ):
                memory_seq = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(change_seq),0) FROM memories"
                    ).fetchone()[0]
                    or 0
                )
        return event_high, memory_seq

    @staticmethod
    def _erasure_generations(
        db: Database,
        identity_id: str,
    ) -> tuple[int, int]:
        with db.transaction() as conn:
            row = conn.execute(
                """SELECT COALESCE(MAX(erasure_generation),0)
                   FROM fact_authority_revisions
                   WHERE identity_id=?""",
                (identity_id,),
            ).fetchone()
            db_generation = int(row[0] or 0)
        external = ExternalErasureFenceStore(
            db.path
        ).identity(identity_id)
        external_generation = (
            0
            if external is None
            else int(external["erasure_generation"])
        )
        return external_generation, db_generation

    def _write_status(
        self,
        *,
        identity_id: str,
        evidence: CanonicalWriteReadinessEvidence,
        updated_at: datetime,
    ) -> CanonicalWriteShadowStatus:
        evidence_data = asdict(evidence)
        digest = "sha256:" + hashlib.sha256(
            json.dumps(
                evidence_data,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        schema_version = max(
            applied_versions(self.source_db),
            default=0,
        )
        payload = {
            "version": self.VERSION,
            "schema_version": schema_version,
            "identity_id": identity_id,
            "candidate_ready": evidence.ready,
            "blockers": list(evidence.blockers()),
            "evidence": evidence_data,
            "evidence_digest": digest,
            "updated_at": updated_at.astimezone(
                timezone.utc
            ).isoformat(timespec="microseconds"),
        }
        self.status_path.parent.mkdir(
            parents=True, exist_ok=True
        )
        tmp = self.status_path.with_name(
            self.status_path.name + ".tmp"
        )
        with tmp.open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.status_path)
        return CanonicalWriteShadowStatus(
            identity_id=identity_id,
            candidate_ready=evidence.ready,
            blockers=evidence.blockers(),
            evidence_digest=digest,
            updated_at=payload["updated_at"],
            schema_version=schema_version,
        )

    def run(
        self,
        *,
        identity_id: str,
        observed_at: Optional[datetime] = None,
    ) -> CanonicalWriteShadowStatus:
        now = (observed_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        checks = {
            "event_idempotency": False,
            "memory_lifecycle": False,
            "persona_revision": False,
            "proposal_decisions": False,
            "purpose_write": False,
            "presentation_write": False,
            "export_complete": False,
            "rebuild_equal": False,
            "legacy_watermarks_unchanged": False,
            "post_cutover_write": False,
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            copy_path = root / "write-drill.sqlite3"
            self.source_db.backup_to(copy_path)
            db = Database(copy_path)
            apply_migrations(db)

            # The backfill progress sidecar is intentionally not authority and
            # is not part of a SQLite backup. Rebuild that operational progress
            # from the copied legacy rows before exercising the real cutover
            # gate. Stable legacy source keys make the replay idempotent.
            with db.transaction() as conn:
                has_legacy_events = self._table_exists(conn, "events")
            if has_legacy_events:
                backfill = LegacyShadowBackfill(db)
                while True:
                    report = backfill.run_batch(
                        identity_id,
                        limit=5000,
                    )
                    if (
                        report.progress.state == "CAUGHT_UP"
                        and report.converged
                    ):
                        break
                    if report.progress.state != "RUNNING":
                        raise RuntimeError(
                            "disposable legacy shadow backfill did not converge: "
                            + report.progress.state
                        )

            # SELF must already be a real canonical authority on the source.
            current_self = SelfAuthorityService(db).get(
                identity_id
            )
            product = CanonicalProductStore(
                db,
                identity_id=identity_id,
            )
            legacy_before = self._legacy_watermarks(db)

            user = product.record_user_turn(
                source_event_key="__write_drill_user_v1",
                text="canonical write drill",
                observed_at=now,
            )
            same = product.record_user_turn(
                source_event_key="__write_drill_user_v1",
                text="canonical write drill",
                observed_at=now + timedelta(seconds=1),
            )
            assistant = product.record_assistant_turn(
                source_event_key="__write_drill_assistant_v1",
                text="drill response",
                observed_at=now + timedelta(seconds=2),
            )
            checks["event_idempotency"] = (
                user.event_id == same.event_id
                and not assistant.eligible_for_memory
            )

            saved = product.save_memory(
                memory_id="__write_drill_memory",
                mutation_id="__write_drill_memory_assert",
                source_event_id=user.event_id,
                principal_id="owner",
                text="drill memory A",
                category="other",
                priority=3,
                created_at=now,
            )
            correction_event = product.record_user_turn(
                source_event_key="__write_drill_correction_v1",
                text="drill memory B",
                observed_at=now + timedelta(seconds=3),
            )
            corrected = product.correct_memory(
                memory_id="__write_drill_memory",
                mutation_id="__write_drill_memory_correct",
                source_event_id=correction_event.event_id,
                principal_id="owner",
                expected_revision=saved.revision,
                text="drill memory B",
                category="other",
                priority=3,
                created_at=now + timedelta(seconds=3),
            )

            retract_source = product.record_user_turn(
                source_event_key="__write_drill_retract_source_v1",
                text="temporary drill memory",
                observed_at=now + timedelta(seconds=4),
            )
            retract_item = product.save_memory(
                memory_id="__write_drill_retract",
                mutation_id="__write_drill_retract_assert",
                source_event_id=retract_source.event_id,
                principal_id="owner",
                text="temporary drill memory",
                category="other",
                priority=2,
                created_at=now + timedelta(seconds=4),
            )
            retract_event = product.record_owner_control(
                source_event_key="__write_drill_retract_v1",
                event_type="memory.retracted",
                payload={"memory_id": "__write_drill_retract"},
                observed_at=now + timedelta(seconds=5),
            )
            retracted = product.retract_memory(
                memory_id="__write_drill_retract",
                mutation_id="__write_drill_retract_mutation",
                source_event_id=retract_event.event_id,
                principal_id="owner",
                expected_revision=retract_item.revision,
                created_at=now + timedelta(seconds=5),
            )
            delete_event = product.record_owner_control(
                source_event_key="__write_drill_delete_v1",
                event_type="memory.deleted",
                payload={"memory_id": "__write_drill_memory"},
                observed_at=now + timedelta(seconds=6),
            )
            deleted = product.delete_memory(
                memory_id="__write_drill_memory",
                mutation_id="__write_drill_memory_delete",
                source_event_id=delete_event.event_id,
                principal_id="owner",
                expected_revision=corrected.revision,
                created_at=now + timedelta(seconds=6),
            )
            checks["memory_lifecycle"] = (
                corrected.revision == 2
                and retracted.revision == 2
                and deleted.revision == 3
                and deleted.erasure_generation > 0
            )

            persona_event = product.record_user_turn(
                source_event_key="__write_drill_persona_v1",
                text="approve a temporary drill style marker",
                observed_at=now + timedelta(seconds=7),
            )
            persona = product.revise_persona(
                expected_revision=current_self.persona_revision,
                persona={
                    **current_self.persona,
                    "style": {
                        **(
                            current_self.persona.get("style")
                            if isinstance(
                                current_self.persona.get("style"),
                                dict,
                            )
                            else {}
                        ),
                        "__write_drill": True,
                    },
                },
                reason="write-drill-only",
                source_event_ids=(persona_event.event_id,),
                principal_id="owner",
                created_at=now + timedelta(seconds=7),
            )
            checks["persona_revision"] = (
                persona.persona_revision
                == current_self.persona_revision + 1
                and persona.identity_id == identity_id
            )

            proposal_source = product.record_user_turn(
                source_event_key="__write_drill_proposal_source_v1",
                text="candidate drill memory",
                observed_at=now + timedelta(seconds=8),
            )
            product.propose_memory(
                claim_id="__write_drill_proposal_approve",
                source_event_id=proposal_source.event_id,
                text="approved drill proposal",
                category="other",
                priority=2,
                created_at=now + timedelta(seconds=8),
            )
            approve_event = product.record_owner_control(
                source_event_key="__write_drill_proposal_approve_v1",
                event_type="memory.approved",
                payload={"claim_id": "__write_drill_proposal_approve"},
                observed_at=now + timedelta(seconds=9),
            )
            approved = product.approve_memory(
                claim_id="__write_drill_proposal_approve",
                decision_event_id=approve_event.event_id,
                principal_id="owner",
                memory_id="__write_drill_proposal_memory",
                decided_at=now + timedelta(seconds=9),
            )

            reject_source = product.record_user_turn(
                source_event_key="__write_drill_reject_source_v1",
                text="reject this drill candidate",
                observed_at=now + timedelta(seconds=10),
            )
            product.propose_memory(
                claim_id="__write_drill_proposal_reject",
                source_event_id=reject_source.event_id,
                text="rejected drill proposal",
                category="other",
                priority=2,
                created_at=now + timedelta(seconds=10),
            )
            reject_event = product.record_owner_control(
                source_event_key="__write_drill_proposal_reject_v1",
                event_type="memory.rejected",
                payload={"claim_id": "__write_drill_proposal_reject"},
                observed_at=now + timedelta(seconds=11),
            )
            rejected = product.reject_memory(
                claim_id="__write_drill_proposal_reject",
                decision_event_id=reject_event.event_id,
                principal_id="owner",
                decided_at=now + timedelta(seconds=11),
            )
            checks["proposal_decisions"] = (
                approved.text == "approved drill proposal"
                and rejected.state == "REJECTED"
                and not product.proposals.list_pending(identity_id)
            )

            purpose = Purpose(
                purpose_id="__write_drill_purpose",
                identity_id=identity_id,
                owner_type=PurposeOwner.USER,
                owner_id="owner",
                state=PurposeState.CONFIRMED,
                kind=PurposeKind.FOLLOW_UP,
                source_event_id=user.event_id,
                payload={"topic": "write-drill"},
                scheduled_wall_time=None,
                timezone_name=None,
                resolved_utc_time=None,
                miss_policy=MissPolicy.RECONCILE,
            )
            product.create_purpose(
                purpose,
                created_at=now + timedelta(seconds=12),
            )
            with db.transaction() as conn:
                purpose_row = conn.execute(
                    """SELECT state FROM purposes
                       WHERE purpose_id='__write_drill_purpose'"""
                ).fetchone()
            checks["purpose_write"] = (
                purpose_row is not None
                and str(purpose_row[0]) == "CONFIRMED"
            )

            state = product.update_presentation_state(
                {"mood": 73, "energy": 64, "bond": 11},
                updated_at=now + timedelta(seconds=13),
            )
            checks["presentation_write"] = (
                int(state["mood"]) == 73
                and int(state["energy"]) == 64
                and int(state["bond"]) == 11
            )

            export = NativeCanonicalExporter(db).build(
                identity_id=identity_id
            )
            data = export["data"]
            checks["export_complete"] = (
                bool(data.get("self_identity"))
                and bool(data.get("self_persona_versions"))
                and "relationship_transitions" in data
                and "promise_candidates" in data
                and "promise_transitions" in data
                and bool(data.get("memory_proposal_decisions"))
                and "presentation_state" not in data
            )

            rebuilt_path = root / "rebuilt.sqlite3"
            rebuild = TemporalFactService(db).rebuild_into(
                Database(rebuilt_path),
                identity_id=identity_id,
            )
            checks["rebuild_equal"] = (
                rebuild["snapshot"]
                == TemporalFactService(db).authority_snapshot(
                    identity_id=identity_id
                )
            )

            legacy_after = self._legacy_watermarks(db)
            checks["legacy_watermarks_unchanged"] = (
                legacy_after == legacy_before
            )

            external_generation, db_generation = (
                self._erasure_generations(
                    db, identity_id
                )
            )
            controller = AuthorityCutoverController(db)
            controller.activate(
                identity_id=identity_id,
                evidence=AuthorityCutoverEvidence(
                    shadow_caught_up=True,
                    rebuild_equal=checks["rebuild_equal"],
                    unresolved_conflicts=0,
                    erasure_generation_source=
                        external_generation,
                    erasure_generation_shadow=
                        db_generation,
                    source_order_ok=True,
                    old_writer_fenced=False,
                    # Read readiness is an independent gate. The disposable
                    # write drill assumes it only to cross the writer fence.
                    canonical_read_path_ready=True,
                    canonical_write_path_ready=True,
                ),
                activated_at=now + timedelta(seconds=14),
            )
            post = CanonicalProductStore(
                db,
                identity_id=identity_id,
            )
            post_turn = post.record_user_turn(
                source_event_key="__write_drill_post_cutover_v1",
                text="post-cutover drill write",
                observed_at=now + timedelta(seconds=15),
            )
            post_memory = post.save_memory(
                memory_id="__write_drill_post_cutover",
                mutation_id="__write_drill_post_cutover_memory",
                source_event_id=post_turn.event_id,
                principal_id="owner",
                text="post-cutover drill write",
                category="other",
                priority=2,
                created_at=now + timedelta(seconds=15),
            )
            post.update_presentation_state(
                {"mood": 74},
                updated_at=now + timedelta(seconds=15),
            )
            checks["post_cutover_write"] = (
                post_memory.revision == 1
                and post.presentation_state()["mood"] == 74
                and controller.verify_legacy_writer_frozen(
                    identity_id
                )
            )

        evidence = CanonicalWriteReadinessEvidence(
            **checks
        )
        return self._write_status(
            identity_id=identity_id,
            evidence=evidence,
            updated_at=now,
        )
