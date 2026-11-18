from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta

from xiaoyu.core.effects import (
    DispatchOutcome,
    DispatchStatus,
    EffectBindingError,
)
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime import OutboxDispatcher
from xiaoyu.tests import test_execution_reliability_minisprint as fixture_module


NOW = fixture_module.NOW


class ScheduledPurposeOccurrenceBindingRedTeamTests(unittest.TestCase):
    def _scheduled(self, db, *, due):
        fixture = fixture_module.ExecutionReliabilityMiniSprintRedTeamTests()
        fixture._insert_purpose(db)
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """UPDATE purposes
                   SET state='SCHEDULED',
                       scheduled_wall_time=?,
                       timezone='UTC',
                       resolved_utc_time=?
                   WHERE purpose_id='purpose-1'""",
                (
                    due.isoformat(timespec="microseconds"),
                    due.isoformat(timespec="microseconds"),
                ),
            )
        return fixture

    def test_future_scheduled_purpose_cannot_dispatch_without_occurrence(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = fixture_module.ExecutionReliabilityMiniSprintRedTeamTests()
            db = fixture._db(td)
            fixture = self._scheduled(
                db,
                due=NOW + timedelta(hours=1),
            )

            with self.assertRaises(EffectBindingError):
                fixture._enqueue(db)

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_final_preflight_blocks_legacy_queued_scheduled_effect(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = fixture_module.ExecutionReliabilityMiniSprintRedTeamTests()
            db = fixture._db(td)
            fixture._insert_purpose(db)

            # Simulate an effect already committed under an older/permissive
            # state before the scheduler authority became durable.
            fixture._enqueue(db)
            future = NOW + timedelta(hours=1)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purposes
                       SET state='SCHEDULED',
                           scheduled_wall_time=?,
                           timezone='UTC',
                           resolved_utc_time=?
                       WHERE purpose_id='purpose-1'
                         AND revision=1""",
                    (
                        future.isoformat(timespec="microseconds"),
                        future.isoformat(timespec="microseconds"),
                    ),
                )

            calls = []

            def transport(payload, idem):
                calls.append((payload, idem))
                return DispatchOutcome(DispatchStatus.SUCCEEDED)

            processed = OutboxDispatcher(
                db,
                {"qq": transport},
            ).dispatch_once(now=NOW)

            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])
            conn = db.connect()
            try:
                row = conn.execute(
                    """SELECT dispatch_state,verifier_state
                       FROM effects WHERE effect_id='effect-1'"""
                ).fetchone()
                self.assertEqual(row["dispatch_state"], "FAILED")
                self.assertIn(
                    "PURPOSE_OCCURRENCE_NOT_ACTIVATED",
                    row["verifier_state"],
                )
            finally:
                conn.close()

    def test_activated_scheduled_purpose_requires_current_occurrence_binding(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = fixture_module.ExecutionReliabilityMiniSprintRedTeamTests()
            db = fixture._db(td)
            fixture = self._scheduled(
                db,
                due=NOW - timedelta(seconds=1),
            )

            with db.transaction(immediate=True) as conn:
                scheduled = PurposeRepository().get(conn, "purpose-1")
                occurrence_id = PurposeRepository().activate_occurrence(
                    conn,
                    scheduled,
                    NOW,
                )
                self.assertTrue(occurrence_id)

            # The scheduled Purpose is now ACTIVE, but its execution identity is
            # the durable occurrence. A parallel effect without that occurrence
            # must not be allowed to bypass the scheduler.
            with self.assertRaises(EffectBindingError):
                fixture._enqueue(db)

            conn = db.connect()
            try:
                occurrence = conn.execute(
                    """SELECT state,effect_id FROM purpose_occurrences
                       WHERE occurrence_id=?""",
                    (occurrence_id,),
                ).fetchone()
                self.assertEqual(tuple(occurrence), ("READY", None))
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
                    0,
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
