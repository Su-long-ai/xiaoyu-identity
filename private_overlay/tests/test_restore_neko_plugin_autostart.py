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
        if path == "/plugins":
            plugins = self.state["plugins"] if self.state["refreshed"] else []
            self._send({"plugins": plugins})
            return
        self._send({"detail": "not found"}, 404)

    def do_POST(self):
        path = urlsplit(self.path).path
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

    def test_reconcile_refreshes_then_starts_only_stopped_autostart(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        result = mod.reconcile(
            main_url=base,
            plugin_url=base,
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


if __name__ == "__main__":
    unittest.main()
