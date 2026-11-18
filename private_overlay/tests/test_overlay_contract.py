import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OverlayContractTests(unittest.TestCase):
    def test_single_authority_contract(self):
        lock = json.loads(
            (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(lock["integration_mode"], "private_data_policy_overlay")
        self.assertEqual(lock["memory_authority"], "neko_native")
        self.assertEqual(lock["persona_storage_authority"], "neko_native")
        self.assertEqual(lock["evolution_authority"], "neko_native")
        self.assertEqual(lock["task_authority"], "neko_native")
        self.assertFalse(lock["allow_dual_write"])

    def test_initial_core_patch_queue_is_empty(self):
        lock = json.loads(
            (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        self.assertLessEqual(len(series["patches"]), lock["core_patch_budget"])
        self.assertEqual(series["patches"], [])

    def test_identity_contract_has_required_hard_invariants(self):
        data = json.loads(
            (ROOT / "identity" / "invariants.json").read_text(encoding="utf-8-sig")
        )
        required = {
            "same_identity_across_model_swap",
            "same_identity_across_restart",
            "same_identity_across_desktop_and_qq",
            "owner_correction_becomes_current",
            "erased_private_memory_must_not_resurrect",
            "private_context_must_not_widen_audience",
        }
        self.assertTrue(required.issubset(set(data["invariants"])))

    def test_growth_policy_is_data_only_and_neko_owns_evolution_runtime(self):
        data = json.loads(
            (ROOT / "identity" / "invariants.json").read_text(encoding="utf-8-sig")
        )
        self.assertTrue(data["allowed_growth"])
        self.assertTrue(data["forbidden_silent_changes"])

        evolution_dir = ROOT / "evolution"
        executable = list(evolution_dir.rglob("*.py")) if evolution_dir.exists() else []
        self.assertEqual(
            executable,
            [],
            "XiaoYu overlay must not grow a second persona/evolution runtime",
        )

    def test_no_private_runtime_plugin_is_required_by_default(self):
        plugins_dir = ROOT / "plugins"
        runtime_files = list(plugins_dir.rglob("*.py")) if plugins_dir.exists() else []
        self.assertEqual(
            runtime_files,
            [],
            "Do not keep a private XiaoYu runtime plugin without a concrete acceptance gap",
        )

    def test_startup_delegates_directly_to_neko_launcher(self):
        script = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "setup_local.ps1",
            "-VerifyOnly",
            "ensure_neko_storage_policy.py",
            "run_checks.ps1",
            "NEKO_STORAGE_SELECTED_ROOT",
            "NEKO_STORAGE_ANCHOR_ROOT",
            "NEKO_RUNTIME_STATE_DIR",
            "launcher.py",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("plugins\\xiaoyu_private", script)
        self.assertNotIn("start_plugin", script)


if __name__ == "__main__":
    unittest.main()