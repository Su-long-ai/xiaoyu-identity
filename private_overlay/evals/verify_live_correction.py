from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import gc
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SOURCE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_WORK = Path(r"D:\xiaoyu_private_overlay_state\correction-e2e")
DEFAULT_POLICY = OVERLAY_ROOT / "privacy" / "provider_policy.json"

OLD_TEXT = "主人用于验收的测试杯标签颜色是蓝色"
NEW_TEXT = "主人用于验收的测试杯标签颜色是绿色"
ENTRY_ID = "xiaoyu_live_correction_probe"


def _set_storage(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


class _EmptyReflections:
    async def aupdate_suppressions(self, _name: str) -> None:
        return None

    async def aget_pending_reflections(self, _name: str, **_kwargs):
        return []

    async def aget_confirmed_reflections(self, _name: str, **_kwargs):
        return []


def _extract_json(text: str) -> dict:
    raw = text.strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _green(value: object) -> bool:
    s = str(value or "").strip().casefold()
    return s in {"绿色", "绿", "green"}


async def _run(args: argparse.Namespace) -> int:
    if args.work_root.exists():
        shutil.rmtree(args.work_root)
    shutil.copytree(args.source_root, args.work_root)
    _set_storage(args.work_root)

    sys.path.insert(0, str(args.neko_root.resolve()))
    sys.path.insert(0, str((OVERLAY_ROOT / "tools").resolve()))

    from check_provider_privacy import host_is_allowed
    from memory.event_log import EventLog
    from memory.introspection import arender_injected_memory
    from memory.persona import PersonaManager
    from memory.refine import annotate_entry
    from utils.config_manager import get_config_manager
    from utils.llm_client import HumanMessage, SystemMessage, create_chat_llm

    result: dict = {
        "schema_version": 1,
        "neko_commit": args.neko_commit,
        "source_root": str(args.source_root.resolve()),
        "work_root": str(args.work_root.resolve()),
        "source_product_data_touched": False,
        "synthetic_fact_only": True,
        "old_text_recorded": False,
        "new_text_recorded": False,
        "model_response_recorded": False,
    }

    try:
        cm = get_config_manager()
        character_data = cm.get_character_data()
        active_character = str(character_data[1] or "")
        if active_character != "XiaoYu":
            raise RuntimeError(f"active character is not XiaoYu: {active_character!r}")

        pm = PersonaManager(event_log=EventLog())
        persona = await pm.aensure_persona(active_character)
        section = pm._get_section_facts(persona, "master")

        # Remove residue if a previous interrupted probe existed in the copied state.
        section[:] = [
            entry for entry in section
            if not (isinstance(entry, dict) and entry.get("id") == ENTRY_ID)
        ]

        entry = pm._normalize_entry(OLD_TEXT)
        entry["id"] = ENTRY_ID
        entry["source"] = "synthetic_acceptance_probe"
        section.append(entry)
        await pm.asave_persona(active_character, persona)

        seeded = await pm.aensure_persona(active_character)
        src = next(
            item for item in pm._get_section_facts(seeded, "master")
            if isinstance(item, dict) and item.get("id") == ENTRY_ID
        )
        cluster = [annotate_entry(src, type_="persona", entity="master")]
        actions = [{
            "action": "modify",
            "source_id": ENTRY_ID,
            "produce": {"text": NEW_TEXT},
            "reason": "synthetic owner correction acceptance probe",
        }]
        applied = await pm.apply_refine_actions(
            active_character, "master", cluster, actions, "xiaoyu_live_correction"
        )

        current = await pm.aensure_persona(active_character)
        target = next(
            item for item in pm._get_section_facts(current, "master")
            if isinstance(item, dict) and item.get("id") == ENTRY_ID
        )
        history = target.get("version_history") or []
        storage_ok = (
            applied == 1
            and target.get("text") == NEW_TEXT
            and any(item.get("text") == OLD_TEXT for item in history if isinstance(item, dict))
        )

        injected = await arender_injected_memory(
            pm,
            _EmptyReflections(),
            active_character,
            pinned_fact_store=None,
            lang="zh",
        )
        memory_text = injected.text
        render_ok = NEW_TEXT in memory_text and OLD_TEXT not in memory_text

        policy = json.loads(args.policy.read_text(encoding="utf-8-sig"))
        cfg = cm.get_model_api_config("correction")
        host = (urlsplit(str(cfg.get("base_url") or "")).hostname or "").lower()
        allowed, reason = host_is_allowed(host, policy)
        if not allowed:
            raise RuntimeError(f"correction provider not privacy-eligible: {host} ({reason})")

        api_key = str(cfg.get("api_key") or "").strip()
        credential_source = "neko_config"
        if not api_key and (
            host == "dashscope.aliyuncs.com"
            or host.endswith(".dashscope.aliyuncs.com")
        ):
            api_key = str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()
            credential_source = "environment:DASHSCOPE_API_KEY"
        if not api_key:
            raise RuntimeError("correction provider has no available API key")

        llm = create_chat_llm(
            model=cfg["model"],
            base_url=cfg.get("base_url"),
            api_key=api_key,
            provider_type=cfg.get("provider_type"),
            temperature=0,
            streaming=False,
            max_retries=1,
            max_completion_tokens=64,
            timeout=60.0,
        )
        probe = (
            '只依据上面的当前记忆回答。只输出严格 JSON：'
            '{"current_color":"当前测试杯标签颜色"}。'
        )
        try:
            response = await llm.ainvoke(
                [SystemMessage(content=memory_text), HumanMessage(content=probe)]
            )
            response_text = str(response.content or "").strip()
        finally:
            await llm.aclose()

        parsed = _extract_json(response_text)
        live_ok = _green(parsed.get("current_color"))
        verdict = "PASS" if storage_ok and render_ok and live_ok else "FAIL"
        result.update({
            "verdict": verdict,
            "character": active_character,
            "modify_applied": applied,
            "same_entry_id_after_modify": target.get("id") == ENTRY_ID,
            "version_history_contains_old_value": any(
                item.get("text") == OLD_TEXT
                for item in history
                if isinstance(item, dict)
            ),
            "current_storage_has_new_only": storage_ok,
            "new_dialog_render_has_new_only": render_ok,
            "live_model": cfg.get("model"),
            "live_host": host,
            "credential_source": credential_source,
            "live_model_current_color": parsed.get("current_color"),
            "live_model_sees_corrected_value": live_ok,
            "response_sha256": hashlib.sha256(
                response_text.encode("utf-8")
            ).hexdigest(),
        })
        return_code = 0 if verdict == "PASS" else 9
    finally:
        # The probe lives only in the copy. Always remove it so no synthetic
        # test fact becomes part of long-lived XiaoYu state.
        try:
            # N.E.K.O configures file-backed logging under the selected storage
            # root. Close those handlers before deleting the disposable copy on
            # Windows, where open log files cannot be unlinked.
            logging.shutdown()
            gc.collect()
            shutil.rmtree(args.work_root)
            result["work_root_cleaned"] = True
        except Exception as exc:
            result["work_root_cleaned"] = False
            result["cleanup_error_type"] = type(exc).__name__

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return return_code if result.get("work_root_cleaned") else 10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--work-root", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument(
        "--neko-commit",
        default="6261a5f653af066d2a7da8e265f624e3df03e3f7",
    )
    ap.add_argument("--evidence", type=Path)
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())