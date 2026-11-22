from __future__ import annotations

import argparse
import re
from pathlib import Path


def _read(root: Path, relpath: str) -> str:
    path = root / relpath
    if not path.is_file():
        raise SystemExit(f"BLOCK_PLUGIN_CRASH_GAP_PROBE: missing {relpath}")
    return path.read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"BLOCK_PLUGIN_CRASH_GAP_PROBE: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce the current N.E.K.O native plugin crash-recovery gap. "
            "This is a re-audit trigger, not a private restart implementation."
        )
    )
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.neko_root.resolve()

    status = _read(root, "plugin/core/status.py")
    host = _read(root, "plugin/core/host.py")
    lifecycle = _read(
        root, "plugin/server/application/plugins/lifecycle_service.py"
    )
    surface_map = _read(
        root,
        ".agent/skills/neko-plugin/references/plugin-system-surface-map.md",
    )

    _require(
        'plugin_state = "crashed"' in status,
        "native crash classification changed; re-audit lifecycle ownership",
    )
    _require(
        "Plugin process {} crashed" in host,
        "native process-crash observation changed; re-audit lifecycle ownership",
    )
    _require(
        "def _emit_lifecycle_event(" in lifecycle,
        "native lifecycle event publication seam changed",
    )

    event_types = set(
        re.findall(
            r'_emit_lifecycle_event\(\s*event_type\s*=\s*["\']([^"\']+)["\']',
            lifecycle,
            flags=re.MULTILINE,
        )
    )
    expected_explicit = {
        "plugin_start_requested",
        "plugin_started",
        "plugin_stop_requested",
        "plugin_stopped",
        "plugin_reload_requested",
        "plugin_reloaded",
    }
    _require(
        expected_explicit.issubset(event_types),
        "explicit native start/stop/reload lifecycle events changed",
    )

    crash_events = sorted(
        name
        for name in event_types
        if any(token in name.lower() for token in ("crash", "unexpected_exit", "process_exit"))
    )
    _require(
        not crash_events,
        "native crash-specific lifecycle event appeared "
        f"({crash_events}); stop tolerating the gap and re-run reuse selection",
    )

    lifecycle_lower = lifecycle.lower()
    restart_policy_tokens = (
        "restart_on_crash",
        "restart-on-crash",
        "autorestart",
        "auto_restart",
        "crash_restart",
        "crash-restart",
    )
    found_restart_policy = [
        token for token in restart_policy_tokens if token in lifecycle_lower
    ]
    _require(
        not found_restart_policy,
        "native crash-restart policy marker appeared "
        f"({found_restart_policy}); re-audit before keeping explicit-only recovery",
    )

    cross_start = surface_map.find("### Cross-Plugin Calls: `Plugins`")
    cross_end = surface_map.find("### Config:", cross_start)
    _require(
        cross_start >= 0 and cross_end > cross_start,
        "Plugin SDK cross-plugin documentation section changed",
    )
    cross_plugin = surface_map[cross_start:cross_end]
    management_api = re.findall(
        r"Plugins\.(?:start|stop|restart|reload)(?:_plugin)?\s*\(",
        cross_plugin,
        flags=re.IGNORECASE,
    )
    _require(
        not management_api,
        "Plugin SDK runtime-management API appeared "
        f"({sorted(set(management_api))}); re-audit native recovery design",
    )

    lifecycle_marker = (
        '@lifecycle(id="startup|shutdown|reload|freeze|unfreeze|config_change"'
    )
    _require(
        lifecycle_marker in surface_map,
        "Plugin SDK lifecycle hook vocabulary changed; re-audit crash recovery",
    )

    print(
        "PASS: reproduced native plugin crash-recovery gap "
        "(crash detection exists; no crash event, generic restart policy, "
        "or Plugin SDK restart-management API)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
