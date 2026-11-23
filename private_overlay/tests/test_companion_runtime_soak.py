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


    def test_process_growth_and_pid_churn_are_observable_without_plugin_pid_guessing(self):
        mib = 1024 * 1024
        samples = [
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {
                    "available": True,
                    "desktop": [{"pid": 10, "rss_bytes": 100 * mib, "cpu_seconds": 1.0}],
                    "backend": [{"pid": 20, "rss_bytes": 200 * mib, "cpu_seconds": 2.0}],
                },
            },
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {
                    "available": True,
                    "desktop": [{"pid": 10, "rss_bytes": 120 * mib, "cpu_seconds": 1.2}],
                    "backend": [{"pid": 20, "rss_bytes": 205 * mib, "cpu_seconds": 2.2}],
                },
            },
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {
                    "available": True,
                    "desktop": [{"pid": 11, "rss_bytes": 130 * mib, "cpu_seconds": 0.1}],
                    "backend": [{"pid": 20, "rss_bytes": 210 * mib, "cpu_seconds": 2.4}],
                },
            },
        ]

        summary = mod.summarize(samples, elapsed_seconds=2.0)

        desktop = summary["process_summary"]["desktop"]
        self.assertEqual(desktop["pid_distinct_count"], 2)
        self.assertEqual(desktop["pid_churn_events"], 1)
        self.assertEqual(desktop["rss_mib_first"], 100.0)
        self.assertEqual(desktop["rss_mib_last"], 130.0)
        self.assertEqual(desktop["rss_mib_growth"], 30.0)
        self.assertIsNone(desktop["cpu_percent_approx"])

        backend = summary["process_summary"]["backend"]
        self.assertEqual(backend["pid_distinct_count"], 1)
        self.assertEqual(backend["pid_churn_events"], 0)
        self.assertEqual(backend["rss_mib_growth"], 10.0)
        self.assertAlmostEqual(backend["cpu_percent_approx"], 20.0)

    def test_explicit_performance_budgets_fail_closed_on_user_visible_regressions(self):
        mib = 1024 * 1024
        samples = [
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {
                    "available": True,
                    "desktop": [{"pid": 10, "rss_bytes": 100 * mib, "cpu_seconds": 1.0}],
                    "backend": [{"pid": 20, "rss_bytes": 200 * mib, "cpu_seconds": 2.0}],
                },
            },
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {
                    "available": True,
                    "desktop": [{"pid": 10, "rss_bytes": 140 * mib, "cpu_seconds": 2.0}],
                    "backend": [{"pid": 20, "rss_bytes": 202 * mib, "cpu_seconds": 2.1}],
                },
            },
        ]

        summary = mod.summarize(
            samples,
            elapsed_seconds=10.0,
            performance_budgets={
                "desktop": {
                    "max_rss_growth_mib": 20.0,
                    "max_pid_churn_events": 0,
                    "max_cpu_percent": 5.0,
                }
            },
        )

        self.assertEqual(summary["verdict"], "FAIL")
        self.assertIn("desktop_rss_growth_mib", summary["failures"])
        self.assertIn("desktop_cpu_percent", summary["failures"])
        self.assertNotIn("desktop_pid_churn", summary["failures"])
        self.assertEqual(
            summary["performance_budgets"]["desktop"]["max_rss_growth_mib"],
            20.0,
        )

    def test_requested_performance_budget_requires_process_metrics(self):
        samples = [
            {
                "endpoints": {},
                "plugins": {"not_running": [], "parse_error": ""},
                "processes": {"available": False, "reason": "psutil_unavailable"},
            }
        ]

        summary = mod.summarize(
            samples,
            elapsed_seconds=1.0,
            performance_budgets={"backend": {"max_pid_churn_events": 0}},
        )

        self.assertEqual(summary["verdict"], "FAIL")
        self.assertIn("backend_process_metrics_unavailable", summary["failures"])


if __name__ == "__main__":
    unittest.main()
