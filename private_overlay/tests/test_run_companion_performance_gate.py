import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from private_overlay.tools import run_companion_performance_gate as mod


class CompanionPerformanceGateTests(unittest.TestCase):
    def _write_runtime_record(self, root: Path, *, instance_id: str = "generation-a") -> Path:
        path = root / "launcher.json"
        path.write_text(
            json.dumps(
                {
                    "app": "N.E.K.O",
                    "state": "ready",
                    "instance_id": instance_id,
                    "launch_mode": "merged",
                    "ports": {
                        "MAIN_SERVER_PORT": 43111,
                        "MEMORY_SERVER_PORT": 43112,
                        "TOOL_SERVER_PORT": 43115,
                    },
                    "internal_ports": {"USER_PLUGIN_SERVER_PORT": 43116},
                }
            ),
            encoding="utf-8",
        )
        return path

    def _write_reconcile(self, root: Path, *, instance_id: str = "generation-a") -> Path:
        path = root / "reconcile.json"
        path.write_text(
            json.dumps(
                {
                    "verdict": "PASS",
                    "elapsed_ms": 1200.0,
                    "runtime_record": {"instance_id": instance_id},
                    "native_autostart": {
                        "initial_not_running": ["xiaoyu_interaction_policy"],
                        "recovered": ["xiaoyu_interaction_policy"],
                        "recovery_elapsed_ms": 800.0,
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _healthy_soak(*, urls, **_kwargs):
        assert urls == {
            "main": "http://127.0.0.1:43111/",
            "memory": "http://127.0.0.1:43112/health",
            "agent": "http://127.0.0.1:43115/health",
            "plugin": "http://127.0.0.1:43116/plugins?summary=true",
        }
        endpoint = {
            "latency_ms_mean": 10.0,
            "latency_ms_p95": 20.0,
            "latency_ms_max": 30.0,
        }
        return {
            "verdict": "PASS",
            "failures": [],
            "endpoint_summary": {
                "main": dict(endpoint),
                "memory": dict(endpoint),
                "agent": dict(endpoint),
                "plugin": dict(endpoint),
            },
            "process_summary": {
                "desktop": {
                    "rss_mib_growth": 0.0,
                    "rss_mib_max": 100.0,
                    "pid_churn_events": 0,
                    "cpu_percent_approx": 1.0,
                    "count_max": 1,
                },
                "backend": {
                    "rss_mib_growth": 0.0,
                    "rss_mib_max": 200.0,
                    "pid_churn_events": 0,
                    "cpu_percent_approx": 1.0,
                    "count_max": 1,
                },
            },
        }

    def test_live_gate_uses_negotiated_launcher_ports_and_current_reconcile(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runtime = self._write_runtime_record(root)
            reconcile = self._write_reconcile(root)
            with patch.object(mod, "run_soak", side_effect=self._healthy_soak):
                result = mod.run_gate(
                    profile="live",
                    budgets_path=mod.DEFAULT_BUDGETS,
                    runtime_record_path=runtime,
                    reconcile_result_path=reconcile,
                )

        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(
            result["sources"]["runtime_record"]["ports"]["MAIN_SERVER_PORT"],
            43111,
        )
        self.assertEqual(
            result["performance"]["metrics"]["plugin.reconcile_ms"],
            1200.0,
        )

    def test_live_gate_requires_exactly_one_desktop_and_backend_process(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runtime = self._write_runtime_record(root)
            reconcile = self._write_reconcile(root)
            bad_soak = self._healthy_soak(
                urls={
                    "main": "http://127.0.0.1:43111/",
                    "memory": "http://127.0.0.1:43112/health",
                    "agent": "http://127.0.0.1:43115/health",
                    "plugin": "http://127.0.0.1:43116/plugins?summary=true",
                }
            )
            bad_soak["process_summary"]["desktop"]["count_max"] = 0
            with patch.object(mod, "run_soak", return_value=bad_soak):
                result = mod.run_gate(
                    profile="live",
                    budgets_path=mod.DEFAULT_BUDGETS,
                    runtime_record_path=runtime,
                    reconcile_result_path=reconcile,
                )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn(
            {
                "kind": "under_budget",
                "metric": "soak.desktop.process_count_max",
                "value": 0.0,
                "min": 1.0,
            },
            result["performance"]["failures"],
        )

    def test_live_gate_rejects_stale_reconcile_generation(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runtime = self._write_runtime_record(root, instance_id="generation-new")
            reconcile = self._write_reconcile(root, instance_id="generation-old")
            with patch.object(mod, "run_soak", side_effect=self._healthy_soak):
                result = mod.run_gate(
                    profile="live",
                    budgets_path=mod.DEFAULT_BUDGETS,
                    runtime_record_path=runtime,
                    reconcile_result_path=reconcile,
                )

        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(
            any(
                item.get("kind") == "source_error"
                and "plugin_reconcile:stale_instance:" in item.get("detail", "")
                for item in result["performance"]["failures"]
            )
        )

    def test_live_gate_fails_closed_when_launcher_record_is_not_ready(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "launcher.json"
            runtime.write_text(
                json.dumps(
                    {
                        "app": "N.E.K.O",
                        "state": "starting",
                        "instance_id": "generation-a",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(mod, "run_soak") as soak:
                result = mod.run_gate(
                    profile="live",
                    budgets_path=mod.DEFAULT_BUDGETS,
                    runtime_record_path=runtime,
                    reconcile_result_path=root / "missing.json",
                )

        soak.assert_not_called()
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(
            any(
                item.get("detail") == "runtime_record:not_ready:starting"
                for item in result["performance"]["failures"]
            )
        )

    def test_cold_start_profile_consumes_native_benchmark_only(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            native = root / "native.json"
            native.write_text(
                json.dumps(
                    {
                        "ports_ready_elapsed_s": 25.0,
                        "services_ready_elapsed_s": {
                            "main": 25.0,
                            "memory": 24.0,
                            "agent": 26.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = mod.run_gate(
                profile="cold_start",
                budgets_path=mod.DEFAULT_BUDGETS,
                native_benchmark_path=native,
            )

        self.assertEqual(result["verdict"], "PASS")
        self.assertIsNone(result["sources"]["live_soak"])
        self.assertTrue(result["sources"]["native_benchmark_present"])

    def test_cold_start_profile_requires_native_benchmark(self):
        result = mod.run_gate(
            profile="cold_start",
            budgets_path=mod.DEFAULT_BUDGETS,
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(
            any(
                item.get("detail") == "native_benchmark:required_for_cold_start"
                for item in result["performance"]["failures"]
            )
        )

    def test_orchestrator_does_not_add_runtime_or_transport_authority(self):
        module_path = Path(mod.__file__)
        tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        for forbidden in ("subprocess", "psutil", "urllib", "httpx", "requests"):
            self.assertNotIn(forbidden, imported)


if __name__ == "__main__":
    unittest.main()
