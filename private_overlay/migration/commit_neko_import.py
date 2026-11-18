from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import types
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STAGE = Path(r"D:\xiaoyu_private_overlay_state\migration\current")
DEFAULT_SANDBOX = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_CHARACTER = "XiaoYu"


def _set_isolated_environment(root: Path) -> None:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _prepare_character(config_manager, character_name: str) -> None:
    data = config_manager.load_characters()
    catgirls = data.setdefault("猫娘", {})
    if character_name not in catgirls:
        profile = {
            "昵称": "小鱼",
            "性别": "女",
            "年龄": "",
            "性格原型": "",
            "种族": "",
            "自称": "小鱼",
            "核心特质": [],
            "行为特点": [],
            "厌恶": [],
            "一句话台词": "",
            "_reserved": {
                "system_prompt": "你是小鱼。长期人格以 N.E.K.O persona memory 中的当前事实为准。"
            },
        }
        catgirls[character_name] = profile
    data["当前猫娘"] = character_name
    # This is an isolated test root, not a cloud-save/product root.  The bypass
    # prevents an unbootstrapped cloud-save fence from blocking test-card setup.
    config_manager.save_characters(data, bypass_write_fence=True)
    # Re-load once so N.E.K.O assigns/persists its own stable reserved identity.
    config_manager.load_characters(require_authoritative=True)


def _load_candidates(stage: Path):
    from memory.external_markdown_import import MarkdownSourceFile, build_import_candidates

    sources = []
    for name in ("SOUL.md", "USER.md", "MEMORY.md"):
        path = stage / name
        if path.exists():
            sources.append(MarkdownSourceFile(name, path.read_text(encoding="utf-8")))
    if not sources:
        raise RuntimeError(f"no staged persona/memory files found under {stage}")
    analysis = build_import_candidates(sources, source_format="openclaw")
    return analysis


def _persona_summary(persona: dict) -> dict:
    imported = []
    for entity in ("neko", "master", "relationship"):
        section = persona.get(entity)
        if not isinstance(section, dict):
            continue
        facts = section.get("facts")
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if isinstance(fact, dict) and fact.get("source") == "external_import":
                imported.append(
                    {
                        "entity": entity,
                        "id": fact.get("id"),
                        "source": fact.get("source"),
                        "fingerprint": (fact.get("external_import") or {}).get("fusion_fingerprint"),
                    }
                )
    return {
        "persona_sha256": _digest(persona),
        "external_import_entries": len(imported),
        "external_import_metadata_sha256": _digest(imported),
    }


async def _run(args: argparse.Namespace) -> int:
    _set_isolated_environment(args.isolated_root)
    sys.path.insert(0, str(args.neko_root))

    from utils.config_manager import get_config_manager
    from app.memory_server import runtime, routes

    config_manager = get_config_manager()
    _prepare_character(config_manager, args.character_name)

    # Build only the real persistence components needed by the official import
    # routine. Full memory-server startup also warms unrelated region/vector/
    # background services and is intentionally outside this migration proof.
    from memory import FactStore, PersonaManager
    from memory.event_log import EventLog

    runtime.event_log = EventLog()
    runtime.fact_store = FactStore()
    runtime.persona_manager = PersonaManager(event_log=runtime.event_log)

    if args.verify_only:
        persona = await runtime.persona_manager.aget_persona(args.character_name)
        print(
            json.dumps(
                {
                    "mode": "verify_only",
                    "character_name": args.character_name,
                    **_persona_summary(persona),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    analysis = _load_candidates(args.stage)
    warnings = analysis.get("warnings") or []
    if warnings:
        raise RuntimeError("staged import has warnings; refuse isolated commit")

    fusion_calls = {"count": 0}

    async def _local_preserve_fusion(self, _name, _entity, candidates, _budget):
        """Deterministic no-network fusion for migration plumbing validation.

        The official N.E.K.O import/persistence/CAS/idempotency path stays real;
        only the model transport is replaced so private SOUL content never leaves
        the isolated machine before provider-privacy admission is accepted.
        """
        fusion_calls["count"] += 1
        result = []
        seen = set()
        for item in candidates:
            text = str(item.get("text") or "").strip()
            norm = " ".join(text.casefold().split())
            if not text or norm in seen:
                continue
            seen.add(norm)
            result.append({"text": text, "importance": 8})
        return result

    runtime.persona_manager._allm_call_fusion = types.MethodType(
        _local_preserve_fusion, runtime.persona_manager
    )

    request = routes.ExternalMemoryImportRequest(
        character_name=args.character_name,
        source_format=analysis["source_format"],
        imported_files=analysis["files"],
        candidates=analysis["candidates"],
        warning_count=len(warnings),
        render_language="zh-CN",
    )
    response = await routes._import_external_markdown(request, {})
    if hasattr(response, "body"):
        body = json.loads(response.body)
        status_code = int(getattr(response, "status_code", 500))
    else:
        body = response
        status_code = 200

    persona = await runtime.persona_manager.aget_persona(args.character_name)
    summary = {
        "mode": "commit",
        "status_code": status_code,
        "character_name": args.character_name,
        "source_format": analysis["source_format"],
        "candidate_count": len(analysis["candidates"]),
        "persona_candidates": sum(c.get("target") == "persona" for c in analysis["candidates"]),
        "fact_candidates": sum(c.get("target") == "facts" for c in analysis["candidates"]),
        "fusion_calls": fusion_calls["count"],
        "result_status": body.get("status") if isinstance(body, dict) else None,
        "added_persona": body.get("added_persona") if isinstance(body, dict) else None,
        "added_facts": body.get("added_facts") if isinstance(body, dict) else None,
        "skipped_duplicates": body.get("skipped_duplicates") if isinstance(body, dict) else None,
        **_persona_summary(persona),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status_code == 200 and summary["result_status"] == "success" else 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--isolated-root", type=Path, default=DEFAULT_SANDBOX)
    parser.add_argument("--character-name", default=DEFAULT_CHARACTER)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
