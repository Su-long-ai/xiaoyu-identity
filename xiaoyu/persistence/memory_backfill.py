from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Optional

from xiaoyu.contracts import Taint, TrustClass
from xiaoyu.core.memory import CanonicalMemoryService
from xiaoyu.core.temporal import (
    FactMutationOperation,
    FactMutationRequest,
    TemporalFactService,
)
from xiaoyu.persistence import Database


class LegacyMemoryBackfillError(RuntimeError):
    pass


class _LegacyOwnerMemoryAdmissionPolicy:
    """Migration-only compatibility for old user events without principal_id."""

    FORBIDDEN_TAINTS = {
        Taint.MODEL_INFERRED,
        Taint.THIRD_PARTY_DATA,
        Taint.UNTRUSTED_INSTRUCTION,
    }

    def require(self, event, authenticated_principal_id: str) -> None:
        if not authenticated_principal_id:
            raise LegacyMemoryBackfillError(
                "authenticated migration principal is required"
            )
        if event.source_namespace != "legacy":
            raise LegacyMemoryBackfillError(
                "legacy memory backfill requires legacy source event"
            )
        if event.trust_class not in {
            TrustClass.OWNER_DIRECT,
            TrustClass.OWNER_AUTHENTICATED_DEVICE,
        }:
            raise LegacyMemoryBackfillError(
                "legacy memory source is not owner-authored"
            )
        if event.principal_id not in {
            None,
            authenticated_principal_id,
        }:
            raise LegacyMemoryBackfillError(
                "legacy memory source principal mismatch"
            )
        if not event.eligible_for_memory:
            raise LegacyMemoryBackfillError(
                "legacy memory source is not memory eligible"
            )
        if event.payload_type != (
            "application/x-xiaoyu-legacy-event+json"
        ):
            raise LegacyMemoryBackfillError(
                "migration-only principal compatibility cannot "
                "admit non-legacy payload"
            )
        if set(event.taint).intersection(self.FORBIDDEN_TAINTS):
            raise LegacyMemoryBackfillError(
                "tainted legacy source cannot enter memory authority"
            )


@dataclass(frozen=True)
class LegacyMemoryBackfillReport:
    identity_id: str
    considered_rows: int
    active_rows: int
    inactive_rows: int
    asserted: int
    lifecycle_closed: int
    skipped_rows: int
    converged: bool


