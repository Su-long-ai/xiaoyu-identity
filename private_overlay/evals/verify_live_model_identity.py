from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STORAGE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_POLICY = OVERLAY_ROOT / "privacy" / "provider_policy.json"
EXPECTED_NAMES = {"xiaoyu", "小鱼"}


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


def _name_ok(value: object) -> bool:
    normalized = re.sub(r"[\s._-]+", "", str(value or "").casefold())
    return normalized in EXPECTED_NAMES


async def _run(args: argparse.Namespace) -> int:
    _set_storage(args.storage_root)
    sys.path.insert(0, str(args.neko_root.resolve()))
    sys.path.insert(0, str((OVERLAY_ROOT / "tools").resolve()))

    from check_provider_privacy import host_is_allowed
    from memory.event_log import EventLog
    from memory.introspection import arender_injected_memory
    from memory.persona import PersonaManager
    from utils.config_manager import get_config_manager
    from utils.llm_client import HumanMessage, SystemMessage, create_chat_llm

    policy = json.loads(args.policy.read_text(encoding="utf-8-sig"))
    cm = get_config_manager()
    character_data = cm.get_character_data()
    active_character = str(character_data[1] or "")
    character_prompt = str((character_data[5] or {}).get(active_character) or "")
    if active_character != "XiaoYu":
        raise RuntimeError(f"active character is not XiaoYu: {active_character!r}")

    persona_manager = PersonaManager(event_log=EventLog())
    injected = await arender_injected_memory(
        persona_manager,
        _EmptyReflections(),
        active_character,
        pinned_fact_store=None,
        lang="zh",
    )
    persona_text = injected.text
    if not persona_text.strip():
        raise RuntimeError("XiaoYu persona render is empty")

    system_prompt = (
        character_prompt
        + "\n\n"
        + persona_text
        + "\n\n"
        + "当前角色身份必须跨底层模型保持连续。不要把底层模型品牌当作角色身份。"
    )
    probe = (
        '只输出一行严格 JSON，不要 Markdown：'
        '{"name":"你的角色名","same_identity_after_model_swap":true}. '
        "请按当前角色与长期人格状态填写。"
    )

    cases = []
    # Use two already-configured direct DashScope model tiers so no private
    # provider credential or endpoint is invented for this test.
    for tier in ("conversation", "summary"):
        cfg = cm.get_model_api_config(tier)
        host = ""
        try:
            from urllib.parse import urlsplit
            host = (urlsplit(str(cfg.get("base_url") or "")).hostname or "").lower()
        except Exception:
            pass
        allowed, reason = host_is_allowed(host, policy)
        if not allowed:
            raise RuntimeError(f"{tier} provider is not privacy-eligible: {host} ({reason})")
        api_key = str(cfg.get("api_key") or "").strip()
        credential_source = "neko_config"
        if not api_key and (
            host == "dashscope.aliyuncs.com"
            or host.endswith(".dashscope.aliyuncs.com")
        ):
            api_key = str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()
            credential_source = "environment:DASHSCOPE_API_KEY"
        if not api_key:
            raise RuntimeError(f"{tier} provider has no available API key")

        llm = create_chat_llm(
            model=cfg["model"],
            base_url=cfg.get("base_url"),
            api_key=api_key,
            provider_type=cfg.get("provider_type"),
            temperature=0,
            streaming=False,
            max_retries=1,
            max_completion_tokens=96,
            timeout=60.0,
        )
        try:
            response = await llm.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=probe)]
            )
            text = str(response.content or "").strip()
        finally:
            await llm.aclose()

        parsed = _extract_json(text)
        case = {
            "tier": tier,
            "model": cfg.get("model"),
            "host": host,
            "credential_source": credential_source,
            "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "parsed_name": parsed.get("name"),
            "same_identity_after_model_swap": parsed.get(
                "same_identity_after_model_swap"
            ),
            "name_ok": _name_ok(parsed.get("name")),
            "continuity_ok": parsed.get("same_identity_after_model_swap") is True,
        }
        case["pass"] = case["name_ok"] and case["continuity_ok"]
        cases.append(case)

    deepseek_key = str(os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    cross_provider_attempted = bool(deepseek_key)
    if deepseek_key:
        host = "api.deepseek.com"
        allowed, reason = host_is_allowed(host, policy)
        if not allowed:
            raise RuntimeError(f"DeepSeek provider is not privacy-eligible: {host} ({reason})")
        llm = create_chat_llm(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=deepseek_key,
            provider_type="openai_compatible",
            temperature=0,
            streaming=False,
            max_retries=1,
            max_completion_tokens=96,
            timeout=60.0,
        )
        try:
            response = await llm.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=probe)]
            )
            text = str(response.content or "").strip()
        finally:
            await llm.aclose()
        parsed = _extract_json(text)
        case = {
            "tier": "cross_provider_deepseek",
            "model": "deepseek-chat",
            "host": host,
            "credential_source": "environment:DEEPSEEK_API_KEY",
            "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "parsed_name": parsed.get("name"),
            "same_identity_after_model_swap": parsed.get(
                "same_identity_after_model_swap"
            ),
            "name_ok": _name_ok(parsed.get("name")),
            "continuity_ok": parsed.get("same_identity_after_model_swap") is True,
        }
        case["pass"] = case["name_ok"] and case["continuity_ok"]
        cases.append(case)

    distinct_models = len({str(c["model"]) for c in cases}) >= 2
    distinct_providers = len({str(c["host"]) for c in cases}) >= 2
    provider_requirement_ok = (
        distinct_providers if cross_provider_attempted else True
    )
    verdict = (
        "PASS"
        if distinct_models and provider_requirement_ok and all(c["pass"] for c in cases)
        else "FAIL"
    )
    result = {
        "schema_version": 1,
        "verdict": verdict,
        "neko_commit": args.neko_commit,
        "storage_root": str(args.storage_root.resolve()),
        "private_persona_sent_only_to_allowlisted_provider": True,
        "persona_text_recorded": False,
        "response_text_recorded": False,
        "distinct_models": distinct_models,
        "cross_provider_attempted": cross_provider_attempted,
        "distinct_providers": distinct_providers,
        "cases": cases,
        "caveat": (
            "Configured Qwen cases use N.E.K.O ConfigManager + PersonaManager + "
            "LLM client. The optional DeepSeek case reuses the same N.E.K.O "
            "PersonaManager prompt and LLM client with an owner-allowlisted direct "
            "endpoint and an existing environment credential; no secret is recorded."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if verdict == "PASS" else 8


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument(
        "--neko-commit",
        default="402695cd115323440dfd4e6860c25a32c10dda43",
    )
    ap.add_argument("--evidence", type=Path)
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())