#!/usr/bin/env python3
"""Reconcile N.E.K.O embedded plugin autostart after the host is ready.

The embedded PluginServer deliberately does not own plugin lifecycle. XiaoYu
keeps the Agent master switch off to avoid unnecessary background agent work,
while still honoring plugins whose native runtime_auto_start preference is on.
This helper uses only N.E.K.O's local lifecycle APIs; it contains no plugin
business logic and never forces a plugin whose native preference is false.
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


def reconcile(
    *,
    main_url: str,
    plugin_url: str,
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
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-url", default="http://127.0.0.1:48911")
    parser.add_argument("--plugin-url", default="http://127.0.0.1:48916")
    parser.add_argument("--lanlan-name", default="XiaoYu")
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()

    result = reconcile(
        main_url=args.main_url,
        plugin_url=args.plugin_url,
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
