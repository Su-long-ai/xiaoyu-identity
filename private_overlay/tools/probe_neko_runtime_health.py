#!/usr/bin/env python3
"""Bounded, read-only-first health check for XiaoYu's N.E.K.O runtime."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import reconcile_neko_plugin_runtime as runtime_reconcile


def _enabled_agent_capabilities(payload: dict[str, Any]) -> list[str]:
    flags = payload.get("agent_flags")
    if not isinstance(flags, dict):
        raise RuntimeError("Agent flags response missing agent_flags object")
    checks = {
        "agent_master": bool(
            payload.get("agent_enabled")
            or payload.get("master_enabled")
            or flags.get("agent_enabled")
            or flags.get("master_enabled")
        ),
        "analyzer": bool(payload.get("analyzer_enabled") or flags.get("analyzer_enabled")),
        "computer": bool(flags.get("computer_use_enabled")),
        "browser": bool(flags.get("browser_use_enabled")),
    }
    return [name for name, enabled in checks.items() if enabled]


def probe(
    *, service_urls: dict[str, str], plugin_url: str, agent_url: str,
    request_timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    services: dict[str, str] = {}
    errors: list[str] = []
    for name, url in service_urls.items():
        try:
            runtime_reconcile._json_request(url, timeout=request_timeout)
            services[name] = "healthy"
        except Exception as exc:
            services[name] = "unhealthy"
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    enabled_capabilities: list[str] = []
    try:
        flags = runtime_reconcile._json_request(
            f"{agent_url.rstrip('/')}/agent/flags", timeout=request_timeout
        )
        enabled_capabilities = _enabled_agent_capabilities(flags)
    except Exception as exc:
        errors.append(f"agent_flags: {type(exc).__name__}: {exc}")

    expected: list[str] = []
    not_running: list[str] = []
    try:
        plugin_payload = runtime_reconcile._json_request(
            f"{plugin_url.rstrip('/')}/plugins?summary=true", timeout=request_timeout
        )
        expected = runtime_reconcile._autostart_candidates(plugin_payload)
        plugins = plugin_payload.get("plugins", [])
        by_id = {
            str(item.get("id")): item
            for item in plugins
            if isinstance(item, dict) and item.get("id")
        }
        not_running = [
            plugin_id
            for plugin_id in expected
            if by_id.get(plugin_id, {}).get("status") != "running"
        ]
    except Exception as exc:
        errors.append(f"plugins: {type(exc).__name__}: {exc}")

    healthy = not errors and not not_running and not enabled_capabilities
    return {
        "healthy": healthy,
        "services": services,
        "expected_runtime_auto_start_plugins": expected,
        "not_running": not_running,
        "forbidden_agent_capabilities_enabled": enabled_capabilities,
        "errors": errors,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
    }


def check_and_repair(
    *, service_urls: dict[str, str], plugin_url: str, agent_url: str,
    lanlan_name: str = "XiaoYu", request_timeout: float = 1.0,
    repair_timeout: float = 30.0,
    reconcile_fn: Callable[..., dict[str, Any]] = runtime_reconcile.reconcile,
) -> dict[str, Any]:
    started = time.monotonic()
    before = probe(
        service_urls=service_urls, plugin_url=plugin_url, agent_url=agent_url,
        request_timeout=request_timeout,
    )
    repair_attempted = bool(before["not_running"])
    repair_result: dict[str, Any] | None = None
    if repair_attempted:
        repair_result = reconcile_fn(
            plugin_url=plugin_url,
            agent_url=agent_url,
            lanlan_name=lanlan_name,
            deadline=time.monotonic() + max(1.0, repair_timeout),
            request_timeout=request_timeout,
        )
        after = probe(
            service_urls=service_urls, plugin_url=plugin_url, agent_url=agent_url,
            request_timeout=request_timeout,
        )
    else:
        after = before
    return {
        "schema_version": 1,
        "verdict": "PASS" if after["healthy"] else "FAIL",
        "authority": "neko_native_http_api",
        "repair_attempted": repair_attempted,
        "repair_attempts": 1 if repair_attempted else 0,
        "before": before,
        "repair_result": repair_result,
        "after": after,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-health-url", default="http://127.0.0.1:48911/health")
    parser.add_argument("--memory-health-url", default="http://127.0.0.1:48912/health")
    parser.add_argument("--agent-health-url", default="http://127.0.0.1:48915/health")
    parser.add_argument("--plugin-health-url", default="http://127.0.0.1:48916/health")
    parser.add_argument("--plugin-url", default="http://127.0.0.1:48916")
    parser.add_argument("--agent-url", default="http://127.0.0.1:48915")
    parser.add_argument("--lanlan-name", default="XiaoYu")
    parser.add_argument("--request-timeout", type=float, default=1.0)
    parser.add_argument("--repair-timeout", type=float, default=30.0)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    result = check_and_repair(
        service_urls={
            "main": args.main_health_url,
            "memory": args.memory_health_url,
            "agent": args.agent_health_url,
            "plugin": args.plugin_health_url,
        },
        plugin_url=args.plugin_url,
        agent_url=args.agent_url,
        lanlan_name=args.lanlan_name,
        request_timeout=max(0.05, args.request_timeout),
        repair_timeout=max(1.0, args.repair_timeout),
    )
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.result_path:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(output + "\n", encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
