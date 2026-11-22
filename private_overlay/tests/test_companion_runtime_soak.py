import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "companion_runtime_soak.py"
SPEC = importlib.util.spec_from_file_location("companion_runtime_soak", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class _Handler(BaseHTTPRequestHandler):
    state = {}

    @classmethod
    def reset(cls):
        cls.state = {
            "plugins": [
                {
                    "id": "alpha",
                    "status": "running",
                    "runtime_enabled": True,
                    "runtime_auto_start": True,
                    "autostart_pending": False,
                },
                {
                    "id": "manual",
                    "status": "stopped",
                    "runtime_enabled": True,
                    "runtime_auto_start": False,
                    "autostart_pending": False,
                },
                {
                    "id": "pending",
                    "status": "stopped",
                    "runtime_enabled": True,
                    "runtime_auto_start": True,
                    "autostart_pending": True,
                },
            ]
        }

    def log_message(self, *_args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/plugins":
            raw = json.dumps({"plugins": self.state["plugins"]}).encode()
        else:
            raw = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class CompanionRuntimeSoakTests(unittest.TestCase):
    def setUp(self):
        _Handler.reset()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def urls(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        return {
            "main": base + "/",
            "memory": base + "/memory",
            "agent": base + "/agent",
            "plugin": base + "/plugins?summary=true",
        }

    def test_single_sample_passes_when_host_declared_autostarts_are_running(self):
        sample = mod.sample_once(urls=self.urls, timeout=1)
        self.assertTrue(all(item["ok"] for item in sample["endpoints"].values()))
        self.assertEqual(sample["plugins"]["not_running"], [])
        self.assertEqual(
            [item["id"] for item in sample["plugins"]["candidates"]],
            ["alpha"],
        )

        summary = mod.summarize([sample], elapsed_seconds=0.1)
        self.assertEqual(summary["verdict"], "PASS")
        self.assertEqual(summary["plugin_summary"]["nonrunning_observations"], {})

    def test_stopped_autostart_fails_but_manual_and_pending_plugins_do_not(self):
        _Handler.state["plugins"][0]["status"] = "crashed"
        sample = mod.sample_once(urls=self.urls, timeout=1)
        self.assertEqual(sample["plugins"]["not_running"], ["alpha"])

        summary = mod.summarize([sample], elapsed_seconds=0.1)
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertEqual(
            summary["plugin_summary"]["nonrunning_observations"],
            {"alpha": 1},
        )
        self.assertNotIn("manual", str(summary))
        self.assertNotIn("pending", str(summary))

    def test_endpoint_failure_is_counted_without_recording_content(self):
        bad = dict(self.urls)
        bad["agent"] = "http://127.0.0.1:1/health"
        sample = mod.sample_once(urls=bad, timeout=0.05)
        summary = mod.summarize([sample], elapsed_seconds=0.1)

        self.assertEqual(summary["verdict"], "FAIL")
        self.assertEqual(summary["endpoint_summary"]["agent"]["failures"], 1)
        self.assertFalse(summary["privacy"]["conversation_text_recorded"])
        self.assertFalse(summary["privacy"]["credentials_recorded"])
        self.assertFalse(summary["privacy"]["window_titles_recorded"])

    def test_process_count_requirements_only_apply_when_metrics_are_available(self):
        samples = [
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {
                    "available": True,
                    "desktop": [{"pid": 1, "rss_bytes": 10, "cpu_seconds": 1.0}],
                    "backend": [
                        {"pid": 2, "rss_bytes": 20, "cpu_seconds": 1.0},
                        {"pid": 3, "rss_bytes": 20, "cpu_seconds": 1.0},
                    ],
                },
            }
        ]
        summary = mod.summarize(
            samples,
            elapsed_seconds=1.0,
            require_desktop=True,
            require_single_backend=True,
        )
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertIn("backend_process_count", summary["failures"])
        self.assertNotIn("desktop_process_count", summary["failures"])


if __name__ == "__main__":
    unittest.main()
