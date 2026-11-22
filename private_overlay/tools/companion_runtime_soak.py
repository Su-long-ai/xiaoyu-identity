#!/usr/bin/env python3
"""Observe XiaoYu's live companion runtime without becoming a runtime authority.

The probe is read-only: it samples the four local N.E.K.O service surfaces,
checks the host-declared auto-start plugin set, and (when psutil is available)
records lightweight process-count/RSS/CPU-time evidence. It never restarts a
service, publishes output, reads conversation text, or stores credentials.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_URLS = {
    "main": "http://127.0.0.1:48911/",
    "memory": "http://127.0.0.1:48912/health",
    "agent": "http://127.0.0.1:48915/health",
    "plugin": "http://127.0.0.1:48916/plugins?summary=true",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_get(url: str, *, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200) or 200)
        return {
            "ok": 200 <= status < 300,
            "status": status,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "body": raw,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "body": b"",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _host_autostart_state(payload: dict[str, Any]) -> dict[str, Any]:
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("plugin summary missing plugins array")
    candidates: list[dict[str, Any]] = []
    for raw in plugins:
        if not isinstance(raw, dict):
            continue
        plugin_id = str(raw.get("id") or "").strip()
        if not plugin_id:
            continue
        if raw.get("runtime_enabled") is not True:
            continue
        if raw.get("runtime_auto_start") is not True:
            continue
        if raw.get("autostart_pending") is True:
            continue
        candidates.append(
            {
                "id": plugin_id,
                "status": str(raw.get("status") or ""),
            }
        )
    return {
        "candidates": candidates,
        "not_running": [
            item["id"] for item in candidates if item["status"] != "running"
        ],
    }


def _process_snapshot(
    *, neko_root: Path | None, desktop_exe: Path | None,
) -> dict[str, Any]:
    try:
        import psutil  # type: ignore
    except Exception:
        return {"available": False, "reason": "psutil_unavailable"}

    desktop_resolved = str(desktop_exe.resolve()).casefold() if desktop_exe else ""
    launcher = str((neko_root / "launcher.py").resolve()).casefold() if neko_root else ""
    roles: dict[str, list[dict[str, Any]]] = {"desktop": [], "backend": []}

    for proc in psutil.process_iter(["pid", "exe", "cmdline", "memory_info", "cpu_times"]):
        try:
            info = proc.info
            exe = str(info.get("exe") or "")
            cmdline = [str(part) for part in (info.get("cmdline") or [])]
            role = None
            if desktop_resolved and exe and str(Path(exe).resolve()).casefold() == desktop_resolved:
                role = "desktop"
            elif launcher and any(str(part).casefold() == launcher for part in cmdline):
                role = "backend"
            if role is None:
                continue
            memory_info = info.get("memory_info")
            cpu_times = info.get("cpu_times")
            roles[role].append(
                {
                    "pid": int(info["pid"]),
                    "rss_bytes": int(getattr(memory_info, "rss", 0) or 0),
                    "cpu_seconds": float(
                        (getattr(cpu_times, "user", 0.0) or 0.0)
                        + (getattr(cpu_times, "system", 0.0) or 0.0)
                    ),
                }
            )
        except Exception:
            continue
    return {"available": True, **roles}


def sample_once(
    *,
    urls: dict[str, str] | None = None,
    timeout: float = 2.0,
    neko_root: Path | None = None,
    desktop_exe: Path | None = None,
) -> dict[str, Any]:
    urls = dict(DEFAULT_URLS if urls is None else urls)
    endpoints: dict[str, Any] = {}
    plugin_state: dict[str, Any] = {
        "candidates": [],
        "not_running": [],
        "parse_error": "",
    }

    for name, url in urls.items():
        result = _http_get(url, timeout=timeout)
        body = result.pop("body")
        endpoints[name] = result
        if name != "plugin" or not result["ok"]:
            continue
        try:
            payload = json.loads(body.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("plugin summary is not a JSON object")
            plugin_state.update(_host_autostart_state(payload))
        except Exception as exc:
            plugin_state["parse_error"] = f"{type(exc).__name__}: {exc}"

    return {
        "observed_at": _iso_now(),
        "endpoints": endpoints,
        "plugins": plugin_state,
        "processes": _process_snapshot(
            neko_root=neko_root,
            desktop_exe=desktop_exe,
        ),
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(float(ordered[index]), 3)


def summarize(
    samples: list[dict[str, Any]],
    *,
    elapsed_seconds: float,
    require_desktop: bool = False,
    require_single_backend: bool = False,
) -> dict[str, Any]:
    endpoint_names = sorted(
        {
            name
            for sample in samples
            for name in (sample.get("endpoints") or {})
        }
    )
    endpoints: dict[str, Any] = {}
    failures: list[str] = []

    for name in endpoint_names:
        rows = [
            sample["endpoints"][name]
            for sample in samples
            if name in sample.get("endpoints", {})
        ]
        latencies = [float(row["latency_ms"]) for row in rows if row.get("ok")]
        failed = [row for row in rows if not row.get("ok")]
        endpoints[name] = {
            "samples": len(rows),
            "failures": len(failed),
            "latency_ms_mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "latency_ms_p95": _percentile(latencies, 0.95),
            "latency_ms_max": round(max(latencies), 3) if latencies else None,
        }
        if failed:
            failures.append(f"endpoint:{name}:{len(failed)}")

    nonrunning_observations: dict[str, int] = {}
    parse_errors = 0
    for sample in samples:
        plugin = sample.get("plugins") or {}
        if plugin.get("parse_error"):
            parse_errors += 1
        for plugin_id in plugin.get("not_running") or []:
            nonrunning_observations[str(plugin_id)] = (
                nonrunning_observations.get(str(plugin_id), 0) + 1
            )
    if parse_errors:
        failures.append(f"plugin_summary_parse:{parse_errors}")
    if nonrunning_observations:
        failures.append("autostart_not_running")

    process_samples = [
        sample.get("processes") or {}
        for sample in samples
        if (sample.get("processes") or {}).get("available") is True
    ]
    process_summary: dict[str, Any] = {"available": bool(process_samples)}
    for role in ("desktop", "backend"):
        counts = [len(sample.get(role) or []) for sample in process_samples]
        rss_totals = [
            sum(int(item.get("rss_bytes") or 0) for item in sample.get(role) or [])
            for sample in process_samples
        ]
        role_summary: dict[str, Any] = {
            "count_min": min(counts) if counts else None,
            "count_max": max(counts) if counts else None,
            "rss_mib_max": (
                round(max(rss_totals) / 1024.0 / 1024.0, 3)
                if rss_totals
                else None
            ),
            "cpu_percent_approx": None,
        }
        if len(process_samples) >= 2 and elapsed_seconds > 0:
            first = {int(p["pid"]): float(p["cpu_seconds"]) for p in process_samples[0].get(role) or []}
            last = {int(p["pid"]): float(p["cpu_seconds"]) for p in process_samples[-1].get(role) or []}
            if first and first.keys() == last.keys():
                delta = sum(max(0.0, last[pid] - first[pid]) for pid in first)
                role_summary["cpu_percent_approx"] = round(
                    100.0 * delta / elapsed_seconds,
                    3,
                )
        process_summary[role] = role_summary

    if require_desktop and process_samples:
        counts = [len(sample.get("desktop") or []) for sample in process_samples]
        if any(count != 1 for count in counts):
            failures.append("desktop_process_count")
    if require_single_backend and process_samples:
        counts = [len(sample.get("backend") or []) for sample in process_samples]
        if any(count != 1 for count in counts):
            failures.append("backend_process_count")

    return {
        "schema_version": 1,
        "verdict": "PASS" if not failures else "FAIL",
        "sample_count": len(samples),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "endpoint_summary": endpoints,
        "plugin_summary": {
            "parse_errors": parse_errors,
            "nonrunning_observations": nonrunning_observations,
        },
        "process_summary": process_summary,
        "failures": failures,
        "privacy": {
            "conversation_text_recorded": False,
            "credentials_recorded": False,
            "window_titles_recorded": False,
        },
    }


def run_soak(
    *,
    duration_seconds: float,
    interval_seconds: float,
    timeout: float,
    urls: dict[str, str] | None = None,
    neko_root: Path | None = None,
    desktop_exe: Path | None = None,
    require_desktop: bool = False,
    require_single_backend: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + max(0.0, duration_seconds)
    samples: list[dict[str, Any]] = []

    while True:
        samples.append(
            sample_once(
                urls=urls,
                timeout=timeout,
                neko_root=neko_root,
                desktop_exe=desktop_exe,
            )
        )
        now = time.monotonic()
        if now >= deadline:
            break
        time.sleep(min(max(0.05, interval_seconds), max(0.0, deadline - now)))

    return summarize(
        samples,
        elapsed_seconds=max(0.0, time.monotonic() - started),
        require_desktop=require_desktop,
        require_single_backend=require_single_backend,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    parser.add_argument("--neko-root", type=Path, default=Path(r"D:\xiaoyu_external_audit\N.E.K.O"))
    parser.add_argument(
        "--desktop-exe",
        type=Path,
        default=Path(r"D:\xiaoyu_external_audit\neko-nightly-desktop\shell\N.E.K.O.exe"),
    )
    parser.add_argument("--require-desktop", action="store_true")
    parser.add_argument("--require-single-backend", action="store_true")
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()

    result = run_soak(
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
        timeout=args.timeout_seconds,
        neko_root=args.neko_root,
        desktop_exe=args.desktop_exe,
        require_desktop=args.require_desktop,
        require_single_backend=args.require_single_backend,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.result_path:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
