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


def _bounded_timeout(
    deadline: float | None,
    preferred: float,
) -> float:
    """Cap one blocking request by the caller's absolute monotonic deadline."""
    preferred = max(0.001, float(preferred))
    if deadline is None:
        return preferred
    remaining = float(deadline) - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("reconcile deadline exhausted")
    # An absolute deadline is authoritative. Do not inflate a tiny positive
    # remainder to the no-deadline 1 ms normalization floor.
    return min(preferred, remaining)


def _valid_runtime_port(value: Any, *, key: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"runtime record missing valid {key}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"runtime record has out-of-range {key}: {port}")
    return port


def resolve_native_runtime_record(record_path: Path) -> dict[str, Any]:
    """Resolve N.E.K.O's authoritative launcher record without owning lifecycle."""
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {
            "present": False,
            "ready": False,
            "state": "missing",
            "record_path": str(record_path),
        }
    except (OSError, ValueError) as exc:
        return {
            "present": True,
            "ready": False,
            "state": "invalid",
            "record_path": str(record_path),
            "error": f"{type(exc).__name__}: {exc}",
        }

    if not isinstance(payload, dict):
        return {
            "present": True,
            "ready": False,
            "state": "invalid",
            "record_path": str(record_path),
            "error": "launcher record is not a JSON object",
        }

    app = str(payload.get("app") or "")
    if app and app != "N.E.K.O":
        return {
            "present": True,
            "ready": False,
            "state": "invalid",
            "record_path": str(record_path),
            "error": f"unexpected launcher record app: {app}",
        }

    state = str(payload.get("state") or "starting")
    base = {
        "present": True,
        "ready": state == "ready",
        "state": state,
        "record_path": str(record_path),
        "instance_id": str(payload.get("instance_id") or ""),
        "launch_id": str(payload.get("launch_id") or ""),
        "launch_mode": str(payload.get("launch_mode") or ""),
    }
    if state != "ready":
        return base

    try:
        ports = payload.get("ports")
        internal_ports = payload.get("internal_ports")
        if not isinstance(ports, dict):
            raise ValueError("runtime record missing ports")
        if not isinstance(internal_ports, dict):
            raise ValueError("runtime record missing internal_ports")
        agent_port = _valid_runtime_port(
            ports.get("TOOL_SERVER_PORT"), key="TOOL_SERVER_PORT"
        )
        plugin_port = _valid_runtime_port(
            internal_ports.get("USER_PLUGIN_SERVER_PORT"),
            key="USER_PLUGIN_SERVER_PORT",
        )
    except ValueError as exc:
        return {
            **base,
            "ready": False,
            "state": "invalid",
            "error": str(exc),
        }

    return {
        **base,
        "agent_url": f"http://127.0.0.1:{agent_port}",
        "plugin_url": f"http://127.0.0.1:{plugin_port}",
        "ports": {
            "TOOL_SERVER_PORT": agent_port,
            "USER_PLUGIN_SERVER_PORT": plugin_port,
        },
    }


def ensure_user_plugin_relay(
    *, agent_url: str, lanlan_name: str, request_timeout: float = 5.0,
    deadline: float | None = None,
) -> dict[str, Any]:
    agent_url = agent_url.rstrip("/")
    before = _json_request(
        f"{agent_url}/agent/flags",
        timeout=_bounded_timeout(deadline, request_timeout),
    )
    flags = before.get("agent_flags")
    if not isinstance(flags, dict):
        raise RuntimeError("Agent flags response missing agent_flags object")
    changed = flags.get("user_plugin_enabled") is not True
    if changed:
        _json_request(
            f"{agent_url}/agent/flags",
            method="POST",
            payload={"lanlan_name": lanlan_name, "user_plugin_enabled": True},
            timeout=_bounded_timeout(deadline, request_timeout),
        )
    after = _json_request(
        f"{agent_url}/agent/flags",
        timeout=_bounded_timeout(deadline, request_timeout),
    )
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
    deadline: float | None = None,
) -> dict[str, Any]:
    plugin_url = plugin_url.rstrip("/")
    phase_started = time.monotonic()
    _json_request(
        f"{plugin_url}/plugins/refresh",
        method="POST",
        payload={},
        timeout=_bounded_timeout(deadline, max(request_timeout, 20.0)),
    )
    initial = _json_request(
        f"{plugin_url}/plugins?summary=true",
        timeout=_bounded_timeout(deadline, request_timeout),
    )
    candidates = _autostart_candidates(initial)
    initial_plugins = initial.get("plugins") if isinstance(initial, dict) else None
    initial_by_id = {
        str(item.get("id")): item
        for item in (initial_plugins or [])
        if isinstance(item, dict) and item.get("id")
    }
    already_running = [
        plugin_id
        for plugin_id in candidates
        if initial_by_id.get(plugin_id, {}).get("status") == "running"
    ]
    attempts: dict[str, list[str]] = {
        plugin_id: (["already_running"] if plugin_id in already_running else [])
        for plugin_id in candidates
    }

    # A one-click/runtime reconcile is also an explicit crash-recovery point.
    # Do not bounce healthy host-owned plugin processes just because they are
    # declared auto-start; only ask N.E.K.O to start candidates that are not
    # currently running.
    pending = [plugin_id for plugin_id in candidates if plugin_id not in already_running]
    initial_not_running = list(pending)
    confirmed_running = set(already_running)
    deadline_exhausted = False
    for _ in range(max(1, max_passes)):
        if not pending:
            break
        next_pending: list[str] = []
        progress = False
        for index, plugin_id in enumerate(pending):
            try:
                start_timeout = _bounded_timeout(
                    deadline,
                    max(request_timeout, 30.0),
                )
            except TimeoutError:
                for remaining_id in pending[index:]:
                    attempts[remaining_id].append("deadline_exhausted")
                    next_pending.append(remaining_id)
                deadline_exhausted = True
                break
            try:
                result = _json_request(
                    f"{plugin_url}/plugin/{urllib.parse.quote(plugin_id, safe='')}/start",
                    method="POST",
                    payload={},
                    timeout=start_timeout,
                )
                attempts[plugin_id].append(
                    "already_running" if result.get("already_running") else "started"
                )
                confirmed_running.add(plugin_id)
                progress = True
            except Exception as exc:
                attempts[plugin_id].append(f"{type(exc).__name__}: {exc}")
                next_pending.append(plugin_id)
        pending = next_pending
        if deadline_exhausted or not progress:
            break

    final_state_confirmed = True
    try:
        final_timeout = _bounded_timeout(deadline, request_timeout)
    except TimeoutError:
        final_state_confirmed = False
        by_id = dict(initial_by_id)
        for plugin_id in confirmed_running:
            by_id[plugin_id] = {
                **by_id.get(plugin_id, {}),
                "id": plugin_id,
                "status": "running",
            }
    else:
        final = _json_request(
            f"{plugin_url}/plugins?summary=true",
            timeout=final_timeout,
        )
        plugins = final.get("plugins") if isinstance(final, dict) else None
        by_id = {
            str(item.get("id")): item
            for item in (plugins or [])
            if isinstance(item, dict) and item.get("id")
        }

    not_running = [
        plugin_id
        for plugin_id in candidates
        if by_id.get(plugin_id, {}).get("status") != "running"
    ]
    recovered = [
        plugin_id
        for plugin_id in initial_not_running
        if by_id.get(plugin_id, {}).get("status") == "running"
    ]
    elapsed_ms = round((time.monotonic() - phase_started) * 1000.0, 3)
    recovery_elapsed_ms = (
        elapsed_ms
        if initial_not_running and final_state_confirmed and not not_running
        else None
    )
    return {
        "host_selected_candidates": candidates,
        "running": [plugin_id for plugin_id in candidates if plugin_id not in not_running],
        "not_running": not_running,
        "initial_not_running": initial_not_running,
        "recovered": recovered,
        "elapsed_ms": elapsed_ms,
        "recovery_elapsed_ms": recovery_elapsed_ms,
        "attempts": attempts,
        "host_registry_refreshed": True,
        "final_state_confirmed": final_state_confirmed,
        "deadline_exhausted": deadline_exhausted,
    }


