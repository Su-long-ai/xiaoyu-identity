from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
