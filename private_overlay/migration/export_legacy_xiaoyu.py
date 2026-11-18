import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(r"D:\dsh-fish\identity\identity.sqlite3")
DEFAULT_OUT = Path(r"D:\xiaoyu_private_overlay_state\migration\current")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(raw: str) -> Any:
    return json.loads(raw)


def _latest_persona(con: sqlite3.Connection) -> tuple[dict[str, Any], str]:
    row = con.execute(
        "select persona_json from persona_versions order by version desc limit 1"
    ).fetchone()
    if row is not None:
        obj = _read_json(row[0])
        if not isinstance(obj, dict):
            raise ValueError("latest persona version is not an object")
        return obj, "persona_versions"

    row = con.execute("select value from settings where key='persona'").fetchone()
    if row is None:
        raise ValueError("no persona found in persona_versions or settings.persona")
    obj = _read_json(row[0])
    if not isinstance(obj, dict):
        raise ValueError("settings.persona is not an object")
    return obj, "settings.persona"


def _bullet_lines(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [f"- {str(v).strip()}" for v in values if str(v).strip()]


def render_soul(persona: dict[str, Any]) -> str:
    lines = ["# XiaoYu", ""]
    name = str(persona.get("name") or "XiaoYu").strip()
    if name:
        lines += ["## Name", name, ""]

    commitments = _bullet_lines(persona.get("identity_commitments"))
    if commitments:
        lines += ["## Identity commitments", *commitments, ""]

    style = persona.get("style")
    if isinstance(style, dict):
        style_lines = [
            f"- {key}: {value}"
            for key, value in sorted(style.items())
            if value is not None and str(value).strip()
        ]
        if style_lines:
            lines += ["## Interaction style", *style_lines, ""]

    growth = _bullet_lines(persona.get("growth_notes"))
    if growth:
        lines += ["## Growth notes", *growth, ""]

    bond = str(persona.get("bond_description") or "").strip()
    if bond:
        lines += ["## Relationship continuity", bond, ""]

    return "\n".join(lines).rstrip() + "\n"


def _current_memory_rows(con: sqlite3.Connection):
    rows = con.execute(
        """
        select memory_id, category, text, source_event, priority, status
        from memories
        order by created_at, memory_id
        """
    ).fetchall()
    included = []
    excluded = []
    for memory_id, category, text, source_event, priority, status in rows:
        normalized = str(status or "").strip().lower()
        record = {
            "memory_id": str(memory_id),
            "category": str(category or ""),
            "source_event": str(source_event or ""),
            "priority": priority,
            "status": str(status or ""),
        }
        if normalized in {"active", "confirmed"}:
            included.append((record, str(text or "").strip()))
        else:
            record["reason"] = f"status_not_current:{normalized or 'blank'}"
            excluded.append(record)
    return included, excluded


def render_memory(rows) -> str:
    lines = ["# Imported confirmed XiaoYu memories", ""]
    for metadata, text in rows:
        if not text:
            continue
        category = metadata.get("category") or "memory"
        lines += [f"## {category}", f"- {text}", ""]
    return "\n".join(lines).rstrip() + "\n"


def export(db: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    uri = f"file:{db.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        persona, persona_source = _latest_persona(con)
        memories, excluded = _current_memory_rows(con)
        event_count = con.execute("select count(*) from events").fetchone()[0]
        persona_count = con.execute("select count(*) from persona_versions").fetchone()[0]
        memory_count = con.execute("select count(*) from memories").fetchone()[0]
    finally:
        con.close()

    soul = render_soul(persona)
    soul_path = out_dir / "SOUL.md"
    soul_path.write_text(soul, encoding="utf-8")

    memory_path = None
    if memories:
        memory_path = out_dir / "MEMORY.md"
        memory_path.write_text(render_memory(memories), encoding="utf-8")
    else:
        stale = out_dir / "MEMORY.md"
        if stale.exists():
            stale.unlink()

    manifest = {
        "schema_version": 1,
        "source_db": str(db),
        "source_db_sha256": _sha256(db),
        "read_mode": "sqlite_uri_mode_ro",
        "persona_source": persona_source,
        "persona_versions": persona_count,
        "events_preserved_in_legacy_only": event_count,
        "memory_rows_total": memory_count,
        "memory_rows_selected": len(memories),
        "memory_rows_excluded": excluded,
        "outputs": {
            "SOUL.md": {
                "sha256": hashlib.sha256(soul.encode("utf-8")).hexdigest(),
                "bytes": len(soul.encode("utf-8")),
            },
            **(
                {
                    "MEMORY.md": {
                        "sha256": _sha256(memory_path),
                        "bytes": memory_path.stat().st_size,
                    }
                }
                if memory_path is not None
                else {}
            ),
        },
        "privacy": "raw persona/memory text stays only in local staging; do not commit this directory",
    }
    (out_dir / "migration_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    manifest = export(args.db, args.out)
    print(json.dumps({
        "source_db_sha256": manifest["source_db_sha256"],
        "persona_source": manifest["persona_source"],
        "persona_versions": manifest["persona_versions"],
        "events_preserved_in_legacy_only": manifest["events_preserved_in_legacy_only"],
        "memory_rows_total": manifest["memory_rows_total"],
        "memory_rows_selected": manifest["memory_rows_selected"],
        "memory_rows_excluded_count": len(manifest["memory_rows_excluded"]),
        "output_files": sorted(manifest["outputs"]),
        "staging_dir": str(args.out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
