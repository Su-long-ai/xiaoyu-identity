# -*- coding: utf-8 -*-
"""Synthetic cross-model behavioral continuity shadow for XiaoYu.

Product shadow only, not a formal benchmark or E2 claim.
- creates a disposable synthetic identity;
- uses the real IdentityStore + ProductMemoryBridge to construct current context;
- sends the exact same current identity context to DeepSeek Flash and Qwen3.8-Flash;
- checks only stable identity/current-state behavior, not wording similarity;
- never reads the real identity/ directory and never persists API keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from model_adapter import project_history


def _user_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
        except OSError:
            return ""
    return ""


def _post_json(url: str, api_key: str, body: dict, timeout: int) -> tuple[dict, float]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000).decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP_{exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("NETWORK_ERROR") from None
    except TimeoutError:
        raise RuntimeError("TIMEOUT") from None
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return json.loads(raw), elapsed_ms


def _extract_json(text: str) -> dict:
    text = str(text or "").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("NO_JSON_OBJECT")
    obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise ValueError("JSON_NOT_OBJECT")
    return obj


def _provider_call(provider: str, system_context: str, history: list[dict], timeout: int) -> dict:
    user_prompt = (
        "只根据 system 中的身份档案和【经确认的长期记忆】回答。"
        "不要使用被更正的旧状态，不要把缺失/已撤回的事实猜成 yes 或 no。"
        "只输出一个 JSON 对象，不要解释，不要 Markdown。字段必须是："
        '{"assistant_name":"身份档案中的name原值",'
        '"user_city":"城市名或unknown",'
        '"shoe_low_profile":true或false或"unknown",'
        '"shoe_quiet":true或false或"unknown",'
        '"mint_tea":"yes|no|unknown"}。'
    )
    messages = [{"role": "system", "content": system_context}]
    messages.extend({"role":x["role"],"content":x["content"]} for x in history)
    messages.append({"role": "user", "content": user_prompt})

    if provider == "deepseek":
        key = _user_env("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY_MISSING")
        url = "https://api.deepseek.com/chat/completions"
        body = {
            "model": "deepseek-flash",
            "messages": messages,
            "temperature": 0,
            "max_tokens": 256,
            "stream": False,
        }
    elif provider == "qwen":
        key = _user_env("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("DASHSCOPE_API_KEY_MISSING")
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        body = {
            "model": "qwen3.8-flash",
            "messages": messages,
            "temperature": 0,
            "max_tokens": 256,
            "stream": False,
            "enable_thinking": False,
        }
    else:
        raise ValueError(provider)

    response, elapsed_ms = _post_json(url, key, body, timeout)
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("NO_CHOICES")
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    parsed = _extract_json(content)
    usage = response.get("usage") or {}
    return {
        "provider": provider,
        "model": str(response.get("model") or body["model"]),
        "latency_ms": round(elapsed_ms, 2),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "parsed": parsed,
    }


def _evaluate(parsed: dict, assistant_name: str) -> dict:
    return {
        "assistant_name_preserved": parsed.get("assistant_name") == assistant_name,
        "corrected_city_used": parsed.get("user_city") == "上海",
        "low_profile_preference_used": parsed.get("shoe_low_profile") is True,
        "quiet_preference_used": parsed.get("shoe_quiet") is True,
        "retracted_mint_tea_not_inferred": parsed.get("mint_tea") == "unknown",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=75)
    ap.add_argument("--trials", type=int, default=1)
    args = ap.parse_args()
    trials=max(1,int(args.trials))

    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        store = IdentityStore(home)
        mixed_event=store.record(
            "conversation.user","user",
            "用户当前居住城市是苏州，而且用户偏好低重心、走路安静的鞋"
        )
        old_city = store.add_memory(
            "用户当前居住城市是苏州", category="shared", priority=5, source_event=mixed_event
        )
        store.add_memory(
            "用户偏好低重心、走路安静的鞋", category="preference", priority=5, source_event=mixed_event
        )
        active_event=store.record("conversation.user","user","用户周末喜欢散步")
        store.add_memory(
            "用户周末喜欢散步", category="preference", priority=3, source_event=active_event
        )
        mint_event=store.record("conversation.user","user","用户喜欢薄荷茶")
        mint = store.add_memory(
            "用户喜欢薄荷茶", category="preference", priority=4, source_event=mint_event
        )
        store.correct_memory(old_city, "用户当前居住城市是上海")
        store.retract_memory(mint)

        bridge = ProductMemoryBridge(home, store, component_root=ROOT)
        try:
            query = "身份 名字 当前居住城市 鞋子偏好 低重心 安静 薄荷茶"
            memories = bridge.recall(query, limit=7)
            context = store.identity_context(query, memories_override=memories)
            persona_name = str(store.persona().get("name") or "")
            active_texts = [str(x.get("text") or "") for x in memories]
            history=project_history(store,16)
            history_by_id={int(x["event_id"]):x for x in history if x.get("event_id") is not None}
            local_contract = {
                "old_city_absent": all("苏州" not in x for x in active_texts),
                "current_city_present": any("上海" in x for x in active_texts),
                "shoe_preference_present": any("低重心" in x and "安静" in x for x in active_texts),
                "retracted_mint_absent": all("薄荷茶" not in x for x in active_texts),
                "mixed_source_recent_dialog_annotated": (
                    history_by_id.get(mixed_event,{}).get("memory_state_annotation")=="mixed_changed"
                    and "部分长期事实后来已被更正" in history_by_id.get(mixed_event,{}).get("content","")
                ),
                "retracted_recent_dialog_annotated": (
                    history_by_id.get(mint_event,{}).get("memory_state_annotation")=="retracted"
                    and "已被用户撤回" in history_by_id.get(mint_event,{}).get("content","")
                ),
                "active_recent_dialog_unmodified": (
                    history_by_id.get(active_event,{}).get("content")=="用户周末喜欢散步"
                    and "memory_state_annotation" not in history_by_id.get(active_event,{})
                ),
            }

            providers = {}
            semantic_keys=("assistant_name","user_city","shoe_low_profile","shoe_quiet","mint_tea")
            all_semantic=[]
            for provider in ("deepseek", "qwen"):
                trial_rows=[]
                for trial_index in range(trials):
                    try:
                        out = _provider_call(provider, context, history, args.timeout)
                        checks = _evaluate(out["parsed"], persona_name)
                        out["trial"]=trial_index+1
                        out["checks"] = checks
                        out["pass"] = all(checks.values())
                    except Exception as exc:
                        out = {
                            "provider": provider,
                            "trial": trial_index+1,
                            "pass": False,
                            "error": type(exc).__name__ + ":" + str(exc),
                        }
                    trial_rows.append(out)
                parsed_rows=[x.get("parsed") for x in trial_rows if x.get("pass") is True]
                semantic_rows=[
                    tuple(x.get(k) for k in semantic_keys)
                    for x in parsed_rows
                ]
                consistent=bool(semantic_rows) and len(set(semantic_rows))==1
                provider_pass=len(trial_rows)==trials and all(x.get("pass") is True for x in trial_rows) and consistent
                providers[provider]={
                    "provider":provider,
                    "trials":trial_rows,
                    "consistent_across_trials":consistent,
                    "pass":provider_pass,
                }
                all_semantic.extend(semantic_rows)

            both_pass = all(x.get("pass") is True for x in providers.values())
            semantic_agreement = both_pass and len(set(all_semantic))==1

            result = {
                "schema": "xiaoyu-cross-model-behavior-shadow-v2",
                "data": "synthetic_disposable_only",
                "private_identity_read": False,
                "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
                "trials_per_provider": trials,
                "identity_id_exposed_to_output": False,
                "local_contract": local_contract,
                "providers": providers,
                "cross_model_semantic_agreement": semantic_agreement,
                "pass": all(local_contract.values()) and both_pass and semantic_agreement,
                "formal_claim": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result["pass"] else 2)
        finally:
            bridge.close()
            store.close()


if __name__ == "__main__":
    main()
