from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from xiaoyu.contracts import AuthorizationDecision
from xiaoyu.core.authorization import AuthorizationResult
from xiaoyu.core.effects import (
    DispatchOutcome,
    DispatchStatus,
    EffectBindingError,
    EffectCoordinator,
)
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime import OutboxDispatcher, PurposeScheduler
from xiaoyu.tests.test_effect_outbox import (
    NOW,
    action,
    actor,
    context,
    delegation,
    effect,
    principal,
    resource,
)


class OccurrenceEffectExclusivityRedTeamTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO canonical_events(
                       event_id,identity_id,turn_id,event_type,surface,source_type,
                       principal_id,audience_scope,context_space,trust_class,
                       taint_json,eligible_for_memory,payload_type,payload_json,
                       observed_at,recorded_at,correlation_id,schema_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "source-occurrence",
                    "fish-1",
                    None,
                    "conversation.user",
                    "desktop",
                    "text",
                    "owner",
                    "PRIVATE",
                    "PERSONAL",
                    "OWNER_DIRECT",
                    "[]",
                    1,
                    "text/plain",
                    "{}",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    "corr-occurrence",
                    1,
                ),
            )
            PurposeRepository().insert(
                conn,
                Purpose(
                    purpose_id="purpose-1",
                    identity_id="fish-1",
                    owner_type=PurposeOwner.USER,
                    owner_id="owner",
                    state=PurposeState.SCHEDULED,
                    kind=PurposeKind.REMINDER,
                    source_event_id="source-occurrence",
                    payload={},
                    scheduled_wall_time=NOW.isoformat(timespec="minutes"),
                    timezone_name="UTC",
                    resolved_utc_time=NOW,
                    miss_policy=MissPolicy.DELIVER_LATE,
                    revision=1,
                ),
                NOW - timedelta(minutes=1),
            )
        decisions = PurposeScheduler(db, "fish-1").reconcile_due(NOW)
        self.assertEqual(len(decisions), 1)
        self.assertIsNotNone(decisions[0].occurrence_id)
        return db, decisions[0].occurrence_id

    def _enqueue(self, db, occurrence_id, suffix):
        idem = "idem-occurrence-" + suffix
        current_principal = replace(
            principal(),
            expires_at=NOW + timedelta(hours=1),
        )
        current_delegation = replace(
            delegation(),
            valid_from=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
        )
        eff = replace(
            effect(replayable=True, idempotency_key=idem),
            effect_id="effect-" + suffix,
            intent_id="intent-" + suffix,
            created_at=NOW,
            purpose_revision=1,
            purpose_occurrence_id=occurrence_id,
        )
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-" + suffix,
            outbox_id="outbox-" + suffix,
            identity_id="fish-1",
            principal=current_principal,
            actor=actor(),
            delegation=current_delegation,
            action=action(replayable=True, idempotency_key=idem),
            resource=resource(),
            context=context(),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                "del-1",
            ),
            effect=eff,
            destination="qq",
            payload=eff.request,
            created_at=NOW,
        )

    def test_second_effect_cannot_bind_same_ready_occurrence(self):
        with tempfile.TemporaryDirectory() as td:
            db, occurrence_id = self._db(td)
            self._enqueue(db, occurrence_id, "a")
            with self.assertRaises(EffectBindingError):
                self._enqueue(db, occurrence_id, "b")

            conn = db.connect()
            try:
                owner = conn.execute(
                    """SELECT state,effect_id FROM purpose_occurrences
                       WHERE occurrence_id=?""",
                    (occurrence_id,),
                ).fetchone()
                self.assertEqual(tuple(owner), ("READY", "effect-a"))
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_two_workers_cannot_cross_transport_for_same_occurrence(self):
        with tempfile.TemporaryDirectory() as td:
            db, occurrence_id = self._db(td)
            self._enqueue(db, occurrence_id, "a")

            # Simulate a pre-fix/legacy database where queued effects existed
            # before occurrence ownership was persisted.
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purpose_occurrences SET effect_id=NULL
                       WHERE occurrence_id=?""",
                    (occurrence_id,),
                )
            self._enqueue(db, occurrence_id, "b")
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purpose_occurrences SET effect_id=NULL
                       WHERE occurrence_id=?""",
                    (occurrence_id,),
                )

            first_linearized = threading.Event()
            release_first = threading.Event()
            calls = []
            calls_lock = threading.Lock()

            def first_fault(stage, row):
                if stage == "before_dispatch":
                    first_linearized.set()
                    if not release_first.wait(5):
                        raise RuntimeError("timed out waiting for second worker")

            def transport(payload, idem):
                with calls_lock:
                    calls.append(idem)
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="msg-" + str(idem),
                )

            first = OutboxDispatcher(
                db,
                {"qq": transport},
                fault_hook=first_fault,
            )

            first_error = []

            def run_first():
                try:
                    first.dispatch_once(limit=1, now=NOW)
                except BaseException as exc:
                    first_error.append(exc)

            thread = threading.Thread(target=run_first)
            thread.start()
            self.assertTrue(first_linearized.wait(5))

            # Worker A has already committed occurrence CLAIMED for effect-a but
            # has not crossed transport. Worker B must not claim the same
            # occurrence for effect-b.
            second_processed = OutboxDispatcher(
                db,
                {"qq": transport},
            ).dispatch_once(limit=1, now=NOW)

            release_first.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(first_error, [])

            self.assertEqual(
                len(calls),
                1,
                "two effects crossed transport for one Purpose occurrence",
            )
            self.assertEqual(second_processed, 0)


if __name__ == "__main__":
    unittest.main()
