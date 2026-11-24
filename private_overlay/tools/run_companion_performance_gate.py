#!/usr/bin/env python3
"""Run XiaoYu Companion performance acceptance over existing measurement authorities.

Live mode reuses the authoritative N.E.K.O launcher record plus XiaoYu's existing
read-only companion soak and startup reconcile result. Cold-start mode consumes
N.E.K.O's native runtime_memory_baseline JSON. This module does not launch,
restart, supervise or transport Companion runtime state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from private_overlay.tools.check_companion_performance import evaluate, extract_metrics
from private_overlay.tools.companion_runtime_soak import run_soak
from private_overlay.tools.reconcile_neko_plugin_runtime import (
    resolve_native_runtime_record,
)


OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGETS = OVERLAY_ROOT / "release" / "COMPANION_PERFORMANCE_BUDGETS.json"


def _read_object(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _profile_budgets(path: Path, profile: str) -> dict[str, Any]:
    payload = _read_object(path)
    assert payload is not None
    if payload.get("schema_version") != 1:
        raise ValueError("Companion performance budget schema_version must be 1")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Companion performance budgets missing profiles object")
    selected = profiles.get(profile)
    if not isinstance(selected, dict):
        raise ValueError(f"Companion performance profile {profile!r} is missing")
    budgets = selected.get("budgets")
    if not isinstance(budgets, dict) or not budgets:
        raise ValueError(f"Companion performance profile {profile!r} has no budgets")
    return budgets


def _runtime_urls(runtime_record: dict[str, Any]) -> dict[str, str]:
    if runtime_record.get("ready") is not True:
        raise ValueError(
            "N.E.K.O launcher record is not ready: "
            + str(runtime_record.get("state") or "unknown")
        )
    required = {
        "main": ("main_url", "/"),
        "memory": ("memory_url", "/health"),
        "agent": ("agent_url", "/health"),
        "plugin": ("plugin_url", "/plugins?summary=true"),
    }
    urls: dict[str, str] = {}
    for name, (key, suffix) in required.items():
        base = str(runtime_record.get(key) or "").rstrip("/")
        if not base:
            raise ValueError(f"N.E.K.O launcher record missing {key}")
        urls[name] = base + suffix
    return urls


def _current_reconcile(
    path: Path | None,
    *,
    current_instance_id: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, ["plugin_reconcile:missing_result"]
    try:
        payload = _read_object(path)
    except FileNotFoundError:
        return None, ["plugin_reconcile:missing_result"]
    assert payload is not None
    runtime_record = payload.get("runtime_record")
    if not isinstance(runtime_record, dict):
        return payload, ["plugin_reconcile:missing_runtime_record"]
    reconcile_instance_id = str(runtime_record.get("instance_id") or "")
    if not reconcile_instance_id:
        return payload, ["plugin_reconcile:missing_instance_id"]
    if reconcile_instance_id != current_instance_id:
        return payload, [
            "plugin_reconcile:stale_instance:"
            + reconcile_instance_id
            + "!="
            + current_instance_id
        ]
    return payload, []


def run_gate(
    *,
    profile: str,
    budgets_path: Path,
    runtime_record_path: Path | None = None,
    reconcile_result_path: Path | None = None,
    native_benchmark_path: Path | None = None,
    duration_seconds: float = 60.0,
    interval_seconds: float = 2.0,
    timeout_seconds: float = 2.0,
    neko_root: Path | None = None,
    desktop_exe: Path | None = None,
) -> dict[str, Any]:
    budgets = _profile_budgets(budgets_path, profile)
    source_errors: list[str] = []
    native_benchmark: dict[str, Any] | None = None
    live_soak: dict[str, Any] | None = None
    plugin_reconcile: dict[str, Any] | None = None
    runtime_record: dict[str, Any] | None = None

    if profile == "live":
        if runtime_record_path is None:
            source_errors.append("runtime_record:missing_path")
        else:
            runtime_record = resolve_native_runtime_record(runtime_record_path)
            if runtime_record.get("ready") is not True:
                source_errors.append(
                    "runtime_record:not_ready:"
                    + str(runtime_record.get("state") or "unknown")
                )
            else:
                live_soak = run_soak(
                    duration_seconds=duration_seconds,
                    interval_seconds=interval_seconds,
                    timeout=timeout_seconds,
                    urls=_runtime_urls(runtime_record),
                    neko_root=neko_root,
                    desktop_exe=desktop_exe,
                )
                plugin_reconcile, reconcile_errors = _current_reconcile(
                    reconcile_result_path,
                    current_instance_id=str(runtime_record.get("instance_id") or ""),
                )
                source_errors.extend(reconcile_errors)
    elif profile == "cold_start":
        if native_benchmark_path is None:
            source_errors.append("native_benchmark:required_for_cold_start")
        else:
            try:
                native_benchmark = _read_object(native_benchmark_path)
            except FileNotFoundError:
                source_errors.append("native_benchmark:missing_file")
    else:
        raise ValueError(f"unsupported Companion performance profile: {profile}")

    metrics, extraction_errors = extract_metrics(
        native_benchmark,
        live_soak,
        plugin_reconcile,
    )
    source_errors.extend(extraction_errors)
    performance = evaluate(metrics, budgets, source_errors=source_errors)
    result: dict[str, Any] = {
        "schema_version": 1,
        "profile": profile,
        "verdict": performance["verdict"],
        "performance": performance,
        "sources": {
            "runtime_record": runtime_record,
            "live_soak": live_soak,
            "plugin_reconcile_present": plugin_reconcile is not None,
            "native_benchmark_present": native_benchmark is not None,
        },
        "ownership": {
            "runtime_lifecycle": "neko_native",
            "cold_start_measurement": "neko_native_runtime_memory_baseline",
            "live_measurement": "xiaoyu_existing_read_only_companion_runtime_soak",
            "plugin_reconcile": "xiaoyu_existing_native_api_reconcile",
            "orchestrator": "composition_and_budget_only",
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("live", "cold_start"), default="live")
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--runtime-record", type=Path)
    parser.add_argument("--reconcile-result", type=Path)
    parser.add_argument("--native-benchmark", type=Path)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    parser.add_argument("--neko-root", type=Path)
    parser.add_argument("--desktop-exe", type=Path)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()

    runtime_record = args.runtime_record
    reconcile_result = args.reconcile_result
    if args.storage_root is not None:
        runtime_dir = args.storage_root / ".runtime"
        if runtime_record is None:
            runtime_record = runtime_dir / "launcher.json"
        if reconcile_result is None:
            reconcile_result = runtime_dir / "xiaoyu_plugin_runtime_reconcile.json"

    result = run_gate(
        profile=args.profile,
        budgets_path=args.budgets,
        runtime_record_path=runtime_record,
        reconcile_result_path=reconcile_result,
        native_benchmark_path=args.native_benchmark,
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
        timeout_seconds=args.timeout_seconds,
        neko_root=args.neko_root,
        desktop_exe=args.desktop_exe,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result_path is not None:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