def reconcile(
    *, plugin_url: str, agent_url: str, lanlan_name: str,
    deadline: float, request_timeout: float = 5.0,
    runtime_record_path: Path | None = None,
    record_fallback_grace: float = 2.0,
) -> dict[str, Any]:
    started = time.monotonic()
    last_error = ""
    endpoint_authority = "explicit_urls"
    runtime_record: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        active_plugin_url = plugin_url
        active_agent_url = agent_url

        if runtime_record_path is not None:
            runtime_record = resolve_native_runtime_record(runtime_record_path)
            if runtime_record["present"]:
                if runtime_record["ready"] is not True:
                    endpoint_authority = "neko_launcher_record_wait"
                    last_error = (
                        "native runtime record not ready: "
                        + str(runtime_record.get("state") or "unknown")
                    )
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(0.25, remaining))
                    continue
                active_plugin_url = str(runtime_record["plugin_url"])
                active_agent_url = str(runtime_record["agent_url"])
                endpoint_authority = "neko_launcher_record"
            elif time.monotonic() - started < max(0.0, record_fallback_grace):
                endpoint_authority = "neko_launcher_record_grace"
                last_error = "native runtime record not published yet"
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.25, remaining))
                continue
            else:
                endpoint_authority = "explicit_urls_fallback"

        try:
            relay = ensure_user_plugin_relay(
                agent_url=active_agent_url,
                lanlan_name=lanlan_name,
                request_timeout=request_timeout,
                deadline=deadline,
            )
            autostart = reconcile_native_autostart(
                plugin_url=active_plugin_url,
                request_timeout=max(request_timeout, 5.0),
                deadline=deadline,
            )
            verdict = "PASS" if not autostart["not_running"] else "PARTIAL"
            return {
                "schema_version": 3,
                "verdict": verdict,
                "plugin_lifecycle_authority": "neko_native_http_api",
                "dependency_and_process_authority": "neko_native",
                "endpoint_authority": endpoint_authority,
                "runtime_record": runtime_record,
                "agent_url": active_agent_url,
                "plugin_url": active_plugin_url,
                "agent_master_required": False,
                "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
                "user_plugin_relay": relay,
                "native_autostart": autostart,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.5, remaining))
    return {
        "schema_version": 3,
        "verdict": "FAIL",
        "plugin_lifecycle_authority": "neko_native_http_api",
        "dependency_and_process_authority": "neko_native",
        "endpoint_authority": endpoint_authority,
        "runtime_record": runtime_record,
        "agent_master_required": False,
        "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
        "error": last_error or "deadline exceeded",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-url", default="http://127.0.0.1:48916")
    parser.add_argument("--agent-url", default="http://127.0.0.1:48915")
    parser.add_argument("--lanlan-name", default="XiaoYu")
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--runtime-record", type=Path)
    parser.add_argument("--record-fallback-grace", type=float, default=2.0)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    result = reconcile(
        plugin_url=args.plugin_url,
        agent_url=args.agent_url,
        lanlan_name=args.lanlan_name,
        deadline=time.monotonic() + max(1.0, args.wait_seconds),
        runtime_record_path=args.runtime_record,
        record_fallback_grace=max(0.0, args.record_fallback_grace),
    )
    text_output = json.dumps(result, ensure_ascii=False, indent=2)
    print(text_output)
    if args.result_path:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(text_output + "\n", encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
