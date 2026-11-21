from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_SEED = Path(__file__).resolve().parents[1] / "identity" / "persona.md"
DEFAULT_ENDPOINT = "http://127.0.0.1:48912"
CHARACTER = "XiaoYu"

_PERSONA_SECTIONS = {"Stable identity", "Growth", "Non-goals"}
_SKIP_PREFIXES = ("Name:",)
_SKIP_EXACT = {
    "No second memory database in the overlay.",
}


def extract_seed_candidates(text: str) -> list[dict]:
    """Extract only identity/persona bullets; infrastructure constraints stay overlay-only."""
    section = None
    candidates: list[dict] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.endswith(":"):
            candidate_section = line[:-1]
            section = candidate_section if candidate_section in _PERSONA_SECTIONS else None
            continue
        if not line.startswith("- "):
            continue
        bullet = line[2:].strip()
        if section not in _PERSONA_SECTIONS or not bullet:
            continue
        if bullet.startswith(_SKIP_PREFIXES) or bullet in _SKIP_EXACT:
            continue
        candidates.append(
            {
                "target": "persona",
                "entity": "neko",
                "text": bullet,
                "kind": "soul",
                "source_file": "identity/persona.md",
                "source_section": section,
                "event_date": None,
            }
        )
    return candidates


def _summary_from_persona_view(payload: dict) -> dict:
    sections = payload.get("sections") if isinstance(payload, dict) else None
    counts = {}
    total = 0
    if isinstance(sections, list):
        for row in sections:
            if not isinstance(row, dict):
                continue
            entity = str(row.get("entity") or "")
            entries = row.get("entries")
            count = len(entries) if isinstance(entries, list) else 0
            if entity:
                counts[entity] = count
            total += count
    return {"total_entries": total, "by_entity": counts}


async def _run(args: argparse.Namespace) -> int:
    import httpx

    seed_text = args.seed.read_text(encoding="utf-8")
    candidates = extract_seed_candidates(seed_text)
    if not candidates:
        raise RuntimeError(f"no persona seed candidates found in {args.seed}")

    report = {
        "mode": "commit" if args.commit else "verify_only",
        "character_name": args.character,
        "seed": str(args.seed),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if not args.commit:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    base = args.endpoint.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout)) as client:
        before = await client.get(f"{base}/internal/memory/{args.character}/persona")
        before.raise_for_status()
        payload = {
            "character_name": args.character,
            "source_format": "openclaw",
            "imported_files": ["identity/persona.md"],
            "candidates": candidates,
            "warning_count": 0,
            "render_language": "zh-CN",
        }
        response = await client.post(
            f"{base}/internal/memory/import_external_markdown",
            json=payload,
        )
        body = response.json()
        after = await client.get(f"{base}/internal/memory/{args.character}/persona")
        after.raise_for_status()

    report.update(
        {
            "http_status": response.status_code,
            "result": body,
            "before": _summary_from_persona_view(before.json()),
            "after": _summary_from_persona_view(after.json()),
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if response.status_code == 200 and body.get("status") == "success" else 5


def main() -> int:
    import asyncio

    parser = argparse.ArgumentParser(
        description="Seed XiaoYu identity into N.E.K.O's native persona authority."
    )
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--character", default=CHARACTER)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--commit", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
