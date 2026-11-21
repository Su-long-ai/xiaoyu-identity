"""Ensure XiaoYu's private activity preferences on top of N.E.K.O native settings.

This does not create a second preference store.  N.E.K.O's activity subsystem
explicitly reads the activity sub-dict from the native user_preferences.json.
XiaoYu only fixes the one private product choice that a focused-work break
reminder must never pivot into a mini-game invitation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

GLOBAL_CONVERSATION_KEY = "__global_conversation__"
TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY = 0.0


def _preferences_path(storage_root: Path) -> Path:
    return storage_root / "config" / "user_preferences.json"


def _load(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("user_preferences.json must contain a JSON array")
    return payload


def inspect_private_activity_preferences(storage_root: Path) -> dict[str, Any]:
    path = _preferences_path(storage_root)
    payload = _load(path)
    global_entry = next(
        (
            item
            for item in payload
            if isinstance(item, dict)
            and item.get("model_path") == GLOBAL_CONVERSATION_KEY
        ),
        None,
    )
    if global_entry is None:
        return {
            "ok": False,
            "reason": "global_conversation_entry_missing",
            "path": str(path),
        }
    activity = global_entry.get("activity")
    value = activity.get("work_break_game_invite_probability") if isinstance(activity, dict) else None
    return {
        "ok": value == TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY,
        "path": str(path),
        "value": value,
        "target": TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY,
    }


def ensure_private_activity_preferences(storage_root: Path, *, verify_only: bool = False) -> dict[str, Any]:
    path = _preferences_path(storage_root)
    payload = _load(path)
    global_entry = next(
        (
            item
            for item in payload
            if isinstance(item, dict)
            and item.get("model_path") == GLOBAL_CONVERSATION_KEY
        ),
        None,
    )
    if global_entry is None:
        raise RuntimeError("global conversation preference entry is missing")

    activity = global_entry.get("activity")
    if not isinstance(activity, dict):
        activity = {}
        if verify_only:
            return {
                "ok": False,
                "changed": False,
                "reason": "activity_preferences_missing",
                "path": str(path),
            }
        global_entry["activity"] = activity

    before = activity.get("work_break_game_invite_probability")
    if before == TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY:
        return {
            "ok": True,
            "changed": False,
            "path": str(path),
            "value": before,
        }

    if verify_only:
        return {
            "ok": False,
            "changed": False,
            "reason": "work_break_game_invite_probability_mismatch",
            "path": str(path),
            "value": before,
            "target": TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY,
        }

    activity["work_break_game_invite_probability"] = TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return {
        "ok": True,
        "changed": True,
        "path": str(path),
        "before": before,
        "value": TARGET_WORK_BREAK_GAME_INVITE_PROBABILITY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    result = ensure_private_activity_preferences(
        Path(args.storage_root).resolve(),
        verify_only=args.verify_only,
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