class LegacyMemoryTemporalBackfill:
    """Translate legacy confirmed memories into R9 memory facts."""

    ACTIVE = "active"
    INACTIVE = {"retracted", "archived", "superseded"}
    SKIP_CATEGORIES = {"bootstrap", "legacy"}

    def __init__(
        self,
        db: Database,
        *,
        principal_id: str = "owner",
    ) -> None:
        self.db = db
        self.principal_id = principal_id
        temporal = TemporalFactService(
            db,
            admission_policy=_LegacyOwnerMemoryAdmissionPolicy(),
        )
        self.memory = CanonicalMemoryService(
            db,
            temporal_service=temporal,
        )

    @staticmethod
    def _canonical_event_id(legacy_event_id) -> str:
        return "legacy:%d" % int(legacy_event_id)

    @staticmethod
    def _extra(row) -> dict:
        try:
            value = json.loads(str(row["extra"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _lifecycle_events(self, conn) -> dict[int, dict]:
        result: dict[int, dict] = {}
        rows = conn.execute(
            """SELECT event_id,at,kind,content,extra
               FROM events
               WHERE kind IN (
                   'memory.corrected',
                   'memory.retracted',
                   'memory.archived'
               )
               ORDER BY event_id"""
        ).fetchall()
        for row in rows:
            kind = str(row["kind"])
            memory_id = None
            if kind == "memory.corrected":
                extra = self._extra(row)
                memory_id = extra.get("supersedes_memory_id")
            else:
                try:
                    memory_id = int(str(row["content"]))
                except (TypeError, ValueError):
                    memory_id = None
            if memory_id is None:
                continue
            result[int(memory_id)] = {
                "event_id": int(row["event_id"]),
                "at": str(row["at"]),
                "kind": kind,
            }
        return result

    @staticmethod
    def _canonical_event_exists(conn, event_id: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM canonical_events WHERE event_id=?",
            (event_id,),
        ).fetchone() is not None

    def _assert_row(
        self,
        row,
        *,
        source_event_id: str,
    ):
        memory_id = "legacy:%d" % int(row["memory_id"])
        value = self.memory._value(
            memory_id=memory_id,
            text=str(row["text"]),
            category=str(row["category"]),
            priority=int(row["priority"]),
        )
        return self.memory.temporal_service.apply(
            FactMutationRequest(
                mutation_id=(
                    "legacy-memory:%d:assert"
                    % int(row["memory_id"])
                ),
                source_event_id=source_event_id,
                authenticated_principal_id=self.principal_id,
                subject=self.memory.subject(memory_id),
                predicate="remembered_item",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value=value,
                principal_scope=self.principal_id,
            )
        )

    def _close_row(
        self,
        row,
        *,
        lifecycle_event_id: str,
    ):
        memory_id = "legacy:%d" % int(row["memory_id"])
        status = str(row["status"])
        return self.memory.temporal_service.apply(
            FactMutationRequest(
                mutation_id=(
                    "legacy-memory:%d:%s"
                    % (int(row["memory_id"]), status)
                ),
                source_event_id=lifecycle_event_id,
                authenticated_principal_id=self.principal_id,
                subject=self.memory.subject(memory_id),
                predicate="remembered_item",
                operation=FactMutationOperation.RETRACT,
                expected_revision=1,
                principal_scope=self.principal_id,
            )
        )

    def run(self, identity_id: str) -> LegacyMemoryBackfillReport:
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT memory_id,created_at,updated_at,category,text,
                          source_event,priority,status,change_seq
                   FROM memories
                   ORDER BY change_seq,memory_id"""
            ).fetchall()
            lifecycle = self._lifecycle_events(conn)

        considered = active = inactive = asserted = closed = skipped = 0
        for row in rows:
            category = str(row["category"])
            status = str(row["status"])
            if category in self.SKIP_CATEGORIES or status == "bootstrap":
                skipped += 1
                continue
            if status not in {self.ACTIVE, *self.INACTIVE}:
                raise LegacyMemoryBackfillError(
                    "unsupported legacy memory status %s" % status
                )
            considered += 1
            source_event = row["source_event"]
            if source_event is None:
                raise LegacyMemoryBackfillError(
                    "legacy memory %s has no canonical source event"
                    % row["memory_id"]
                )
            source_event_id = self._canonical_event_id(
                source_event
            )
            with self.db.transaction() as conn:
                if not self._canonical_event_exists(
                    conn, source_event_id
                ):
                    raise LegacyMemoryBackfillError(
                        "canonical source %s is missing; run event "
                        "backfill first" % source_event_id
                    )

            self._assert_row(
                row,
                source_event_id=source_event_id,
            )
            asserted += 1

            if status == self.ACTIVE:
                active += 1
                continue

            inactive += 1
            lifecycle_event = lifecycle.get(
                int(row["memory_id"])
            )
            if lifecycle_event is None:
                raise LegacyMemoryBackfillError(
                    "legacy memory %s status %s has no lifecycle event"
                    % (row["memory_id"], status)
                )
            lifecycle_event_id = self._canonical_event_id(
                lifecycle_event["event_id"]
            )
            with self.db.transaction() as conn:
                if not self._canonical_event_exists(
                    conn, lifecycle_event_id
                ):
                    raise LegacyMemoryBackfillError(
                        "canonical lifecycle event %s is missing"
                        % lifecycle_event_id
                    )
            self._close_row(
                row,
                lifecycle_event_id=lifecycle_event_id,
            )
            closed += 1

        with self.db.transaction() as conn:
            represented_active = conn.execute(
                """SELECT COUNT(*)
                   FROM temporal_facts tf
                   WHERE tf.identity_id=?
                     AND tf.principal_scope=?
                     AND tf.predicate='remembered_item'
                     AND tf.subject LIKE 'memory:legacy:%'
                     AND tf.status='CURRENT'""",
                (identity_id, self.principal_id),
            ).fetchone()[0]
            asserted_rows = conn.execute(
                """SELECT COUNT(*)
                   FROM fact_mutations
                   WHERE identity_id=?
                     AND mutation_id LIKE 'legacy-memory:%:assert'""",
                (identity_id,),
            ).fetchone()[0]
            closed_rows = conn.execute(
                """SELECT COUNT(*)
                   FROM fact_mutations
                   WHERE identity_id=?
                     AND (
                       mutation_id LIKE 'legacy-memory:%:retracted'
                       OR mutation_id LIKE 'legacy-memory:%:archived'
                       OR mutation_id LIKE 'legacy-memory:%:superseded'
                     )""",
                (identity_id,),
            ).fetchone()[0]

        converged = (
            int(represented_active) == active
            and int(asserted_rows) == considered
            and int(closed_rows) == inactive
        )
        return LegacyMemoryBackfillReport(
            identity_id=identity_id,
            considered_rows=considered,
            active_rows=active,
            inactive_rows=inactive,
            asserted=asserted,
            lifecycle_closed=closed,
            skipped_rows=skipped,
            converged=converged,
        )
