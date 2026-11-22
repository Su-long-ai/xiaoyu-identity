from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SANDBOX = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
CHARACTER = "XiaoYu"
OLD_ALIAS = "碳基生物"
NEW_ALIAS = "主人"
_RUNTIME_PORTS = (48911, 48912, 48915, 48916)


def _set_isolated_environment(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _runtime_open_ports() -> list[int]:
    found = []
    for port in _RUNTIME_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                found.append(port)
        except OSError:
            pass
    return found


def find_legacy_owner_alias_entries(persona: dict) -> list[dict]:
    section = persona.get("neko") if isinstance(persona, dict) else None
    facts = section.get("facts") if isinstance(section, dict) else None
    if not isinstance(facts, list):
        return []
    rows = []
    for row in facts:
        if (
            isinstance(row, dict)
            and row.get("source") == "external_import"
            and OLD_ALIAS in str(row.get("text") or "")
        ):
            rows.append(row)
    return rows


def normalize_legacy_owner_alias_entries(persona: dict, persona_manager_cls) -> list[str]:
    changed_ids: list[str] = []
    for row in find_legacy_owner_alias_entries(persona):
        old_text = str(row.get("text") or "")
        new_text = old_text.replace(OLD_ALIAS, NEW_ALIAS)
        if new_text == old_text:
            continue

        history = row.get("version_history")
        if not isinstance(history, list):
            history = []
            row["version_history"] = history
        history.append(
            {
                "text": old_text,
                "replaced_at": datetime.now(timezone.utc).isoformat(),
                "reason": "owner_profile_alias_rename",
                "source_fact_id": row.get("id"),
            }
        )
        row["text"] = new_text
        persona_manager_cls._invalidate_token_count_cache(row)
        persona_manager_cls._invalidate_embedding_cache(row)
        row["last_refine_cluster_hash"] = None
        row["last_refine_at"] = None
        changed_ids.append(str(row.get("id") or ""))
    return changed_ids


async def _run(args: argparse.Namespace) -> int:
    if args.commit:
        open_ports = _runtime_open_ports()
        if open_ports:
            raise RuntimeError(
                "refuse live persona alias migration while N.E.K.O is running; open ports="
                + ",".join(map(str, open_ports))
            )

    _set_isolated_environment(args.sandbox)
    sys.path.insert(0, str(args.neko_root))

    from memory import PersonaManager
    from memory.event_log import EventLog

    manager = PersonaManager(event_log=EventLog())
    persona = await manager.aget_persona(args.character)
    candidates = find_legacy_owner_alias_entries(persona)
    report = {
        "mode": "commit" if args.commit else "verify_only",
        "character_name": args.character,
        "old_alias": OLD_ALIAS,
        "new_alias": NEW_ALIAS,
        "candidate_count": len(candidates),
        "candidate_ids": [str(row.get("id") or "") for row in candidates],
    }

    if args.commit and candidates:
        updated = deepcopy(persona)
        changed_ids = normalize_legacy_owner_alias_entries(updated, PersonaManager)
        await manager.asave_persona(args.character, updated)
        after = await manager.aget_persona(args.character)
        remaining = find_legacy_owner_alias_entries(after)
        report.update(
            {
                "changed_ids": changed_ids,
                "remaining_count": len(remaining),
            }
        )
        if remaining:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 5

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize legacy XiaoYu owner aliases through N.E.K.O native PersonaManager persistence."
    )
    parser.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    parser.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    parser.add_argument("--character", default=CHARACTER)
    parser.add_argument("--commit", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
