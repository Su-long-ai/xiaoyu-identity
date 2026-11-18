from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta

from xiaoyu.core.effects import DispatchOutcome, DispatchStatus
from xiaoyu.runtime import OutboxDispatcher
from xiaoyu.tests.test_execution_reliability_minisprint import (
    ExecutionReliabilityMiniSprintRedTeamTests,
    NOW,
)


class ClaimCrashRetryBudgetRedTeamTests(unittest.TestCase):
    def test_pretransport_claim_crashes_do_not_consume_transport_retry_budget(self):
        class SimulatedCrash(BaseException):
            pass

        fixture = ExecutionReliabilityMiniSprintRedTeamTests()
        with tempfile.TemporaryDirectory() as td:
            db = fixture._db(td)
            fixture._insert_purpose(db)
            fixture._enqueue(db)

            def crash_after_claim(stage, row):
                if stage == "after_claim":
                    raise SimulatedCrash()

            # Two process deaths occur after durable claim but before the
            # DISPATCHING linearization point. No transport call is possible.
            for offset in (0, 1):
                dispatcher = OutboxDispatcher(
                    db,
                    {"qq": lambda payload, idem: None},
                    fault_hook=crash_after_claim,
                    max_attempts=2,
                )
                with self.assertRaises(SimulatedCrash):
                    dispatcher.dispatch_once(
                        now=NOW + timedelta(seconds=offset)
                    )
                OutboxDispatcher(
                    db,
                    {"qq": lambda payload, idem: None},
                    max_attempts=2,
                ).recover_inflight(
                    NOW + timedelta(seconds=offset, microseconds=1)
                )

            transport_calls = []

            def retryable(payload, idem):
                transport_calls.append((payload, idem))
                return DispatchOutcome(
                    DispatchStatus.FAILED_RETRYABLE,
                    retry_after_s=1,
                )

            self.assertEqual(
                OutboxDispatcher(
                    db,
                    {"qq": retryable},
                    max_attempts=2,
                ).dispatch_once(now=NOW + timedelta(seconds=3)),
                1,
            )
            self.assertEqual(len(transport_calls), 1)

            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT state,attempt_count FROM outbox"
                ).fetchone()
                # Retry budget counts actual transport attempts, not safe
                # pre-dispatch claims recovered after process crashes.
                self.assertEqual(tuple(row), ("FAILED_RETRYABLE", 1))
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "QUEUED",
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
