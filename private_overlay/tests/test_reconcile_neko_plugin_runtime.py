import importlib.util
import json
import threading
import time
import unittest
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "reconcile_neko_plugin_runtime.py"
SPEC = importlib.util.spec_from_file_location("reconcile_neko_plugin_runtime", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class _FakeHandler(BaseHTTPRequestHandler):
    state = {}

    @classmethod
    def reset(cls):
        cls.state = {
            "agent_flags": {"computer_use_enabled": False, "browser_use_enabled": False, "user_plugin_enabled": False},
            "analyzer_enabled": False,
            "agent_flag_posts": [],
            "refreshes": 0,
            "starts": [],
            "start_delay": 0.0,
            "plugins": [
                {"id": "alpha", "status": "stopped", "runtime_enabled": True, "runtime_auto_start": True, "autostart_pending": False},
                {"id": "beta", "status": "stopped", "runtime_enabled": True, "runtime_auto_start": True, "autostart_pending": False},
                {"id": "manual", "status": "stopped", "runtime_enabled": True, "runtime_auto_start": False, "autostart_pending": False},
                {"id": "pending", "status": "stopped", "runtime_enabled": True, "runtime_auto_start": True, "autostart_pending": True},
            ],
        }

    def log_message(self, *_args): return

    def _send(self, payload, status=200):
        raw=json.dumps(payload).encode("utf-8"); self.send_response(status)
        self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path=="/agent/flags":
            self._send({"success":True,"agent_flags":dict(self.state["agent_flags"]),"analyzer_enabled":self.state["analyzer_enabled"]}); return
        if path=="/plugins":
            self._send({"plugins":[dict(x) for x in self.state["plugins"]],"message":""}); return
        self._send({"detail":"not found"},404)

    def do_POST(self):
        path=urlsplit(self.path).path
        length=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if path=="/agent/flags":
            self.state["agent_flag_posts"].append(dict(body))
            if "user_plugin_enabled" in body: self.state["agent_flags"]["user_plugin_enabled"]=bool(body["user_plugin_enabled"])
            self._send({"success":True,"agent_flags":dict(self.state["agent_flags"]),"analyzer_enabled":self.state["analyzer_enabled"]}); return
        if path=="/plugins/refresh":
            self.state["refreshes"] += 1; self._send({"success":True}); return
        if path.startswith("/plugin/") and path.endswith("/start"):
            delay = float(self.state.get("start_delay") or 0.0)
            if delay > 0:
                time.sleep(delay)
            plugin_id=path.split("/")[2]; self.state["starts"].append(plugin_id)
            for item in self.state["plugins"]:
                if item["id"]==plugin_id: item["status"]="running"
            self._send({"success":True,"plugin_id":plugin_id,"message":"Plugin started successfully"}); return
        self._send({"detail":"not found"},404)


class ReconcileNativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        _FakeHandler.reset(); self.server=ThreadingHTTPServer(("127.0.0.1",0),_FakeHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
    @property
    def base(self): return f"http://127.0.0.1:{self.server.server_port}"

    def test_host_declared_autostart_only_and_pending_approval_is_preserved(self):
        result=mod.reconcile_native_autostart(plugin_url=self.base,request_timeout=1)
        self.assertEqual(result["host_selected_candidates"],["alpha","beta"])
        self.assertEqual(result["not_running"],[])
        self.assertEqual(_FakeHandler.state["refreshes"],1)
        self.assertEqual(_FakeHandler.state["starts"],["alpha","beta"])

    def test_running_autostart_is_not_restarted_and_crashed_plugin_is_recovered(self):
        _FakeHandler.state["plugins"][0]["status"] = "running"
        _FakeHandler.state["plugins"][1]["status"] = "crashed"

        result = mod.reconcile_native_autostart(plugin_url=self.base, request_timeout=1)

        self.assertEqual(result["host_selected_candidates"], ["alpha", "beta"])
        self.assertEqual(result["running"], ["alpha", "beta"])
        self.assertEqual(result["not_running"], [])
        self.assertEqual(result["attempts"]["alpha"], ["already_running"])
        self.assertEqual(result["attempts"]["beta"], ["started"])
        self.assertEqual(result["initial_not_running"], ["beta"])
        self.assertEqual(result["recovered"], ["beta"])
        self.assertIsNotNone(result["recovery_elapsed_ms"])
        self.assertGreaterEqual(result["recovery_elapsed_ms"], 0.0)
        self.assertGreaterEqual(result["elapsed_ms"], result["recovery_elapsed_ms"])
        self.assertEqual(_FakeHandler.state["starts"], ["beta"])

    def test_healthy_autostart_does_not_claim_a_recovery_latency(self):
        _FakeHandler.state["plugins"][0]["status"] = "running"
        _FakeHandler.state["plugins"][1]["status"] = "running"

        result = mod.reconcile_native_autostart(
            plugin_url=self.base,
            request_timeout=1,
        )

        self.assertEqual(result["initial_not_running"], [])
        self.assertEqual(result["recovered"], [])
        self.assertIsNone(result["recovery_elapsed_ms"])
        self.assertGreaterEqual(result["elapsed_ms"], 0.0)
        self.assertEqual(_FakeHandler.state["starts"], [])

    def test_autostart_start_requests_respect_absolute_deadline(self):
        _FakeHandler.state["start_delay"] = 0.40
        deadline = time.monotonic() + 0.12
        started = time.monotonic()

        result = mod.reconcile_native_autostart(
            plugin_url=self.base,
            request_timeout=1.0,
            deadline=deadline,
        )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.35, f"deadline leaked across plugin start calls: {elapsed:.3f}s")
        self.assertTrue(result["not_running"])
        self.assertTrue(
            result["deadline_exhausted"]
            or any("timed out" in " ".join(v).lower() for v in result["attempts"].values())
        )

    def test_bounded_timeout_never_exceeds_remaining_budget(self):
        now = 1000.0
        deadline = 1000.05
        remaining = deadline - now
        original_monotonic = mod.time.monotonic
        try:
            mod.time.monotonic = lambda: now
            timeout = mod._bounded_timeout(deadline, 30.0)
        finally:
            mod.time.monotonic = original_monotonic
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, remaining)

    def test_bounded_timeout_does_not_inflate_sub_millisecond_budget(self):
        now = 1000.0
        deadline = 1000.0004
        remaining = deadline - now
        original_monotonic = mod.time.monotonic
        try:
            mod.time.monotonic = lambda: now
            timeout = mod._bounded_timeout(deadline, 30.0)
        finally:
            mod.time.monotonic = original_monotonic
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, remaining)
        self.assertLess(timeout, 0.001)

    def test_relay_preserves_master_and_builtin_flags(self):
        result=mod.ensure_user_plugin_relay(agent_url=self.base,lanlan_name="XiaoYu",request_timeout=1)
        self.assertTrue(result["user_plugin_enabled"]); self.assertFalse(result["analyzer_enabled"])
        self.assertFalse(result["computer_use_enabled"]); self.assertFalse(result["browser_use_enabled"])
        self.assertEqual(_FakeHandler.state["agent_flag_posts"],[{"lanlan_name":"XiaoYu","user_plugin_enabled":True}])

    def test_full_reconcile_delegates_lifecycle_to_host_api(self):
        result=mod.reconcile(plugin_url=self.base,agent_url=self.base,lanlan_name="XiaoYu",deadline=time.monotonic()+3,request_timeout=1)
        self.assertEqual(result["verdict"],"PASS")
        self.assertEqual(result["plugin_lifecycle_authority"],"neko_native_http_api")
        self.assertEqual(result["dependency_and_process_authority"],"neko_native")
        self.assertEqual(result["native_autostart"]["running"],["alpha","beta"])
        self.assertGreaterEqual(result["elapsed_ms"], 0.0)
        self.assertIsNotNone(result["native_autostart"]["recovery_elapsed_ms"])


    def test_runtime_record_routes_reconcile_to_negotiated_native_ports(self):
        with TemporaryDirectory() as td:
            record = Path(td) / "launcher.json"
            port = self.server.server_port
            record.write_text(
                json.dumps(
                    {
                        "app": "N.E.K.O",
                        "state": "ready",
                        "instance_id": "native-generation",
                        "launch_mode": "merged",
                        "ports": {
                            "MAIN_SERVER_PORT": port,
                            "MEMORY_SERVER_PORT": port,
                            "TOOL_SERVER_PORT": port,
                        },
                        "internal_ports": {"USER_PLUGIN_SERVER_PORT": port},
                    }
                ),
                encoding="utf-8",
            )

            result = mod.reconcile(
                plugin_url="http://127.0.0.1:1",
                agent_url="http://127.0.0.1:2",
                lanlan_name="XiaoYu",
                deadline=time.monotonic() + 3,
                request_timeout=1,
                runtime_record_path=record,
            )

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["endpoint_authority"], "neko_launcher_record")
        self.assertEqual(result["runtime_record"]["instance_id"], "native-generation")
        self.assertEqual(result["runtime_record"]["main_url"], self.base)
        self.assertEqual(result["runtime_record"]["memory_url"], self.base)
        self.assertEqual(result["agent_url"], self.base)
        self.assertEqual(result["plugin_url"], self.base)

    def test_starting_runtime_record_never_falls_back_to_guessed_default_ports(self):
        with TemporaryDirectory() as td:
            record = Path(td) / "launcher.json"
            record.write_text(
                json.dumps(
                    {
                        "app": "N.E.K.O",
                        "state": "starting",
                        "instance_id": "new-generation",
                        "ports": {"TOOL_SERVER_PORT": self.server.server_port},
                        "internal_ports": {
                            "USER_PLUGIN_SERVER_PORT": self.server.server_port
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = mod.reconcile(
                plugin_url=self.base,
                agent_url=self.base,
                lanlan_name="XiaoYu",
                deadline=time.monotonic() + 0.12,
                request_timeout=0.05,
                runtime_record_path=record,
                record_fallback_grace=0.0,
            )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["endpoint_authority"], "neko_launcher_record_wait")
        self.assertEqual(_FakeHandler.state["refreshes"], 0)
        self.assertEqual(_FakeHandler.state["agent_flag_posts"], [])

    def test_missing_runtime_record_preserves_bounded_explicit_url_compatibility(self):
        with TemporaryDirectory() as td:
            result = mod.reconcile(
                plugin_url=self.base,
                agent_url=self.base,
                lanlan_name="XiaoYu",
                deadline=time.monotonic() + 3,
                request_timeout=1,
                runtime_record_path=Path(td) / "missing-launcher.json",
                record_fallback_grace=0.0,
            )

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["endpoint_authority"], "explicit_urls_fallback")


if __name__ == "__main__": unittest.main()
