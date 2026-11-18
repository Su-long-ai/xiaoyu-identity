from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SOURCE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_WORK = Path(r"D:\xiaoyu_private_overlay_state\scope-e2e")
DEFAULT_POLICY = OVERLAY_ROOT / "privacy" / "provider_policy.json"
PRIVATE_CANARY = "XIAOYU_SCOPE_PRIVATE_VIOLET_731"
GROUP_CANARY = "XIAOYU_SCOPE_GROUP_AMBER_284"
CHARACTER = "XiaoYu"


class _EmptyReflections:
    async def aupdate_suppressions(self, _name: str) -> None:
        return None

    async def aget_pending_reflections(self, _name: str, **_kwargs):
        return []

    async def aget_confirmed_reflections(self, _name: str, **_kwargs):
        return []


def _set_storage(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _extract_json(text: str) -> dict:
    raw = text.strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"{.*}", raw, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


async def _run(args: argparse.Namespace) -> int:
    if args.work_root.exists():
        shutil.rmtree(args.work_root)
    shutil.copytree(args.source_root, args.work_root)
    _set_storage(args.work_root)
    sys.path.insert(0, str(args.neko_root.resolve()))
    sys.path.insert(0, str((OVERLAY_ROOT / "tools").resolve()))

    result: dict = {
        "schema_version": 1,
        "neko_commit": args.neko_commit,
        "source_root": str(args.source_root.resolve()),
        "work_root": str(args.work_root.resolve()),
        "source_product_data_touched": False,
        "synthetic_canaries_only": True,
        "private_canary_text_recorded": False,
        "group_canary_text_recorded": False,
        "model_response_recorded": False,
        "native_regression_evidence": "evals/evidence/2026-11-18-neko-scope-qq-native.json",
    }

    try:
        from check_provider_privacy import host_is_allowed
        from memory.event_log import EventLog
        from memory.introspection import (
            arender_injected_memory,
            arender_scoped_injected_memory,
        )
        from memory.persona import PersonaManager
        from memory.scopes import MemorySubject
        from utils.config_manager import get_config_manager
        from utils.llm_client import HumanMessage, SystemMessage, create_chat_llm

        pm = PersonaManager(event_log=EventLog())
        group = MemorySubject.group_chat("qq", "xiaoyu-scope-e2e")

        private_add = await pm.aadd_fact(
            CHARACTER, PRIVATE_CANARY, entity="master", source="manual"
        )
        group_add = await pm.aadd_fact(
            CHARACTER, GROUP_CANARY, source="manual", subject=group
        )

        private_render = (
            await arender_injected_memory(
                pm,
                _EmptyReflections(),
                CHARACTER,
                pinned_fact_store=None,
                lang="zh",
            )
        ).text
        group_render = await arender_scoped_injected_memory(
            pm,
            _EmptyReflections(),
            CHARACTER,
            [group],
        )

        render_checks = {
            "private_render_has_private": PRIVATE_CANARY in private_render,
            "private_render_excludes_group": GROUP_CANARY not in private_render,
            "group_render_has_group": GROUP_CANARY in group_render,
            "group_render_excludes_private": PRIVATE_CANARY not in group_render,
        }
        result.update(
            {
                "private_add_result": private_add,
                "group_add_result": group_add,
                "private_render_sha256": hashlib.sha256(
                    private_render.encode("utf-8")
                ).hexdigest(),
                "group_render_sha256": hashlib.sha256(
                    group_render.encode("utf-8")
                ).hexdigest(),
                "render_checks": render_checks,
            }
        )

        if not all(render_checks.values()):
            result["verdict"] = "FAIL"
            result["reason"] = "scoped render isolation failed before model call"
            return 17

        policy = json.loads(args.policy.read_text(encoding="utf-8-sig"))
        cm = get_config_manager()
        cfg = cm.get_model_api_config("summary")
        host = (urlsplit(str(cfg.get("base_url") or "")).hostname or "").lower()
        allowed, reason = host_is_allowed(host, policy)
        if not allowed:
            raise RuntimeError(
                f"summary provider is not privacy-eligible: {host} ({reason})"
            )

        api_key = str(cfg.get("api_key") or "").strip()
        credential_source = "neko_config"
        if not api_key and (
            host == "dashscope.aliyuncs.com"
            or host.endswith(".dashscope.aliyuncs.com")
        ):
            api_key = str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()
            credential_source = "environment:DASHSCOPE_API_KEY"
        if not api_key:
            raise RuntimeError("summary provider has no available API key")

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
        prompt = (
            "The following is the only long-term context allowed for this QQ group. "
            "Answer only from this scoped context and do not infer private-chat memory.\n\n"
            + group_render
        )
        probe = (
            'Find the marker beginning with "XIAOYU_SCOPE_" in the context. '
            'Output exactly one JSON object and no Markdown: '
            '{"marker":"the exact marker you actually saw"}'
        )
        try:
            response = await llm.ainvoke(
                [SystemMessage(content=prompt), HumanMessage(content=probe)]
            )
            response_text = str(response.content or "").strip()
        finally:
            await llm.aclose()

        parsed = _extract_json(response_text)
        marker = str(parsed.get("marker") or "").strip()
        live_checks = {
            "model_returns_group_canary": marker == GROUP_CANARY,
            "model_does_not_return_private_canary": PRIVATE_CANARY not in response_text,
        }
        result.update(
            {
                "live_model": cfg.get("model"),
                "live_host": host,
                "credential_source": credential_source,
                "response_sha256": hashlib.sha256(
                    response_text.encode("utf-8")
                ).hexdigest(),
                "live_checks": live_checks,
            }
        )
        result["verdict"] = (
            "PASS"
            if all(render_checks.values()) and all(live_checks.values())
            else "FAIL"
        )
        return 0 if result["verdict"] == "PASS" else 18
    finally:
        logging.shutdown()
        if args.work_root.exists():
            shutil.rmtree(args.work_root)
        result["work_root_cleaned"] = not args.work_root.exists()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--work-root", type=Path, default=DEFAULT_WORK)
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
