"""Isolated paid probe for recent-activity tool selection.

Does not touch XiaoYu chat history or memory. Uses the configured N.E.K.O
conversation provider directly, then records provider-reported usage into the
native token tracker under call_type=acceptance_probe.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Keep this one-off acceptance probe out of N.E.K.O remote telemetry while still
# persisting its provider-reported token usage into the local native ledger.
os.environ.setdefault("NEKO_DO_NOT_TRACK", "1")

DEFAULT_STORAGE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_NEKO_ROOT = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
PLUGIN_SOURCE = Path(__file__).resolve().parents[1] / "plugins" / "xiaoyu_interaction_policy" / "__init__.py"
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "evidence"
    / "2026-11-20-recent-activity-tool-selection-probe.json"
)

STATIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Recall durable conversational memories, personal facts, preferences, "
                "commitments, and prior conversation information about the owner."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_current_screen",
            "description": (
                "Inspect the owner's current screen only. It cannot establish what "
                "the owner was doing minutes or hours ago."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def build_tools(neko_root: Path) -> list[dict]:
    root = str(neko_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    from plugin.sdk.plugin.llm_tool import LLM_TOOL_META_ATTR

    spec = importlib.util.spec_from_file_location("xiaoyu_probe_plugin", PLUGIN_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load XiaoYu interaction plugin source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    method = module.XiaoYuInteractionPolicyPlugin.xiaoyu_recent_activity
    meta = getattr(method, LLM_TOOL_META_ATTR)
    recent = {
        "type": "function",
        "function": {
            "name": meta.name,
            "description": meta.description,
            "parameters": meta.parameters,
        },
    }
    return [recent, *STATIC_TOOLS]


CASES = [
    {
        "id": "hour_retrospective",
        "prompt": "我刚才一个小时主要在电脑上干嘛？不要猜，如果需要查证就用工具。",
        "expect": "xiaoyu_recent_activity",
    },
    {
        "id": "anti_false_inactivity",
        "prompt": "我刚刚这段时间在电脑上是不是一直没干事？请按你真正有的证据回答。",
        "expect": "xiaoyu_recent_activity",
    },
    {
        "id": "game_or_code",
        "prompt": "我刚才是在写代码还是打游戏？你能查一下吗？",
        "expect": "xiaoyu_recent_activity",
    },
    {
        "id": "memory_negative_control",
        "prompt": "你记得我长期更偏好的求职城市是什么吗？",
        "expect_not": "xiaoyu_recent_activity",
    },
]


def cached_tokens(usage) -> int:
    details = getattr(usage, "prompt_tokens_details", None)
    value = getattr(details, "cached_tokens", 0) if details is not None else 0
    return int(value or 0)


async def run_probe(storage_root: Path, output: Path, neko_root: Path, *, case_id: str | None = None, force_recent_activity: bool = False) -> dict:
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(storage_root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(storage_root)

    tools = build_tools(neko_root)

    import httpx
    from openai import AsyncOpenAI
    from utils.config_manager import get_config_manager
    from utils.token_tracker import TokenTracker

    cfg = await get_config_manager().aget_model_api_config("conversation")
    model = str(cfg.get("model") or "").strip()
    api_key = str(cfg.get("api_key") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    if not model or not api_key or not base_url:
        raise RuntimeError("conversation provider is incomplete")
    if "qwen3.8" not in model.lower():
        raise RuntimeError(f"probe is frozen for the current qwen3.8 product binding, got {model!r}")

    tracker = TokenTracker.get_instance()
    results = []
    total_pt = total_ct = total_tt = total_cached = 0

    http = httpx.AsyncClient(trust_env=False, timeout=30.0)
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        max_retries=0,
        http_client=http,
    )
    try:
        selected_cases = [case for case in CASES if case_id is None or case["id"] == case_id]
        if not selected_cases:
            raise RuntimeError(f"unknown case id: {case_id}")
        for case in selected_cases:
            request_kwargs = {}
            if force_recent_activity:
                request_kwargs["tool_choice"] = {
                    "type": "function",
                    "function": {"name": "xiaoyu_recent_activity"},
                }
                request_kwargs["reasoning_effort"] = "none"
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are XiaoYu. Use available tools when factual evidence "
                            "is needed. Never invent unseen owner activity or missing evidence."
                        ),
                    },
                    {"role": "user", "content": case["prompt"]},
                ],
                tools=tools,
                tool_choice=request_kwargs.get("tool_choice", "auto"),
                reasoning_effort=request_kwargs.get("reasoning_effort"),
                temperature=0,
                max_completion_tokens=96,
            )
            message = response.choices[0].message
            calls = [
                {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in (message.tool_calls or [])
            ]
            names = [item["name"] for item in calls]
            expected = case.get("expect")
            forbidden = case.get("expect_not")
            passed = (expected in names if expected else True) and (
                forbidden not in names if forbidden else True
            )

            usage = response.usage
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            tt = int(getattr(usage, "total_tokens", 0) or pt + ct)
            cch = cached_tokens(usage)
            total_pt += pt
            total_ct += ct
            total_tt += tt
            total_cached += cch
            tracker.record(
                model=model,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=tt,
                cached_tokens=cch,
                call_type="acceptance_probe",
                source="recent_activity_tool_selection",
                success=True,
            )
            results.append(
                {
                    "id": case["id"],
                    "expected": expected,
                    "expected_not": forbidden,
                    "selected_tools": names,
                    "pass": passed,
                    "usage": {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": tt,
                        "cached_tokens": cch,
                    },
                }
            )
    finally:
        await client.close()

    tracker.save(report_timeout=0.01)

    evidence = {
        "schema_version": 1,
        "observed_at_local": datetime.now().astimezone().isoformat(),
        "isolation": {
            "chat_history_written": False,
            "memory_written": False,
            "provider_credentials_persisted": False,
            "native_usage_ledger_recorded": True,
            "remote_neko_telemetry_for_probe": False,
        },
        "model": model,
        "tool_choice": "forced:xiaoyu_recent_activity" if force_recent_activity else "auto",
        "case_filter": case_id,
        "cases": results,
        "summary": {
            "passed": sum(1 for item in results if item["pass"]),
            "total": len(results),
            "all_pass": all(item["pass"] for item in results),
            "provider_usage": {
                "prompt_tokens": total_pt,
                "completion_tokens": total_ct,
                "total_tokens": total_tt,
                "cached_tokens": total_cached,
            },
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, output)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    parser.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--case-id")
    parser.add_argument("--force-recent-activity", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        print(json.dumps({
            "execute": False,
            "cases": len(CASES),
            "max_completion_tokens_per_case": 96,
            "history_or_memory_write": False,
            "usage_ledger": "native N.E.K.O token tracker",
        }, ensure_ascii=False))
        return 0

    result = asyncio.run(run_probe(
        args.storage_root,
        args.output,
        args.neko_root,
        case_id=args.case_id,
        force_recent_activity=args.force_recent_activity,
    ))
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
