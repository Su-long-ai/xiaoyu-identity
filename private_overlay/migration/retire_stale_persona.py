from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SANDBOX = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
CHARACTER = "XiaoYu"
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


def find_stale_relationship_entries(persona: dict) -> list[dict]:
    """Known pre-continuity import residue: 'we just started knowing each other'."""
    rows = []
    section = persona.get("neko") if isinstance(persona, dict) else None
    facts = section.get("facts") if isinstance(section, dict) else None
    if not isinstance(facts, list):
        return rows
    for entry in facts:
        if not isinstance(entry, dict) or entry.get("source") != "external_import":
            continue
        text = str(entry.get("text") or "")
        if "刚开始认识" in text or "刚认识彼此" in text:
            rows.append(
                {
                    "entity": "neko",
                    "id": str(entry.get("id") or ""),
                    "text": text,
                    "source": entry.get("source"),
                }
            )
    return rows


async def _run(args: argparse.Namespace) -> int:
    if args.commit:
        open_ports = _runtime_open_ports()
        if open_ports:
            raise RuntimeError(
                "refuse live persona archive while N.E.K.O is running; open ports="
                + ",".join(map(str, open_ports))
            )

    _set_isolated_environment(args.sandbox)
    sys.path.insert(0, str(args.neko_root))

    from memory import PersonaManager
    from memory.event_log import EventLog

    manager = PersonaManager(event_log=EventLog())
    persona = await manager.aget_persona(args.character)
    stale = find_stale_relationship_entries(persona)
    report = {
        "mode": "commit" if args.commit else "verify_only",
        "character_name": args.character,
        "stale_count": len(stale),
        "stale": stale,
        "archived": [],
    }

    if args.commit:
        for row in stale:
            ok = await manager.aarchive_persona_entry(
                args.character, row["entity"], row["id"]
            )
            report["archived"].append({"id": row["id"], "ok": bool(ok)})
        after = await manager.aget_persona(args.character)
        report["remaining_stale_count"] = len(find_stale_relationship_entries(after))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.commit and report.get("remaining_stale_count") != 0:
        return 5
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retire stale pre-continuity XiaoYu persona facts through N.E.K.O's native archive path."
    )
    parser.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    parser.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    parser.add_argument("--character", default=CHARACTER)
    parser.add_argument("--commit", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
