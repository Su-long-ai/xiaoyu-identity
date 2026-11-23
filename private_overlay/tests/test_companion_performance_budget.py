import ast
import importlib.util
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "check_companion_performance.py"
SPEC = importlib.util.spec_from_file_location("check_companion_performance", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class CompanionPerformanceBudgetTests(unittest.TestCase):
    def test_extracts_native_and_live_user_visible_metrics(self):
        native = {
            "ports_ready_elapsed_s": 2.5,
            "services_ready_elapsed_s": {"main": 2.6, "memory": 3.1, "agent": 4.0},
            "synthetic_chat": {"elapsed_s": 1.25},
            "checkpoints": [
                {"label": "cold_start_ready", "total": {"median_rss_mib": 300.0, "peak_rss_mib": 350.0, "median_count": 4}},
                {"label": "electron_attached", "total": {"median_rss_mib": 500.0, "peak_rss_mib": 550.0}, "last_processes": [{}, {}, {}, {}, {}]},
                {"label": "first_chat_complete_live", "total": {"median_rss_mib": 620.0, "peak_rss_mib": 690.0, "median_count": 6}},
            ],
        }
        soak = {
            "verdict": "PASS",
            "endpoint_summary": {
                "main": {
                    "latency_ms_mean": 12.5,
                    "latency_ms_p95": 18.0,
                    "latency_ms_max": 23.0,
                },
                "memory": {
                    "latency_ms_mean": 8.0,
                    "latency_ms_p95": 9.5,
                    "latency_ms_max": 11.0,
                },
                "agent": {
                    "latency_ms_mean": 16.0,
                    "latency_ms_p95": 22.5,
                    "latency_ms_max": 31.0,
                },
                "plugin": {
                    "latency_ms_mean": 20.0,
                    "latency_ms_p95": 27.5,
                    "latency_ms_max": 35.0,
                },
            },
            "process_summary": {
                "desktop": {"rss_mib_growth": 12.5, "rss_mib_max": 420.0, "pid_churn_events": 0, "cpu_percent_approx": 1.5, "count_max": 1},
                "backend": {"rss_mib_growth": 8.0, "rss_mib_max": 700.0, "pid_churn_events": 1, "cpu_percent_approx": 2.25, "count_max": 1},
            },
        }

        plugin_reconcile = {
            "verdict": "PASS",
            "elapsed_ms": 140.0,
            "native_autostart": {
                "initial_not_running": ["xiaoyu_private"],
                "recovered": ["xiaoyu_private"],
                "recovery_elapsed_ms": 95.0,
            },
        }
        metrics, errors = mod.extract_metrics(native, soak, plugin_reconcile)

        self.assertEqual(errors, [])
        self.assertEqual(metrics["startup.backend_ready_ms"], 2500.0)
        self.assertEqual(metrics["startup.main_ready_ms"], 2600.0)
        self.assertEqual(metrics["startup.memory_ready_ms"], 3100.0)
        self.assertEqual(metrics["startup.agent_ready_ms"], 4000.0)
        self.assertEqual(metrics["chat.first_turn_complete_ms"], 1250.0)
        self.assertEqual(metrics["memory.cold_start.process_count"], 4.0)
        self.assertEqual(metrics["memory.avatar_host_attached.process_count"], 5.0)
        self.assertEqual(metrics["memory.first_chat_complete.peak_rss_mib"], 690.0)
        self.assertEqual(metrics["soak.desktop.rss_growth_mib"], 12.5)
        self.assertEqual(metrics["soak.backend.pid_churn_events"], 1.0)
        self.assertEqual(metrics["soak.backend.cpu_percent"], 2.25)
        self.assertEqual(metrics["soak.endpoint.main.latency_p95_ms"], 18.0)
        self.assertEqual(metrics["soak.endpoint.memory.latency_max_ms"], 11.0)
        self.assertEqual(metrics["soak.endpoint.agent.latency_mean_ms"], 16.0)
        self.assertEqual(metrics["soak.endpoint.plugin.latency_p95_ms"], 27.5)
        self.assertEqual(metrics["plugin.reconcile_ms"], 140.0)
        self.assertEqual(metrics["plugin.recovery_ms"], 95.0)

    def test_source_failures_and_missing_requested_metrics_fail_closed(self):
        native = {"ports_ready_elapsed_s": 3.0, "validation_errors": ["residual port 48911"]}
        soak = {"verdict": "FAIL", "failures": ["endpoint:agent:1"], "process_summary": {}}
        plugin_reconcile = {
            "verdict": "PARTIAL",
            "elapsed_ms": 200.0,
            "native_autostart": {"recovery_elapsed_ms": None},
        }
        metrics, errors = mod.extract_metrics(native, soak, plugin_reconcile)
        result = mod.evaluate(metrics, {"voice.first_audio_ms": {"max": 1000}}, source_errors=errors)

        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn({"kind": "source_error", "detail": "native_benchmark:residual port 48911"}, result["failures"])
        self.assertIn({"kind": "source_error", "detail": "live_soak:endpoint:agent:1"}, result["failures"])
        self.assertIn({"kind": "source_error", "detail": "plugin_reconcile:partial"}, result["failures"])
        self.assertIn({"kind": "missing_metric", "metric": "voice.first_audio_ms"}, result["failures"])

    def test_explicit_budget_boundaries_pass_and_regressions_fail(self):
        metrics = {
            "startup.backend_ready_ms": 3000.0,
            "chat.first_turn_complete_ms": 5000.0,
            "soak.desktop.rss_growth_mib": 20.0,
        }
        passing = mod.evaluate(metrics, {
            "startup.backend_ready_ms": {"max": 3000},
            "chat.first_turn_complete_ms": {"max": 5000},
            "soak.desktop.rss_growth_mib": {"min": 0, "max": 20},
        })
        failing = mod.evaluate(metrics, {
            "startup.backend_ready_ms": {"max": 2999},
            "soak.desktop.rss_growth_mib": {"max": 19.5},
        })

        self.assertEqual(passing["verdict"], "PASS")
        self.assertEqual(failing["verdict"], "FAIL")
        self.assertEqual(
            {item["metric"] for item in failing["failures"]},
            {"startup.backend_ready_ms", "soak.desktop.rss_growth_mib"},
        )

    def test_live_endpoint_latency_uses_explicit_budgets_and_missing_is_fail_closed(self):
        metrics, errors = mod.extract_metrics(
            None,
            {
                "verdict": "PASS",
                "endpoint_summary": {
                    "main": {
                        "latency_ms_mean": 10.0,
                        "latency_ms_p95": 25.0,
                        "latency_ms_max": 30.0,
                    }
                },
                "process_summary": {},
            },
        )
        self.assertEqual(errors, [])

        passing = mod.evaluate(
            metrics,
            {"soak.endpoint.main.latency_p95_ms": {"max": 25.0}},
        )
        failing = mod.evaluate(
            metrics,
            {
                "soak.endpoint.main.latency_p95_ms": {"max": 24.9},
                "soak.endpoint.agent.latency_p95_ms": {"max": 50.0},
            },
        )

        self.assertEqual(passing["verdict"], "PASS")
        self.assertEqual(failing["verdict"], "FAIL")
        self.assertIn(
            {
                "kind": "over_budget",
                "metric": "soak.endpoint.main.latency_p95_ms",
                "value": 25.0,
                "max": 24.9,
            },
            failing["failures"],
        )
        self.assertIn(
            {"kind": "missing_metric", "metric": "soak.endpoint.agent.latency_p95_ms"},
            failing["failures"],
        )

    def test_invalid_and_nonfinite_values_cannot_bypass_the_gate(self):
        for budgets in (
            {"x": 1},
            {"x": {}},
            {"x": {"max": True}},
            {"x": {"max": math.nan}},
            {"x": {"min": math.inf}},
        ):
            with self.subTest(budgets=repr(budgets)):
                with self.assertRaises(ValueError):
                    mod.evaluate({"x": 1.0}, budgets)

        direct = mod.evaluate({"x": math.nan}, {"x": {"max": 1.0}})
        self.assertEqual(direct["verdict"], "FAIL")
        self.assertEqual(direct["failures"][0]["kind"], "invalid_metric")

        extracted, errors = mod.extract_metrics({"ports_ready_elapsed_s": math.inf}, None)
        self.assertEqual(errors, [])
        self.assertNotIn("startup.backend_ready_ms", extracted)
        missing = mod.evaluate(extracted, {"startup.backend_ready_ms": {"max": 1000}})
        self.assertEqual(missing["failures"][0]["kind"], "missing_metric")

    def test_recovery_budget_fails_closed_when_no_recovery_measurement_exists(self):
        metrics, errors = mod.extract_metrics(
            None,
            None,
            {
                "verdict": "PASS",
                "elapsed_ms": 25.0,
                "native_autostart": {
                    "initial_not_running": [],
                    "recovered": [],
                    "recovery_elapsed_ms": None,
                },
            },
        )
        self.assertEqual(errors, [])
        self.assertEqual(metrics["plugin.reconcile_ms"], 25.0)
        result = mod.evaluate(metrics, {"plugin.recovery_ms": {"max": 1000}})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["failures"][0]["kind"], "missing_metric")

    def test_adapter_remains_offline_and_non_authoritative(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8-sig"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])

        self.assertNotIn("psutil", imported)
        self.assertNotIn("subprocess", imported)
        source = MODULE_PATH.read_text(encoding="utf-8-sig")
        self.assertNotIn("process_iter(", source)
        self.assertNotIn("Popen(", source)


if __name__ == "__main__":
    unittest.main()
