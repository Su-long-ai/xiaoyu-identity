from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from check_provider_privacy import MODEL_TIERS, host_is_allowed


class ProviderPrivacyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = {
            "allow_localhost": True,
            "fail_closed_unknown_hosts": True,
            "allowed_host_suffixes": [
                "dashscope.aliyuncs.com",
                "api.deepseek.com",
            ],
            "explicitly_denied_host_suffixes": [
                "lanlan.tech",
                "openrouter.ai",
            ],
        }

    def test_direct_allowlisted_provider_is_allowed(self):
        self.assertEqual(host_is_allowed("dashscope.aliyuncs.com", self.policy), (True, "allowlist"))
        self.assertEqual(host_is_allowed("sub.dashscope.aliyuncs.com", self.policy), (True, "allowlist"))

    def test_relay_and_router_are_denied(self):
        self.assertEqual(host_is_allowed("www.lanlan.tech", self.policy), (False, "explicitly_denied"))
        self.assertEqual(host_is_allowed("openrouter.ai", self.policy), (False, "explicitly_denied"))

    def test_unknown_host_fails_closed(self):
        self.assertEqual(host_is_allowed("unknown.example", self.policy), (False, "unknown_host"))

    def test_localhost_is_allowed(self):
        self.assertEqual(host_is_allowed("127.0.0.1", self.policy), (True, "localhost"))
        self.assertEqual(host_is_allowed("localhost", self.policy), (True, "localhost"))

    def test_all_private_content_model_tiers_are_covered(self):
        required = {
            "conversation",
            "summary",
            "correction",
            "emotion",
            "vision",
            "agent",
            "realtime",
            "game_main",
            "game_summary",
        }
        self.assertTrue(required.issubset(set(MODEL_TIERS)))


if __name__ == "__main__":
    unittest.main()
