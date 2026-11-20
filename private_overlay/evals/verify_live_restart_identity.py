from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_STORAGE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_POLICY = OVERLAY_ROOT / "privacy" / "provider_policy.json"


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


def _digest(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _extract_json(text: str) -> dict:
    raw = text.strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(raw[start:end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


async def _child(args: argparse.Namespace) -> int:
    _set_storage(args.storage_root)
    sys.path.insert(0, str(args.neko_root.resolve()))
    sys.path.insert(0, str((OVERLAY_ROOT / "tools").resolve()))

    from check_provider_privacy import host_is_allowed
    from memory.event_log import EventLog
    from memory.introspection import arender_injected_memory
    from memory.persona import PersonaManager
    from utils.config_manager import get_config_manager
    from utils.llm_client import HumanMessage, SystemMessage, create_chat_llm

    cm = get_config_manager()
    character_data = cm.get_character_data()
    active_character = str(character_data[1] or "")
    if active_character != "XiaoYu":
        raise RuntimeError(f"active character is not XiaoYu: {active_character!r}")

    pm = PersonaManager(event_log=EventLog())
    persona = pm.get_persona(active_character)
    persona_sha = _digest(persona)
    injected = await arender_injected_memory(
        pm, _EmptyReflections(), active_character, pinned_fact_store=None, lang="zh"
    )
    memory_text = injected.text
    if not memory_text.strip():
        raise RuntimeError("injected XiaoYu memory is empty")

    policy = json.loads(args.policy.read_text(encoding="utf-8-sig"))
    cfg = cm.get_model_api_config("summary")
    host = (urlsplit(str(cfg.get("base_url") or "")).hostname or "").lower()
    allowed, reason = host_is_allowed(host, policy)
    if not allowed:
        raise RuntimeError(f"summary provider not privacy-eligible: {host} ({reason})")

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
        max_completion_tokens=48,
        timeout=60.0,
    )
    try:
        response = await llm.ainvoke([
            SystemMessage(content=memory_text),
            HumanMessage(
                content='只输出严格 JSON：{"name":"当前角色名","continuing_identity":true}'
            ),
        ])
        response_text = str(response.content or "").strip()
    finally:
        await llm.aclose()

    parsed = _extract_json(response_text)
    normalized = str(parsed.get("name") or "").strip().casefold()
    ok = normalized in {"xiaoyu", "小鱼"} and parsed.get("continuing_identity") is True
    row = {
        "fresh_process_pid": os.getpid(),
        "character": active_character,
        "persona_sha256": persona_sha,
        "model": cfg.get("model"),
        "host": host,
        "credential_source": credential_source,
        "name": parsed.get("name"),
        "continuing_identity": parsed.get("continuing_identity"),
        "response_sha256": hashlib.sha256(
            response_text.encode("utf-8")
        ).hexdigest(),
        "pass": ok,
        "persona_text_recorded": False,
        "response_text_recorded": False,
    }
    args.child_output.write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if ok else 11


def _parent(args: argparse.Namespace) -> int:
    rows = []
    with tempfile.TemporaryDirectory(prefix="xiaoyu-restart-e2e-") as tmp:
        tmp_root = Path(tmp)
        for idx in range(2):
            output = tmp_root / f"child-{idx}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                "--neko-root", str(args.neko_root),
                "--storage-root", str(args.storage_root),
                "--policy", str(args.policy),
                "--child-output", str(output),
            ]
            cp = subprocess.run(
                command,
                cwd=str(args.neko_root),
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            if cp.returncode != 0:
                raise RuntimeError(
                    f"fresh process {idx} failed rc={cp.returncode}: {cp.stderr[-2000:]}"
                )
            rows.append(json.loads(output.read_text(encoding="utf-8")))

    distinct_processes = len({row["fresh_process_pid"] for row in rows}) == 2
    same_persona = len({row["persona_sha256"] for row in rows}) == 1
    same_character = len({row["character"] for row in rows}) == 1
    both_live_pass = all(row["pass"] for row in rows)
    verdict = (
        "PASS"
        if distinct_processes and same_persona and same_character and both_live_pass
        else "FAIL"
    )
    result = {
        "schema_version": 1,
        "verdict": verdict,
        "neko_commit": args.neko_commit,
        "storage_root": str(args.storage_root.resolve()),
        "fresh_processes": 2,
        "distinct_processes": distinct_processes,
        "same_persona_digest_across_restart": same_persona,
        "same_character_across_restart": same_character,
        "both_live_behavior_probes_pass": both_live_pass,
        "cases": rows,
        "product_data_touched": False,
        "caveat": (
            "Each case is a separate fresh Python/N.E.K.O process reading the same "
            "isolated XiaoYu authority and making a real allowlisted model call. "
            "This proves runtime-process restart continuity; desktop GUI restart "
            "remains part of final integrated product smoke."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if verdict == "PASS" else 12


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neko-root", type=Path, default=DEFAULT_NEKO)
    ap.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument(
        "--neko-commit",
        default="6261a5f653af066d2a7da8e265f624e3df03e3f7",
    )
    ap.add_argument("--evidence", type=Path)
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--child-output", type=Path)
    args = ap.parse_args()
    if args.child and args.child_output is None:
        ap.error("--child requires --child-output")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_child(args)) if args.child else _parent(args)


if __name__ == "__main__":
    raise SystemExit(main())