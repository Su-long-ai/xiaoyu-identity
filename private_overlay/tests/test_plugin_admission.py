from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "tools" / "check_plugin_admission.py"

spec = importlib.util.spec_from_file_location("check_plugin_admission", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(checker)


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

    def test_manual_only_manifest_drift_is_unaffected(self):
        active = checker.validate_state(
            self.policy,
            {"qq_auto_reply": {"enabled": True, "auto_start": False}},
            {"pending": []},
        )
        self.assertEqual(active, set())


if __name__ == "__main__":
    unittest.main()
