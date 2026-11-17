from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from xiaoyu.runtime.execution_resources import ExecutionResourceHandles


class ExecutionResourceHandleTests(unittest.TestCase):
    def test_cancel_releases_resource_once_and_is_idempotent(self):
        broker = ExecutionResourceHandles()
        calls = []

        broker.acquire(
            lease_id="lease-1",
            effect_id="effect-1",
            resource_id="provider-session:1",
            cancel=lambda: calls.append("cancel"),
            release=lambda: calls.append("release"),
        )

        first = broker.cancel("lease-1")
        second = broker.cancel("lease-1")

        self.assertEqual(first.state, "RELEASED")
        self.assertEqual(second.state, "RELEASED")
        self.assertEqual(calls, ["cancel", "release"])

    def test_cancel_failure_still_releases_local_resource(self):
        broker = ExecutionResourceHandles()
        calls = []

        def fail_cancel():
            calls.append("cancel")
            raise RuntimeError("provider refused cancel")

        broker.acquire(
            lease_id="lease-1",
            effect_id="effect-1",
            resource_id="subprocess:1",
            cancel=fail_cancel,
            release=lambda: calls.append("release"),
        )

        snapshot = broker.cancel("lease-1")
        self.assertEqual(snapshot.state, "RELEASED")
        self.assertIn("RuntimeError", snapshot.last_error)
        self.assertEqual(calls, ["cancel", "release"])

    def test_release_failure_is_visible_and_retryable(self):
        broker = ExecutionResourceHandles()
        attempts = []

        def flaky_release():
            attempts.append("release")
            if len(attempts) == 1:
                raise OSError("busy")

        broker.acquire(
            lease_id="lease-1",
            effect_id="effect-1",
            resource_id="file-lock:1",
            release=flaky_release,
        )

        failed = broker.release("lease-1")
        self.assertEqual(failed.state, "RELEASE_FAILED")
        self.assertIn("OSError", failed.last_error)

        recovered = broker.release("lease-1")
        self.assertEqual(recovered.state, "RELEASED")
        self.assertIsNone(recovered.last_error)
        self.assertEqual(len(attempts), 2)

    def test_concurrent_cancel_releases_once(self):
        broker = ExecutionResourceHandles()
        calls = []
        broker.acquire(
            lease_id="lease-1",
            effect_id="effect-1",
            resource_id="socket:1",
            cancel=lambda: calls.append("cancel"),
            release=lambda: calls.append("release"),
        )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: broker.cancel("lease-1"),
                    range(4),
                )
            )

        self.assertTrue(all(result.state == "RELEASED" for result in results))
        self.assertEqual(calls, ["cancel", "release"])

    def test_lease_id_cannot_be_rebound_to_another_effect(self):
        broker = ExecutionResourceHandles()
        broker.acquire(
            lease_id="lease-1",
            effect_id="effect-1",
            resource_id="socket:1",
            release=lambda: None,
        )
        with self.assertRaises(ValueError):
            broker.acquire(
                lease_id="lease-1",
                effect_id="effect-2",
                resource_id="socket:1",
                release=lambda: None,
            )


if __name__ == "__main__":
    unittest.main()
