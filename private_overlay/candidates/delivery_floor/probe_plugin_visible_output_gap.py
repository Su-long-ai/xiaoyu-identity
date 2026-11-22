from __future__ import annotations

import argparse
from pathlib import Path


def _read(root: Path, relpath: str) -> str:
    path = root / relpath
    if not path.is_file():
        raise SystemExit(f"BLOCK_PLUGIN_VISIBLE_FLOOR_PROBE: missing {relpath}")
    return path.read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"BLOCK_PLUGIN_VISIBLE_FLOOR_PROBE: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce the current N.E.K.O plugin-visible final-admission gap."
    )
    parser.add_argument("--neko-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.neko_root.resolve()

    runtime = _read(root, "app/main_server/character_runtime.py")
    bridge = _read(root, "plugin/server/messaging/proactive_bridge.py")
    surface_map = _read(
        root,
        ".agent/skills/neko-plugin/references/plugin-system-surface-map.md",
    )

    chat_sink = runtime.find("await mgr.render_chat_blocks(")
    proactive_sink = runtime.find("mgr.submit_proactive_callback(")
    hud_sink = runtime.find("await ws.send_json(notif)", max(proactive_sink, 0))

    _require(chat_sink >= 0, "native plugin chat sink is no longer recognizable")
    _require(proactive_sink >= 0, "native proactive delivery sink is no longer recognizable")
    _require(hud_sink >= 0, "native plugin HUD sink is no longer recognizable")
    _require(
        chat_sink < proactive_sink < hud_sink,
        "publication ordering changed; re-audit whether direct chat/HUD still bypass final admission",
    )
    _require(
        'and "chat" in visibility' in runtime,
        "chat visibility gate changed; re-audit the native host",
    )
    _require(
        '"hud" in _vis' in runtime,
        "HUD visibility gate changed; re-audit the native host",
    )
    _require(
        "delivery=silent: skipping LLM channel (frontend HUD still fires)" in runtime,
        "blind/silent HUD counterexample changed; re-audit before promoting anything",
    )
    _require(
        "visibility is NOT consulted here" in bridge,
        "proactive bridge visibility semantics changed; re-audit",
    )
    _require(
        "push_message pre-check are planned for a later stage, not implemented"
        in surface_map,
        "Plugin SDK push_message permission enforcement changed; re-audit",
    )

    print(
        "PASS: reproduced native plugin-visible floor gap "
        "(direct chat/HUD sinks remain outside one final proactive admission seam)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
