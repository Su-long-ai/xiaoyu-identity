from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "candidates" / "execution_plane" / "probe_neko_fac795_execution_migration.py"
SPEC = importlib.util.spec_from_file_location("fac_probe", MODULE_PATH)
assert SPEC and SPEC.loader
fac_probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fac_probe)


class Fac795ExecutionMigrationProbeTests(unittest.TestCase):
    def test_constants_pin_candidate_and_product(self) -> None:
        self.assertEqual(
            fac_probe.EXPECTED_CANDIDATE_SHA,
            "fac795091e33cd92a6604d14ac242510944badac",
        )
        self.assertEqual(
            fac_probe.EXPECTED_PRODUCT_SHA,
            "c3fc33ff0d32e4a79fd905d1add22d45725071f5",
        )
        self.assertEqual(fac_probe.BASE_PATCH_COUNT, 10)

    def test_semantic_matrix_detects_known_latest_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "nekopower" / "host"
            host.mkdir(parents=True)
            (host / "ledger.py").write_text(
                "status IN ('queued','working','waiting_user')\nHOST_ENDED_REASON\n",
                encoding="utf-8",
            )
            (host / "task_agents.py").write_text(
                "self._queue: deque[str]\n"
                "self._notes: dict[str, list[str]]\n"
                "self._resume: dict[str, str]\n",
                encoding="utf-8",
            )
            (host / "outbox.py").write_text("mark_sent()\n", encoding="utf-8")
            (host / "plugin_runs.py").write_text('status = "unknown"\n', encoding="utf-8")

            matrix = fac_probe._semantic_matrix(root)

        self.assertTrue(matrix["restart"]["prior_host_active_failed"])
        self.assertTrue(matrix["restart"]["queue_resume_notes_are_process_memory"])
        self.assertFalse(matrix["restart"]["native_durable_queue_epoch_events"])
        self.assertFalse(matrix["restart"]["equivalent_to_green_restart_stack"])
        self.assertFalse(matrix["delivery_effect"]["equivalent_to_0011_0012"])
        self.assertFalse(matrix["plugin_effect"]["equivalent_to_0013_0014"])

    def test_semantic_matrix_requires_all_equivalence_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host = root / "nekopower" / "host"
            host.mkdir(parents=True)
            (host / "ledger.py").write_text(
                "restart_queue_resume\nrestart_queue_note\n"
                "delivery_handoff delivery_claimed delivery_uncertain delivery_receipt\n",
                encoding="utf-8",
            )
            (host / "task_agents.py").write_text("restart_queue_resume\n", encoding="utf-8")
            (host / "outbox.py").write_text(
                "delivery_handoff delivery_claimed delivery_uncertain delivery_receipt\n",
                encoding="utf-8",
            )
            (host / "plugin_runs.py").write_text(
                'if status == "unknown": pass\nidempotency_key = "x"\n',
                encoding="utf-8",
            )

            matrix = fac_probe._semantic_matrix(root)

        self.assertTrue(matrix["restart"]["equivalent_to_green_restart_stack"])
        self.assertTrue(matrix["delivery_effect"]["equivalent_to_0011_0012"])
        self.assertTrue(matrix["plugin_effect"]["equivalent_to_0013_0014"])


if __name__ == "__main__":
    unittest.main()
