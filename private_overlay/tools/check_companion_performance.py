#!/usr/bin/env python3
"""Evaluate XiaoYu Companion performance using existing native measurements.

This module deliberately does not launch, sample or supervise any process.
N.E.K.O's runtime_memory_baseline.py remains the cold-start/process-tree
measurement authority; companion_runtime_soak.py remains the live soak
measurement authority. This adapter only normalizes their JSON outputs and
applies explicit product budgets.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _checkpoint(native: dict[str, Any], label: str) -> dict[str, Any] | None:
    for item in native.get("checkpoints") or []:
        if isinstance(item, dict) and item.get("label") == label:
            return item
    return None


def _put(metrics: dict[str, float], key: str, value: Any, scale: float = 1.0) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        normalized = float(value) * scale
        if math.isfinite(normalized):
            metrics[key] = round(normalized, 3)


def extract_metrics(
    native_benchmark: dict[str, Any] | None,
    live_soak: dict[str, Any] | None,
    plugin_reconcile: dict[str, Any] | None = None,
) -> tuple[dict[str, float], list[str]]:
    metrics: dict[str, float] = {}
    source_errors: list[str] = []

    if native_benchmark is not None:
        errors = native_benchmark.get("validation_errors") or []
        if errors:
            source_errors.extend(f"native_benchmark:{item}" for item in errors)

        _put(
            metrics,
            "startup.backend_ready_ms",
            native_benchmark.get("ports_ready_elapsed_s"),
            1000.0,
        )
        service_ready = native_benchmark.get("services_ready_elapsed_s") or {}
        for role in ("main", "memory", "agent"):
            _put(
                metrics,
                f"startup.{role}_ready_ms",
                service_ready.get(role),
                1000.0,
            )

        chat = native_benchmark.get("synthetic_chat")
        if isinstance(chat, dict):
            _put(metrics, "chat.first_turn_complete_ms", chat.get("elapsed_s"), 1000.0)

        for label, prefix in (
            ("cold_start_ready", "memory.cold_start"),
            ("electron_attached", "memory.avatar_host_attached"),
            ("first_chat_complete_live", "memory.first_chat_complete"),
        ):
            checkpoint = _checkpoint(native_benchmark, label)
            if checkpoint is None:
                continue
            total = checkpoint.get("total") or {}
            _put(metrics, f"{prefix}.median_rss_mib", total.get("median_rss_mib"))
            _put(metrics, f"{prefix}.peak_rss_mib", total.get("peak_rss_mib"))
            _put(metrics, f"{prefix}.process_count", total.get("median_count"))
            if "median_count" not in total:
                _put(metrics, f"{prefix}.process_count", len(checkpoint.get("last_processes") or []))

    if live_soak is not None:
        if str(live_soak.get("verdict") or "").upper() == "FAIL":
            source_errors.extend(
                f"live_soak:{item}" for item in (live_soak.get("failures") or ["failed"])
            )
        endpoint_summary = live_soak.get("endpoint_summary") or {}
        for endpoint in ("main", "memory", "agent", "plugin"):
            summary = endpoint_summary.get(endpoint) or {}
            _put(
                metrics,
                f"soak.endpoint.{endpoint}.latency_mean_ms",
                summary.get("latency_ms_mean"),
            )
            _put(
                metrics,
                f"soak.endpoint.{endpoint}.latency_p95_ms",
                summary.get("latency_ms_p95"),
            )
            _put(
                metrics,
                f"soak.endpoint.{endpoint}.latency_max_ms",
                summary.get("latency_ms_max"),
            )

        process_summary = live_soak.get("process_summary") or {}
        for role in ("desktop", "backend"):
            summary = process_summary.get(role) or {}
            _put(metrics, f"soak.{role}.rss_growth_mib", summary.get("rss_mib_growth"))
            _put(metrics, f"soak.{role}.rss_peak_mib", summary.get("rss_mib_max"))
            _put(metrics, f"soak.{role}.pid_churn_events", summary.get("pid_churn_events"))
            _put(metrics, f"soak.{role}.cpu_percent", summary.get("cpu_percent_approx"))
            _put(metrics, f"soak.{role}.process_count_max", summary.get("count_max"))

    if plugin_reconcile is not None:
        verdict = str(plugin_reconcile.get("verdict") or "").upper()
        if verdict != "PASS":
            source_errors.append(
                "plugin_reconcile:" + (verdict.lower() if verdict else "missing_verdict")
            )
        _put(metrics, "plugin.reconcile_ms", plugin_reconcile.get("elapsed_ms"))
        native_autostart = plugin_reconcile.get("native_autostart")
        if isinstance(native_autostart, dict):
            _put(
                metrics,
                "plugin.recovery_ms",
                native_autostart.get("recovery_elapsed_ms"),
            )

    return metrics, source_errors


def evaluate(
    metrics: dict[str, float],
    budgets: dict[str, Any],
    *,
    source_errors: list[str] | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for error in source_errors or []:
        failures.append({"kind": "source_error", "detail": error})

    normalized_budgets: dict[str, dict[str, float]] = {}
    for key, raw_rule in budgets.items():
        if not isinstance(raw_rule, dict):
            raise ValueError(f"budget for {key!r} must be an object")
        rule: dict[str, float] = {}
        for bound in ("max", "min"):
            if bound in raw_rule:
                value = raw_rule[bound]
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"budget {key!r}.{bound} must be numeric")
                normalized = float(value)
                if not math.isfinite(normalized):
                    raise ValueError(f"budget {key!r}.{bound} must be finite")
                rule[bound] = normalized
        if not rule:
            raise ValueError(f"budget for {key!r} must declare max and/or min")
        normalized_budgets[key] = rule

        if key not in metrics:
            failures.append({"kind": "missing_metric", "metric": key})
            continue
        value = metrics[key]
        if not math.isfinite(value):
            failures.append(
                {"kind": "invalid_metric", "metric": key, "value": repr(value)}
            )
            continue
        if "max" in rule and value > rule["max"]:
            failures.append(
                {
                    "kind": "over_budget",
                    "metric": key,
                    "value": value,
                    "max": rule["max"],
                }
            )
        if "min" in rule and value < rule["min"]:
            failures.append(
                {
                    "kind": "under_budget",
                    "metric": key,
                    "value": value,
                    "min": rule["min"],
                }
            )

    return {
        "schema_version": 1,
        "verdict": "PASS" if not failures else "FAIL",
        "measurement_authority": {
            "cold_start_process_tree": "neko_native_runtime_memory_baseline",
            "live_process_soak": "xiaoyu_read_only_companion_runtime_soak",
            "plugin_recovery": "xiaoyu_existing_native_api_reconcile",
            "adapter": "normalization_and_budget_only",
        },
        "metrics": dict(sorted(metrics.items())),
        "budgets": dict(sorted(normalized_budgets.items())),
        "failures": failures,
    }


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-benchmark", type=Path)
    parser.add_argument("--live-soak", type=Path)
    parser.add_argument("--plugin-reconcile", type=Path)
    parser.add_argument("--budgets", type=Path, required=True)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()

    if (
        args.native_benchmark is None
        and args.live_soak is None
        and args.plugin_reconcile is None
    ):
        parser.error("at least one measurement source is required")

    native = _read_json(args.native_benchmark)
    soak = _read_json(args.live_soak)
    plugin_reconcile = _read_json(args.plugin_reconcile)
    budget_payload = _read_json(args.budgets) or {}
    metrics, source_errors = extract_metrics(native, soak, plugin_reconcile)
    result = evaluate(metrics, budget_payload, source_errors=source_errors)

    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result_path is not None:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
