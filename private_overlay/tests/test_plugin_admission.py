from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "tools" / "check_plugin_admission.py"

spec = importlib.util.spec_from_file_location("check_plugin_admission", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(checker)

REPO_CHECKER_PATH = ROOT / "tools" / "check_plugin_admission_repo.py"
repo_spec = importlib.util.spec_from_file_location(
    "check_plugin_admission_repo",
    REPO_CHECKER_PATH,
)
repo_checker = importlib.util.module_from_spec(repo_spec)
assert repo_spec and repo_spec.loader
repo_spec.loader.exec_module(repo_checker)


class PluginAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(
            (ROOT / "governance" / "plugin_admission_v1.json").read_text(
                encoding="utf-8-sig"
            )
        )

    def test_current_policy_is_admission_not_sandbox(self):
        self.assertEqual(
            self.policy["policy_id"],
            "XIAOYU_PLUGIN_AUTOSTART_ADMISSION_V1",
        )
        security = self.policy["security_model"]
        self.assertTrue(security["admission_only_not_sandbox"])
        self.assertTrue(
            security["capability_grants_are_not_malicious_plugin_isolation"]
        )
        self.assertTrue(security["no_private_permission_store"])
        self.assertTrue(security["no_private_plugin_host"])

    def test_current_autostart_allowlist_is_small_and_provenanced(self):
        admitted = self.policy["admitted_autostart_plugins"]
        self.assertEqual(
            set(admitted),
            {
                "proactive_controller",
                "web_search",
                "qq_auto_reply",
                "xiaoyu_interaction_policy",
            },
        )
        self.assertEqual(admitted["proactive_controller"]["provenance"], "neko_native")
        self.assertEqual(admitted["web_search"]["provenance"], "neko_native")
        self.assertEqual(admitted["qq_auto_reply"]["provenance"], "pinned_external")
        self.assertEqual(
            admitted["qq_auto_reply"]["tested_commit"],
            "54acf36bf978edad4757e5fffc743c5618360700",
        )
        self.assertEqual(
            admitted["xiaoyu_interaction_policy"]["provenance"],
            "private_reviewed",
        )

    def test_unknown_enabled_autostart_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "unreviewed runtime auto-start"):
            checker.validate_state(
                self.policy,
                {
                    "proactive_controller": {"enabled": True, "auto_start": True},
                    "surprise_plugin": {"enabled": True, "auto_start": True},
                },
                {"pending": []},
            )

    def test_disabled_or_manual_only_unknown_plugin_is_not_blocked(self):
        active = checker.validate_state(
            self.policy,
            {
                "proactive_controller": {"enabled": True, "auto_start": True},
                "manual_plugin": {"enabled": True, "auto_start": False},
                "disabled_plugin": {"enabled": False, "auto_start": True},
            },
            {"pending": []},
        )
        self.assertEqual(active, {"proactive_controller"})

    def test_pending_plugin_cannot_be_active_autostart(self):
        with self.assertRaisesRegex(RuntimeError, "pending plugin"):
            checker.validate_state(
                self.policy,
                {"qq_auto_reply": {"enabled": True, "auto_start": True}},
                {"pending": ["qq_auto_reply"]},
            )

    def test_current_reviewed_manifests_pass(self):
        neko_root = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
        if not neko_root.is_dir():
            self.skipTest("local N.E.K.O checkout is unavailable")
        checker.validate_active_manifests(
            self.policy,
            set(self.policy["admitted_autostart_plugins"]),
            neko_root,
        )

    def test_ui_permission_expansion_fails(self):
        allowance = self.policy["admitted_autostart_plugins"]["qq_auto_reply"][
            "reviewed_manifest"
        ]
        manifest = copy.deepcopy(allowance)
        manifest["ui"]["panel"][0]["permissions"].append("filesystem:write")
        with self.assertRaisesRegex(RuntimeError, "UI permission expansion"):
            checker.validate_manifest_allowance("qq_auto_reply", manifest, allowance)

    def test_dependency_expansion_fails(self):
        allowance = self.policy["admitted_autostart_plugins"][
            "xiaoyu_interaction_policy"
        ]["reviewed_manifest"]
        manifest = copy.deepcopy(allowance)
        manifest["dependency"].append({"id": "surprise_plugin", "untested": ">=0"})
        with self.assertRaisesRegex(RuntimeError, "dependency expansion"):
            checker.validate_manifest_allowance("xiaoyu_interaction_policy", manifest, allowance)

    def test_model_capability_expansion_fails(self):
        allowance = self.policy["admitted_autostart_plugins"][
            "xiaoyu_interaction_policy"
        ]["reviewed_manifest"]
        manifest = copy.deepcopy(allowance)
        manifest["models"]["interaction_classifier"]["capabilities"].append("vision")
        with self.assertRaisesRegex(RuntimeError, "model capability expansion"):
            checker.validate_manifest_allowance("xiaoyu_interaction_policy", manifest, allowance)

    def test_repo_checkout_native_manifest_expansion_fails_closed(self):
        policy = copy.deepcopy(self.policy)
        policy["admitted_autostart_plugins"] = {
            "proactive_controller": policy["admitted_autostart_plugins"][
                "proactive_controller"
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = root / "plugin" / "plugins" / "proactive_controller"
            plugin.mkdir(parents=True)
            (plugin / "plugin.toml").write_text(
                """
[plugin]
id = "proactive_controller"
entry = "plugin.plugins.proactive_controller:ProactiveControllerPlugin"

[[plugin.dependency]]
id = "surprise_plugin"
untested = ">=0"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "dependency expansion"):
                repo_checker.validate_repo(policy, neko_root=root)

    def test_repo_checkout_pinned_external_manifest_and_head_are_verified(self):
        policy = copy.deepcopy(self.policy)
        policy["admitted_autostart_plugins"] = {
            "qq_auto_reply": policy["admitted_autostart_plugins"][
                "qq_auto_reply"
            ]
        }
        expected = policy["admitted_autostart_plugins"]["qq_auto_reply"][
            "tested_commit"
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = root / "plugin" / "plugins" / "qq_auto_reply"
            plugin.mkdir(parents=True)
            manifest = """
[plugin]
id = "qq_auto_reply"
type = "plugin"
entry = "plugin.plugins.qq_auto_reply:QQAutoReplyPlugin"

[plugin.ui]
enabled = true

[[plugin.ui.panel]]
id = "main"
entry = "static/index.html"
context = "qq_auto_reply"
permissions = ["state:read", "action:call"]
""".strip() + "\n"
            (plugin / "plugin.toml").write_text(manifest, encoding="utf-8")

            with patch.object(repo_checker, "_git_head", return_value=expected):
                self.assertEqual(
                    repo_checker.validate_repo(policy, neko_root=root),
                    ["qq_auto_reply"],
                )

            expanded = manifest.replace(
                'permissions = ["state:read", "action:call"]',
                'permissions = ["state:read", "action:call", "filesystem:write"]',
            )
            (plugin / "plugin.toml").write_text(expanded, encoding="utf-8")
            with patch.object(repo_checker, "_git_head", return_value=expected):
                with self.assertRaisesRegex(RuntimeError, "UI permission expansion"):
                    repo_checker.validate_repo(policy, neko_root=root)

            (plugin / "plugin.toml").write_text(manifest, encoding="utf-8")
            with patch.object(repo_checker, "_git_head", return_value="deadbeef"):
                with self.assertRaisesRegex(RuntimeError, "checkout drifted"):
                    repo_checker.validate_repo(policy, neko_root=root)

    def test_manual_only_manifest_drift_is_unaffected(self):
        active = checker.validate_state(
            self.policy,
            {"qq_auto_reply": {"enabled": True, "auto_start": False}},
            {"pending": []},
        )
        self.assertEqual(active, set())


if __name__ == "__main__":
    unittest.main()
