from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from xiaoyu.core.authorization import AuthorizationResult
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus, EffectCoordinator
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
    resolve_wall_time,
)
from xiaoyu.contracts import AuthorizationDecision
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime import OutboxDispatcher, PowerLifecycle, PurposeScheduler
from xiaoyu.tests.test_effect_outbox import (
    action,
    actor,
    context,
    delegation,
    effect,
    principal,
    resource,
)


UTC = timezone.utc
NOW = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)


class PurposeLifecycleRedTeamTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _insert_purpose(
        self,
        db,
        *,
        purpose_id="purpose-1",
        due=NOW,
        policy=MissPolicy.DELIVER_LATE,
        payload=None,
        timezone_name="Asia/Shanghai",
    ):
        wall = due.astimezone(ZoneInfo(timezone_name))
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO canonical_events(
                       event_id,identity_id,turn_id,event_type,surface,source_type,
                       principal_id,audience_scope,context_space,trust_class,
                       taint_json,eligible_for_memory,payload_type,payload_json,
                       observed_at,recorded_at,correlation_id,schema_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "purpose-source",
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
                    "purpose-source",
                    1,
                ),
            )
            PurposeRepository().insert(
                conn,
                Purpose(
                    purpose_id=purpose_id,
                    identity_id="fish-1",
                    owner_type=PurposeOwner.USER,
                    owner_id="owner",
                    state=PurposeState.SCHEDULED,
                    kind=PurposeKind.REMINDER,
                    source_event_id="purpose-source",
                    payload=payload or {},
                    scheduled_wall_time=wall.isoformat(
                        timespec="minutes"
                    ),
                    timezone_name=timezone_name,
                    resolved_utc_time=due,
                    miss_policy=policy,
                    revision=1,
                ),
                NOW - timedelta(hours=1),
            )

    def _enqueue_bound_effect(self, db, purpose_revision=1):
        current_principal = replace(
            principal(),
            expires_at=NOW + timedelta(hours=2),
        )
        current_delegation = replace(
            delegation(),
            valid_from=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=2),
        )
        with db.transaction() as conn:
            occurrence = conn.execute(
                """SELECT occurrence_id FROM purpose_occurrences
                   WHERE purpose_id='purpose-1'
                     AND purpose_revision=?
                     AND state='READY'""",
                (purpose_revision,),
            ).fetchone()
        if occurrence is None:
            raise AssertionError(
                "test fixture must activate the scheduled occurrence before enqueue"
            )
        eff = replace(
            effect(),
            created_at=NOW,
            purpose_revision=purpose_revision,
            purpose_occurrence_id=str(occurrence["occurrence_id"]),
        )
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-purpose",
            outbox_id="outbox-purpose",
            identity_id="fish-1",
            principal=current_principal,
            actor=actor(),
            delegation=current_delegation,
            action=action(),
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

    def test_on_time_reschedule_policy_executes_instead_of_rescheduling(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(
                db,
                due=NOW,
                policy=MissPolicy.RESCHEDULE,
                payload={"reschedule_seconds": 600},
            )
            decisions = PurposeScheduler(
                db, "fish-1"
            ).reconcile_due(NOW)
            self.assertEqual(len(decisions), 1)
            self.assertEqual(
                decisions[0].new_state,
                PurposeState.ACTIVE,
            )
            self.assertEqual(
                decisions[0].reason,
                "DUE_ON_TIME",
            )
            conn = db.connect()
            try:
                purpose_row = conn.execute(
                    "SELECT state,revision FROM purposes"
                ).fetchone()
                occurrence = conn.execute(
                    """SELECT state,purpose_revision
                       FROM purpose_occurrences"""
                ).fetchone()
                self.assertEqual(
                    tuple(purpose_row),
                    ("ACTIVE", 1),
                )
                self.assertEqual(
                    tuple(occurrence),
                    ("READY", 1),
                )
            finally:
                conn.close()

    def test_resume_persists_recoverable_ready_occurrence(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(
                db,
                due=NOW + timedelta(minutes=30),
                policy=MissPolicy.DELIVER_LATE,
            )
            power = PowerLifecycle(
                PurposeScheduler(db, "fish-1")
            )
            power.suspend(NOW)
            report = power.resume(NOW + timedelta(hours=3))
            self.assertEqual(report.reconciled_purposes, 1)

            # New scheduler/repository instance after the resume still sees
            # durable work; correctness does not depend on ResumeReport memory.
            with db.transaction() as conn:
                rows = PurposeRepository().list_ready_occurrences(
                    conn, "fish-1"
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["state"], "READY")

    def test_same_instant_with_plus8_offset_is_due(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            same_instant_plus8 = NOW.astimezone(
                timezone(timedelta(hours=8))
            )
            self._insert_purpose(
                db,
                due=same_instant_plus8,
                policy=MissPolicy.DELIVER_LATE,
            )
            decisions = PurposeScheduler(
                db, "fish-1"
            ).reconcile_due(NOW)
            self.assertEqual(len(decisions), 1)
            self.assertEqual(
                decisions[0].new_state,
                PurposeState.ACTIVE,
            )

    def test_nonexistent_dst_wall_time_is_rejected(self):
        gap = datetime(
            2026,
            3,
            8,
            2,
            30,
            tzinfo=ZoneInfo("America/Los_Angeles"),
        )
        with self.assertRaises(ValueError):
            resolve_wall_time(
                gap,
                "America/Los_Angeles",
            )

    def test_cancel_invalidates_queued_effect_before_transport(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            decisions = PurposeScheduler(
                db, "fish-1"
            ).reconcile_due(NOW)
            self.assertEqual(len(decisions), 1)
            self.assertIsNotNone(decisions[0].occurrence_id)
            self._enqueue_bound_effect(db, 1)
            with db.transaction(immediate=True) as conn:
                self.assertTrue(
                    PurposeRepository().cancel(
                        conn,
                        "purpose-1",
                        NOW + timedelta(seconds=1),
                    )
                )
            calls = []

            def transport(payload, idem):
                calls.append(payload)
                return DispatchOutcome(DispatchStatus.SUCCEEDED)

            processed = OutboxDispatcher(
                db, {"qq": transport}
            ).dispatch_once(
                now=NOW + timedelta(seconds=2)
            )
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])
            conn = db.connect()
            try:
                purpose_row = conn.execute(
                    "SELECT state,revision FROM purposes"
                ).fetchone()
                self.assertEqual(
                    tuple(purpose_row),
                    ("CANCELLED", 2),
                )
            finally:
                conn.close()

    def test_reschedule_invalidates_old_queued_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            decisions = PurposeScheduler(
                db, "fish-1"
            ).reconcile_due(NOW)
            self.assertEqual(len(decisions), 1)
            self.assertIsNotNone(decisions[0].occurrence_id)
            self._enqueue_bound_effect(db, 1)
            new_due = NOW + timedelta(hours=1)
            wall = new_due.astimezone(
                ZoneInfo("Asia/Shanghai")
            ).isoformat(timespec="minutes")
            with db.transaction(immediate=True) as conn:
                self.assertTrue(
                    PurposeRepository().reschedule(
                        conn,
                        "purpose-1",
                        wall,
                        "Asia/Shanghai",
                        new_due,
                        NOW + timedelta(seconds=1),
                    )
                )
            calls = []
            processed = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: (
                        calls.append(payload)
                        or DispatchOutcome(
                            DispatchStatus.SUCCEEDED
                        )
                    )
                },
            ).dispatch_once(
                now=NOW + timedelta(seconds=2)
            )
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_cancel_after_dispatch_linearization_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            decisions = PurposeScheduler(
                db, "fish-1"
            ).reconcile_due(NOW)
            self.assertEqual(len(decisions), 1)
            self.assertIsNotNone(decisions[0].occurrence_id)
            self._enqueue_bound_effect(db, 1)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE effects SET dispatch_state='DISPATCHING'
                       WHERE effect_id='effect-1'"""
                )
            with db.transaction(immediate=True) as conn:
                self.assertFalse(
                    PurposeRepository().cancel(
                        conn,
                        "purpose-1",
                        NOW + timedelta(seconds=1),
                    )
                )
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT state,revision FROM purposes"
                ).fetchone()
                self.assertEqual(
                    tuple(row),
                    ("NEEDS_RECONCILIATION", 1),
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
