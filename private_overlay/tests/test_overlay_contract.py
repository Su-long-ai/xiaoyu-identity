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
        self.assertEqual(lock["integration_mode"], "private_data_policy_overlay")
        self.assertEqual(lock["memory_authority"], "neko_native")
        self.assertEqual(lock["persona_storage_authority"], "neko_native")
        self.assertEqual(lock["evolution_authority"], "neko_native")
        self.assertEqual(lock["task_authority"], "neko_native")
        self.assertFalse(lock["allow_dual_write"])

    def test_core_patch_queue_stays_small_and_evidence_backed(self):
        lock = json.loads(
            (ROOT / "NEKO_UPSTREAM.lock.json").read_text(encoding="utf-8-sig")
        )
        series = json.loads(
            (ROOT / "patches" / "series.json").read_text(encoding="utf-8-sig")
        )
        patches = series["patches"]
        self.assertLessEqual(len(patches), lock["core_patch_budget"])
        self.assertEqual(lock["core_patch_budget"], 6)
        self.assertEqual(len(patches), 6)
        for patch in patches:
            self.assertTrue((ROOT / "patches" / patch["file"]).is_file())
            self.assertTrue(patch["reason"].strip())
            self.assertTrue((ROOT / patch["evidence"]).is_file())

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

    def test_private_runtime_plugins_are_exception_only_and_delegate_authority(self):
        plugins_dir = ROOT / "plugins"
        manifest = json.loads(
            (plugins_dir / "manifest.json").read_text(encoding="utf-8-sig")
        )
        allowed = manifest.get("allowed_private_runtime_plugins", [])
        allowed_ids = {item["id"] for item in allowed}

        actual_ids = {
            path.parent.name
            for path in plugins_dir.glob("*/__init__.py")
            if path.is_file()
        }
        self.assertEqual(
            actual_ids,
            allowed_ids,
            "Every private runtime plugin must be explicitly admitted by the overlay manifest",
        )

        for item in allowed:
            self.assertTrue(item["acceptance_gap"].strip())
            self.assertEqual(
                item["hard_execution_authority"],
                "neko_native:proactive_controller",
            )
            for authority_flag in (
                "owns_memory",
                "owns_persona",
                "owns_evolution",
                "owns_tasks",
                "owns_proactive_engine",
            ):
                self.assertFalse(
                    item[authority_flag],
                    f"{item['id']} must not duplicate N.E.K.O authority: {authority_flag}",
                )
            source_dir = ROOT / item["source_dir"]
            config = tomllib.loads(
                (source_dir / "plugin.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["plugin"]["id"], item["id"])
            dependency_ids = {
                dep.get("id")
                for dep in config["plugin"].get("dependency", [])
                if isinstance(dep, dict)
            }
            self.assertIn("proactive_controller", dependency_ids)
            self.assertTrue((ROOT / item["evidence"]).is_file())

    def test_startup_delegates_directly_to_neko_launcher(self):
        script = (ROOT / "tools" / "start_xiaoyu.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "setup_local.ps1",
            "-VerifyOnly",
            "ensure_neko_storage_policy.py",
            "ensure_private_plugin.py",
            "--source",
            "plugins\\xiaoyu_interaction_policy",
            "run_checks.ps1",
            "restore_neko_plugin_autostart.py",
            "NEKO_STORAGE_SELECTED_ROOT",
            "NEKO_STORAGE_ANCHOR_ROOT",
            "NEKO_RUNTIME_STATE_DIR",
            "NEKO_PRIVATE_SPEECH_GATE_FILE",
            "launcher.py",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("plugins\\xiaoyu_private", script)
        self.assertNotIn("start_plugin", script)


    def test_private_plugin_ensure_uses_native_package_workflow(self):
        script = (ROOT / "tools" / "ensure_private_plugin.py").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "build_plugin",
            "PluginCliService",
            "plan_install",
            "confirm_upgrade",
            "confirmation_token",
            "build_install_source_manager",
            "reconcile",
            "USER_PLUGIN_EXEC_ROOT",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("shutil.copytree", script)
        self.assertNotIn("copy2(", script)


    def test_shortcut_installer_is_relocatable_and_covers_product_entries(self):
        script = (ROOT / "tools" / "install_xiaoyu_shortcuts.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "$PSScriptRoot",
            "start_xiaoyu_oneclick.ps1",
            "open_api_cost.cmd",
            "http://127.0.0.1:48911/",
            "0x5C0F",
            "0x9C7C",
            "0x8D39",
            "0x7528",
        }
        for item in required:
            self.assertIn(item, script)
        self.assertNotIn("dsh-fish-overlay-audit", script)
        self.assertNotIn("xiaoyu_private_overlay_work", script)


    def test_setup_keeps_neko_ui_native_and_repairable(self):
        script = (ROOT / "tools" / "setup_local.ps1").read_text(
            encoding="utf-8-sig"
        )
        required = {
            "templates\\index.html",
            "frontend\\plugin-manager\\package.json",
            "frontend\\react-neko-chat\\package.json",
            "frontend\\plugin-manager\\dist\\index.html",
            "static\\react\\neko-chat\\neko-chat-window.iife.js",
            "sparse-checkout add frontend templates",
            "npm run build-only",
            "npm run build",
            "Ensure-NekoCorePatches",
            "git -C $NekoRoot apply --reverse --check",
            "git -C $NekoRoot apply --check",
        }
        for marker in required:
            self.assertIn(marker, script)
        self.assertNotIn("build_frontend.bat", script)
        self.assertNotIn("plugins\\xiaoyu_private", script)


if __name__ == "__main__":
    unittest.main()