import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OverlayContractTests(unittest.TestCase):
    def test_single_authority_contract(self):
        lock = json.loads(
            (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
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

    def test_plugin_manifest_is_thin_external_overlay(self):
        manifest_path = ROOT / "plugins" / "xiaoyu_private" / "plugin.toml"
        with manifest_path.open("rb") as fh:
            manifest = tomllib.load(fh)
        self.assertEqual(manifest["plugin"]["id"], "xiaoyu_private")
        self.assertEqual(manifest["plugin"]["type"], "plugin")
        self.assertEqual(
            manifest["plugin"]["entry"],
            "plugin.plugins.xiaoyu_private:XiaoYuPrivatePlugin",
        )
        self.assertFalse(manifest["plugin_runtime"]["auto_start"])
        self.assertIn("sdk", manifest["plugin"])


if __name__ == "__main__":
    unittest.main()
