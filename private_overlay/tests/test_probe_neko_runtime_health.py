import importlib.util
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("probe_neko_runtime_health", TOOLS / "probe_neko_runtime_health.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def _responses(*, running=True, forbidden=False):
    def request(url, **_kwargs):
        if url.endswith("/agent/flags"):
            return {
                "agent_flags": {
                    "computer_use_enabled": forbidden,
                    "browser_use_enabled": False,
                    "user_plugin_enabled": True,
                },
                "analyzer_enabled": False,
                "master_enabled": False,
            }
        if "/plugins?" in url:
            return {"plugins": [{
                "id": "alpha", "status": "running" if running else "stopped",
                "runtime_enabled": True, "runtime_auto_start": True,
                "autostart_pending": False,
            }]}
        return {"status": "ok"}
    return request


class RuntimeHealthTests(unittest.TestCase):
    def test_healthy_path_is_read_only_fast_and_does_not_reconcile(self):
        reconcile_calls = []
        started = time.monotonic()
        with patch.object(mod.runtime_reconcile, "_json_request", side_effect=_responses()):
            result = mod.check_and_repair(
                service_urls={"main": "http://host/main-health"},
                plugin_url="http://host", agent_url="http://host",
                request_timeout=.1, reconcile_fn=lambda **kw: reconcile_calls.append(kw),
            )
        self.assertEqual(result["verdict"], "PASS")
        self.assertFalse(result["repair_attempted"])
        self.assertEqual(reconcile_calls, [])
        self.assertLess(time.monotonic() - started, .25)

    def test_missing_plugin_reconciles_exactly_once_then_reprobes(self):
        calls = []
        request = _responses(running=False)
        def reconcile(**kwargs):
            calls.append(kwargs)
            return {"verdict": "PASS"}
        with patch.object(mod.runtime_reconcile, "_json_request", side_effect=lambda url, **kw: (_responses(running=True)(url, **kw) if calls else request(url, **kw))):
            result = mod.check_and_repair(
                service_urls={"main": "http://host/main-health"},
                plugin_url="http://host", agent_url="http://host",
                request_timeout=.1, reconcile_fn=reconcile,
            )
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["repair_attempts"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["before"]["not_running"], ["alpha"])
        self.assertEqual(result["after"]["not_running"], [])

    def test_forbidden_agent_capability_fails_without_repair(self):
        with patch.object(mod.runtime_reconcile, "_json_request", side_effect=_responses(forbidden=True)):
            result = mod.check_and_repair(
                service_urls={"main": "http://host/main-health"},
                plugin_url="http://host", agent_url="http://host",
                request_timeout=.1,
            )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["after"]["forbidden_agent_capabilities_enabled"], ["computer"])
        self.assertFalse(result["repair_attempted"])


if __name__ == "__main__":
    unittest.main()
