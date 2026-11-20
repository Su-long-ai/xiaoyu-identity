import importlib.util
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "restore_neko_plugin_autostart.py"
SPEC = importlib.util.spec_from_file_location(
    "restore_neko_plugin_autostart", MODULE_PATH
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class _FakeHandler(BaseHTTPRequestHandler):
    state = {
        "refreshed": False,
        "starts": [],
        "agent_flags": {
            "computer_use_enabled": False,
            "browser_use_enabled": False,
            "user_plugin_enabled": False,
        },
        "analyzer_enabled": False,
        "agent_flag_posts": [],
        "plugins": [
            {
                "id": "qq_auto_reply",
                "runtime_enabled": True,
                "runtime_auto_start": True,
                "status": "stopped",
            },
            {
                "id": "web_search",
                "runtime_enabled": True,
                "runtime_auto_start": True,
                "status": "running",
            },
            {
                "id": "memo_reminder",
                "runtime_enabled": True,
                "runtime_auto_start": False,
                "status": "stopped",
            },
        ],
    }

    def log_message(self, *_args):
        return

    def _send(self, payload, status=200):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/config/page_config":
            self._send({"autostart_csrf_token": "test-token"})
            return
        if path == "/agent/flags":
            self._send({
                "success": True,
                "agent_flags": dict(self.state["agent_flags"]),
                "analyzer_enabled": self.state["analyzer_enabled"],
            })
            return
        if path == "/plugins":
            plugins = self.state["plugins"] if self.state["refreshed"] else []
            self._send({"plugins": plugins})
            return
        self._send({"detail": "not found"}, 404)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/agent/flags":
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            self.state["agent_flag_posts"].append(dict(body))
            if "user_plugin_enabled" in body:
                self.state["agent_flags"]["user_plugin_enabled"] = bool(
                    body["user_plugin_enabled"]
                )
            self._send({
                "success": True,
                "agent_flags": dict(self.state["agent_flags"]),
                "analyzer_enabled": self.state["analyzer_enabled"],
            })
            return
        if path == "/plugins/refresh":
            assert self.headers.get("Origin")
            assert self.headers.get("X-CSRF-Token") == "test-token"
            self.state["refreshed"] = True
            self._send({"success": True, "added": ["qq_auto_reply", "web_search"]})
            return
        if path.startswith("/plugin/") and path.endswith("/start"):
            plugin_id = path.split("/")[2]
            self.state["starts"].append(plugin_id)
            self._send({"success": True, "plugin_id": plugin_id})
            return
        self._send({"detail": "not found"}, 404)


class RestoreAutostartTests(unittest.TestCase):
    def setUp(self):
        _FakeHandler.state["refreshed"] = False
        _FakeHandler.state["starts"] = []
        _FakeHandler.state["agent_flags"] = {
            "computer_use_enabled": False,
            "browser_use_enabled": False,
            "user_plugin_enabled": False,
        }
        _FakeHandler.state["analyzer_enabled"] = False
        _FakeHandler.state["agent_flag_posts"] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_selects_only_enabled_native_autostart_plugins(self):
        needs, running = mod.select_autostart_candidates(
            _FakeHandler.state["plugins"]
        )
        self.assertEqual(needs, ["qq_auto_reply"])
        self.assertEqual(running, ["web_search"])

    def test_user_plugin_relay_enable_preserves_agent_master_and_builtin_flags(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        result = mod.ensure_user_plugin_relay(
            agent_url=base,
            lanlan_name="XiaoYu",
            request_timeout=1,
        )
        self.assertTrue(result["user_plugin_enabled"])
        self.assertFalse(result["analyzer_enabled"])
        self.assertFalse(result["computer_use_enabled"])
        self.assertFalse(result["browser_use_enabled"])
        self.assertEqual(
            _FakeHandler.state["agent_flag_posts"],
            [{"lanlan_name": "XiaoYu", "user_plugin_enabled": True}],
        )

    def test_fallback_start_order_respects_declared_dependencies(self):
        plugins = [
            {
                "id": "xiaoyu_interaction_policy",
                "runtime_enabled": True,
                "runtime_auto_start": True,
                "status": "stopped",
                "dependencies": [{"id": "proactive_controller"}],
            },
            {
                "id": "proactive_controller",
                "runtime_enabled": True,
                "runtime_auto_start": True,
                "status": "stopped",
                "dependencies": [],
            },
        ]
        needs, _running = mod.select_autostart_candidates(plugins)
        self.assertEqual(
            mod.order_autostart_candidates(plugins, needs),
            ["proactive_controller", "xiaoyu_interaction_policy"],
        )

    def test_reconcile_refreshes_then_starts_only_stopped_autostart(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        result = mod.reconcile(
            main_url=base,
            plugin_url=base,
            agent_url=base,
            lanlan_name="XiaoYu",
            deadline=time.monotonic() + 3,
            request_timeout=1,
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertTrue(result["registry_refreshed"])
        self.assertEqual(result["discovered_count"], 3)
        self.assertEqual(
            result["autostart_candidates"],
            ["qq_auto_reply", "web_search"],
        )
        self.assertEqual(result["started"], ["qq_auto_reply"])
        self.assertEqual(result["already_running"], ["web_search"])
        self.assertEqual(_FakeHandler.state["starts"], ["qq_auto_reply"])
        self.assertFalse(result["agent_master_required"])
        self.assertTrue(result["native_api_only"])
        self.assertEqual(
            result["user_plugin_relay"],
            {
                "user_plugin_enabled": True,
                "analyzer_enabled": False,
                "computer_use_enabled": False,
                "browser_use_enabled": False,
            },
        )
        self.assertEqual(
            _FakeHandler.state["agent_flag_posts"],
            [{"lanlan_name": "XiaoYu", "user_plugin_enabled": True}],
        )


if __name__ == "__main__":
    unittest.main()
