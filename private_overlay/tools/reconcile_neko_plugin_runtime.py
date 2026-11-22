#!/usr/bin/env python3
"""Reconcile N.E.K.O embedded plugin autostart after the host is ready.

XiaoYu keeps the Agent master switch off to avoid unnecessary background
agent work while still using N.E.K.O's User Plugin message relay and honoring
plugins whose native runtime_auto_start preference is on. Current N.E.K.O
PluginServer has native dependency-aware autostart; this helper is a recovery
path for source launches and also restores the independent User Plugin relay
through the native Agent flags API. It contains no plugin business logic and
never enables Agent analyzer/computer/browser flags.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method=method
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return data


def _origin(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _plugin_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plugins = payload.get("plugins", [])
    if not isinstance(plugins, list):
        return []
    return [item for item in plugins if isinstance(item, dict)]


def select_autostart_candidates(
    plugins: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return (needs_start, already_running) from native runtime preferences."""
    needs_start: list[str] = []
    already_running: list[str] = []
    for plugin in plugins:
        plugin_id = str(plugin.get("id") or "").strip()
        if not plugin_id:
            continue
        if plugin.get("runtime_enabled") is not True:
            continue
        if plugin.get("runtime_auto_start") is not True:
            continue
        if str(plugin.get("status") or "").lower() == "running":
            already_running.append(plugin_id)
        else:
            needs_start.append(plugin_id)
    return needs_start, already_running


def order_autostart_candidates(
    plugins: list[dict[str, Any]], needs_start: list[str],
) -> list[str]:
    """Stable topological order for fallback starts using N.E.K.O registry metadata.

    Native PluginServer autostart is the primary dependency-aware path. This
    helper is only a recovery path, but it must never start a dependent before
    a provider when both still need starting.
    """
    candidate_set = set(needs_start)
    by_id = {
        str(item.get("id") or "").strip(): item
        for item in plugins
        if str(item.get("id") or "").strip()
    }
    original_index = {plugin_id: i for i, plugin_id in enumerate(needs_start)}
    deps: dict[str, set[str]] = {plugin_id: set() for plugin_id in needs_start}

    for plugin_id in needs_start:
        raw_deps = by_id.get(plugin_id, {}).get("dependencies", [])
        if not isinstance(raw_deps, list):
            continue
        for dep in raw_deps:
            dep_id = ""
            if isinstance(dep, dict):
                dep_id = str(dep.get("id") or "").strip()
            elif isinstance(dep, str):
                dep_id = dep.strip()
            if dep_id in candidate_set and dep_id != plugin_id:
                deps[plugin_id].add(dep_id)

    ordered: list[str] = []
    remaining = set(needs_start)
    while remaining:
        ready = [
            plugin_id
            for plugin_id in needs_start
            if plugin_id in remaining and not (deps[plugin_id] & remaining)
        ]
        if not ready:
            # A cycle or malformed metadata should not make recovery nondeterministic.
            ordered.extend(
                sorted(remaining, key=lambda plugin_id: original_index[plugin_id])
            )
            break
        for plugin_id in ready:
            ordered.append(plugin_id)
            remaining.remove(plugin_id)
    return ordered


def ensure_user_plugin_relay(
    *, agent_url: str, lanlan_name: str, request_timeout: float = 5.0,
) -> dict[str, Any]:
    """Enable only N.E.K.O's independent User Plugin relay.

    The POST intentionally contains no analyzer/computer/browser fields. Those
    flags remain under their existing authority; this helper only restores the
    relay needed for plugin bus user-message delivery.
    """
    agent_url = agent_url.rstrip("/")
    before = _json_request(
        f"{agent_url}/agent/flags",
        timeout=request_timeout,
    )
    flags = before.get("agent_flags")
    if not isinstance(flags, dict):
        raise RuntimeError("Agent flags response missing agent_flags object")

    if flags.get("user_plugin_enabled") is not True:
        _json_request(
            f"{agent_url}/agent/flags",
            method="POST",
            payload={
                "lanlan_name": lanlan_name,
                "user_plugin_enabled": True,
            },
            timeout=request_timeout,
        )

    after = _json_request(
        f"{agent_url}/agent/flags",
        timeout=request_timeout,
    )
    after_flags = after.get("agent_flags")
    if not isinstance(after_flags, dict):
        raise RuntimeError("Agent flags verification missing agent_flags object")
    if after_flags.get("user_plugin_enabled") is not True:
        raise RuntimeError("N.E.K.O User Plugin relay did not become enabled")
    return {
        "user_plugin_enabled": True,
        "analyzer_enabled": bool(after.get("analyzer_enabled")),
        "computer_use_enabled": bool(after_flags.get("computer_use_enabled")),
        "browser_use_enabled": bool(after_flags.get("browser_use_enabled")),
    }


