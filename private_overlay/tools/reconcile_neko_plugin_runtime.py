#!/usr/bin/env python3
"""Reconcile XiaoYu's use of N.E.K.O's native plugin runtime.

This adapter owns no plugin discovery, dependency graph, process host or durable
plugin preference. The embedded PluginServer does not run its full lifecycle
while the Agent master switch is off, which is XiaoYu's intended product mode.
We therefore ask the host to refresh its own registry and start only plugins
that the host itself marks enabled + auto-start + approved. Every actual start,
dependency check, permission check and process launch remains N.E.K.O-owned.

Separately, current N.E.K.O intent replay skips ``user_plugin_enabled`` when the
Agent master is off. We replay only that independent flag through the native
Agent flags API without enabling analyzer/computer/browser capabilities.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return data


def ensure_user_plugin_relay(
    *, agent_url: str, lanlan_name: str, request_timeout: float = 5.0,
) -> dict[str, Any]:
    agent_url = agent_url.rstrip("/")
    before = _json_request(f"{agent_url}/agent/flags", timeout=request_timeout)
    flags = before.get("agent_flags")
    if not isinstance(flags, dict):
        raise RuntimeError("Agent flags response missing agent_flags object")
    changed = flags.get("user_plugin_enabled") is not True
    if changed:
        _json_request(
            f"{agent_url}/agent/flags",
            method="POST",
            payload={"lanlan_name": lanlan_name, "user_plugin_enabled": True},
            timeout=request_timeout,
        )
    after = _json_request(f"{agent_url}/agent/flags", timeout=request_timeout)
    after_flags = after.get("agent_flags")
    if not isinstance(after_flags, dict) or after_flags.get("user_plugin_enabled") is not True:
        raise RuntimeError("N.E.K.O User Plugin relay did not become enabled")
    return {
        "user_plugin_enabled": True,
        "changed": changed,
        "analyzer_enabled": bool(after.get("analyzer_enabled")),
        "computer_use_enabled": bool(after_flags.get("computer_use_enabled")),
        "browser_use_enabled": bool(after_flags.get("browser_use_enabled")),
    }


def _autostart_candidates(payload: dict[str, Any]) -> list[str]:
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        raise RuntimeError("Plugin list response missing plugins array")
    result: list[str] = []
    for item in plugins:
        if not isinstance(item, dict):
            continue
        plugin_id = str(item.get("id") or "").strip()
        if not plugin_id:
            continue
        if item.get("runtime_enabled") is not True:
            continue
        if item.get("runtime_auto_start") is not True:
            continue
        # Preserve N.E.K.O's first-install approval fence. This adapter must not
        # turn a pending plugin into an implicit user-approved autostart.
        if item.get("autostart_pending") is True:
            continue
        result.append(plugin_id)
    return result


def reconcile_native_autostart(
    *, plugin_url: str, request_timeout: float = 10.0, max_passes: int = 3,
) -> dict[str, Any]:
    plugin_url = plugin_url.rstrip("/")
    _json_request(
        f"{plugin_url}/plugins/refresh",
        method="POST",
        payload={},
        timeout=max(request_timeout, 20.0),
    )
    initial = _json_request(f"{plugin_url}/plugins?summary=true", timeout=request_timeout)
    candidates = _autostart_candidates(initial)
    attempts: dict[str, list[str]] = {plugin_id: [] for plugin_id in candidates}

    pending = list(candidates)
    for _ in range(max(1, max_passes)):
        if not pending:
            break
        next_pending: list[str] = []
        progress = False
        for plugin_id in pending:
            try:
                result = _json_request(
                    f"{plugin_url}/plugin/{urllib.parse.quote(plugin_id, safe='')}/start",
                    method="POST",
                    payload={},
                    timeout=max(request_timeout, 30.0),
                )
                attempts[plugin_id].append("already_running" if result.get("already_running") else "started")
                progress = True
            except Exception as exc:
                attempts[plugin_id].append(f"{type(exc).__name__}: {exc}")
                next_pending.append(plugin_id)
        pending = next_pending
        if not progress:
            break

    final = _json_request(f"{plugin_url}/plugins?summary=true", timeout=request_timeout)
    plugins = final.get("plugins") if isinstance(final, dict) else None
    by_id = {
        str(item.get("id")): item
        for item in (plugins or [])
        if isinstance(item, dict) and item.get("id")
    }
    not_running = [plugin_id for plugin_id in candidates if by_id.get(plugin_id, {}).get("status") != "running"]
    return {
        "host_selected_candidates": candidates,
        "running": [plugin_id for plugin_id in candidates if plugin_id not in not_running],
        "not_running": not_running,
        "attempts": attempts,
        "host_registry_refreshed": True,
    }


def reconcile(
    *, plugin_url: str, agent_url: str, lanlan_name: str,
    deadline: float, request_timeout: float = 5.0,
) -> dict[str, Any]:
    last_error = ""
    while time.monotonic() < deadline:
        try:
            relay = ensure_user_plugin_relay(
                agent_url=agent_url,
                lanlan_name=lanlan_name,
                request_timeout=request_timeout,
            )
            autostart = reconcile_native_autostart(
                plugin_url=plugin_url,
                request_timeout=max(request_timeout, 5.0),
            )
            verdict = "PASS" if not autostart["not_running"] else "PARTIAL"
            return {
                "schema_version": 2,
                "verdict": verdict,
                "plugin_lifecycle_authority": "neko_native_http_api",
                "dependency_and_process_authority": "neko_native",
                "agent_master_required": False,
                "user_plugin_relay": relay,
                "native_autostart": autostart,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
    return {
        "schema_version": 2,
        "verdict": "FAIL",
        "plugin_lifecycle_authority": "neko_native_http_api",
        "dependency_and_process_authority": "neko_native",
        "agent_master_required": False,
        "error": last_error or "deadline exceeded",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-url", default="http://127.0.0.1:48916")
    parser.add_argument("--agent-url", default="http://127.0.0.1:48915")
    parser.add_argument("--lanlan-name", default="XiaoYu")
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    result = reconcile(
        plugin_url=args.plugin_url,
        agent_url=args.agent_url,
        lanlan_name=args.lanlan_name,
        deadline=time.monotonic() + max(1.0, args.wait_seconds),
    )
    text_output = json.dumps(result, ensure_ascii=False, indent=2)
    print(text_output)
    if args.result_path:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(text_output + "\n", encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
