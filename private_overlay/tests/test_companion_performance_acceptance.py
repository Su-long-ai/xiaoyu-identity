from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "check_companion_performance.py"
SPEC = importlib.util.spec_from_file_location("check_companion_performance", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class CompanionPerformanceAcceptanceTests(unittest.TestCase):
    def test_adapter_never_becomes_a_sampler_or_process_owner(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import psutil",
            "from psutil",
            "import subprocess",
            "from subprocess",
            "Popen(",
            "Get-Process",
        ):
            self.assertNotIn(forbidden, source)

    def test_extracts_native_startup_chat_and_memory_without_resampling(self):
        native = {
            "validation_errors": [],
            "ports_ready_elapsed_s": 2.5,
            "services_ready_elapsed_s": {
                "main": 1.0,
                "memory": 1.5,
                "agent": 2.0,
            },
            "synthetic_chat": {"elapsed_s": 0.8},
            "checkpoints": [
                {
                    "label": "cold_start_ready",
                    "total": {"median_rss_mib": 500.0, "peak_rss_mib": 550.0},
                    "last_processes": [{"pid": 1}, {"pid": 2}],
                },
                {
                    "label": "electron_attached",
                    "total": {"median_rss_mib": 700.0, "peak_rss_mib": 760.0},
                    "last_processes": [{"pid": 1}, {"pid": 2}, {"pid": 3}],
                },
            ],
        }

        metrics, errors = mod.extract_metrics(native, None)

        self.assertEqual(errors, [])
        self.assertEqual(metrics["startup.backend_ready_ms"], 2500.0)
        self.assertEqual(metrics["startup.main_ready_ms"], 1000.0)
        self.assertEqual(metrics["startup.memory_ready_ms"], 1500.0)
        self.assertEqual(metrics["startup.agent_ready_ms"], 2000.0)
        self.assertEqual(metrics["chat.first_turn_complete_ms"], 800.0)
        self.assertEqual(metrics["memory.cold_start.median_rss_mib"], 500.0)
        self.assertEqual(metrics["memory.cold_start.process_count"], 2.0)
        self.assertEqual(
            metrics["memory.avatar_host_attached.peak_rss_mib"],
            760.0,
        )

    def test_extracts_live_soak_growth_cpu_and_churn(self):
        soak = {
            "verdict": "PASS",
            "failures": [],
            "process_summary": {
                "desktop": {
                    "rss_mib_growth": 20.0,
                    "rss_mib_max": 320.0,
                    "pid_churn_events": 0,
                    "cpu_percent_approx": 1.5,
                    "count_max": 1,
                },
                "backend": {
                    "rss_mib_growth": 40.0,
                    "rss_mib_max": 900.0,
                    "pid_churn_events": 1,
                    "cpu_percent_approx": 5.5,
                    "count_max": 2,
                },
            },
        }

        metrics, errors = mod.extract_metrics(None, soak)

        self.assertEqual(errors, [])
        self.assertEqual(metrics["soak.desktop.rss_growth_mib"], 20.0)
        self.assertEqual(metrics["soak.desktop.cpu_percent"], 1.5)
        self.assertEqual(metrics["soak.backend.pid_churn_events"], 1.0)
        self.assertEqual(metrics["soak.backend.process_count_max"], 2.0)

    def test_explicit_budgets_pass_and_fail_closed_on_missing_metric(self):
        metrics = {
            "startup.backend_ready_ms": 2500.0,
            "soak.backend.rss_growth_mib": 10.0,
        }

        passed = mod.evaluate(
            metrics,
            {
                "startup.backend_ready_ms": {"max": 3000},
                "soak.backend.rss_growth_mib": {"max": 20},
            },
        )
        self.assertEqual(passed["verdict"], "PASS")

        failed = mod.evaluate(
            metrics,
            {
                "startup.backend_ready_ms": {"max": 2000},
                "voice.first_ready_ms": {"max": 3000},
            },
        )
        self.assertEqual(failed["verdict"], "FAIL")
        kinds = {(item["kind"], item.get("metric")) for item in failed["failures"]}
        self.assertIn(("over_budget", "startup.backend_ready_ms"), kinds)
        self.assertIn(("missing_metric", "voice.first_ready_ms"), kinds)

    def test_source_validation_errors_are_product_failures(self):
        metrics, errors = mod.extract_metrics(
            {"validation_errors": ["residual port 48911"]},
            {
                "verdict": "FAIL",
                "failures": ["backend_pid_churn"],
                "process_summary": {},
            },
        )
        result = mod.evaluate(metrics, {}, source_errors=errors)

        self.assertEqual(result["verdict"], "FAIL")
        details = [item["detail"] for item in result["failures"]]
        self.assertIn("native_benchmark:residual port 48911", details)
        self.assertIn("live_soak:backend_pid_churn", details)

    def test_budget_schema_rejects_implicit_or_non_numeric_thresholds(self):
        with self.assertRaises(ValueError):
            mod.evaluate({"metric": 1.0}, {"metric": {}})
        with self.assertRaises(ValueError):
            mod.evaluate({"metric": 1.0}, {"metric": {"max": "fast"}})


if __name__ == "__main__":
    unittest.main()