def reconcile(
    *,
    main_url: str,
    plugin_url: str,
    agent_url: str,
    lanlan_name: str,
    deadline: float,
    request_timeout: float = 5.0,
) -> dict[str, Any]:
    main_url = main_url.rstrip("/")
    plugin_url = plugin_url.rstrip("/")
    origin = _origin(main_url)
    last_error = ""

    while time.monotonic() < deadline:
        try:
            relay_state = ensure_user_plugin_relay(
                agent_url=agent_url,
                lanlan_name=lanlan_name,
                request_timeout=request_timeout,
            )
            page = _json_request(
                f"{main_url}/api/config/page_config?"
                + urllib.parse.urlencode({"lanlan_name": lanlan_name}),
                timeout=request_timeout,
            )
            token = str(page.get("autostart_csrf_token") or "")
            if not token:
                raise RuntimeError(
                    "main page_config returned no autostart_csrf_token"
                )
            mutation_headers = {
                "Origin": origin,
                "X-CSRF-Token": token,
            }
            refresh = _json_request(
                f"{plugin_url}/plugins/refresh",
                method="POST",
                payload={},
                headers=mutation_headers,
                timeout=request_timeout,
            )
            listing = _json_request(
                f"{plugin_url}/plugins?summary=true",
                timeout=request_timeout,
            )
            plugins = _plugin_list(listing)
            if not plugins:
                raise RuntimeError("plugin registry still empty after refresh")

            needs_start, already_running = select_autostart_candidates(plugins)
            needs_start = order_autostart_candidates(plugins, needs_start)
            started: list[str] = []
            failed: dict[str, str] = {}
            for plugin_id in needs_start:
                try:
                    result = _json_request(
                        f"{plugin_url}/plugin/"
                        + urllib.parse.quote(plugin_id, safe="")
                        + "/start",
                        method="POST",
                        payload={},
                        headers=mutation_headers,
                        timeout=max(request_timeout, 20.0),
                    )
                    if result.get("success") is True:
                        started.append(plugin_id)
                    else:
                        failed[plugin_id] = json.dumps(
                            result, ensure_ascii=False, sort_keys=True
                        )
                except Exception as exc:
                    failed[plugin_id] = f"{type(exc).__name__}: {exc}"

            return {
                "schema_version": 1,
                "verdict": "PASS" if not failed else "PARTIAL",
                "registry_refreshed": refresh.get("success") is True,
                "discovered_count": len(plugins),
                "autostart_candidates": sorted(needs_start + already_running),
                "started": sorted(started),
                "already_running": sorted(already_running),
                "failed": failed,
                "agent_master_required": False,
                "native_api_only": True,
                "user_plugin_relay": relay_state,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)

    return {
        "schema_version": 1,
        "verdict": "FAIL",
        "registry_refreshed": False,
        "discovered_count": 0,
        "autostart_candidates": [],
        "started": [],
        "already_running": [],
        "failed": {"startup_reconcile": last_error or "deadline exceeded"},
        "agent_master_required": False,
        "native_api_only": True,
        "user_plugin_relay": {
            "user_plugin_enabled": False,
            "error": last_error or "deadline exceeded",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-url", default="http://127.0.0.1:48911")
    parser.add_argument("--plugin-url", default="http://127.0.0.1:48916")
    parser.add_argument("--agent-url", default="http://127.0.0.1:48915")
    parser.add_argument("--lanlan-name", default="XiaoYu")
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()

    result = reconcile(
        main_url=args.main_url,
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
    return 0 if result["verdict"] in {"PASS", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
