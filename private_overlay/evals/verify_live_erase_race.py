from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import shutil
import sys
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SOURCE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_WORK = Path(r"D:\xiaoyu_private_overlay_state\erase-race-e2e")
CHARACTER = "XiaoYu"
CANARY = "XIAOYU_ERASE_RACE_CANARY_947"


def _set_storage(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _close_logging_handlers() -> None:
    loggers = [logging.getLogger()]
    loggers.extend(
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in loggers:
        for handler in list(logger.handlers):
            try:
                handler.flush()
            except Exception:
                pass
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)
    logging.shutdown()


class GatedExtractor:
    def __init__(self, response: list[dict], *, blocked: bool) -> None:
        self.response = response
        self.calls = 0
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()
        if not blocked:
            self.gate.set()

    async def __call__(self, _prompt, _lanlan_name, **_kwargs):
        self.calls += 1
        self.entered.set()
        await self.gate.wait()
        return copy.deepcopy(self.response)


def _history() -> str:
    return json.dumps(
        [{"role": "user", "content": CANARY}],
        ensure_ascii=False,
    )


async def _facts_for(runtime, subject):
    from memory.scopes import entry_matches_subject

    rows = await runtime.fact_store.aload_facts(CHARACTER)
    return [
        row for row in rows
        if isinstance(row, dict) and entry_matches_subject(row, subject)
    ]


def _request(routes, subject, key: str):
    subject_req = routes.MemorySubjectRequest(
        subject_kind=subject.kind,
        subject_id=subject.subject_id,
        scope=subject.scope,
    )
    return routes.ScopedHistoryRequest(
        input_history=_history(),
        subject=subject_req,
        display_name="XiaoYu erase-race probe",
        idempotency_key=key,
        subject_epochs={subject.key: 0},
    )


def _forget_request(routes, subject):
    return routes.ScopedForgetRequest(
        subject=routes.MemorySubjectRequest(
            subject_kind=subject.kind,
            subject_id=subject.subject_id,
            scope=subject.scope,
        )
    )


async def _case_generation_forget(routes, runtime, subject, key: str) -> dict:
    extractor = GatedExtractor(
        [{"text": CANARY, "importance": 8}],
        blocked=True,
    )
    original = runtime.fact_store._allm_call_with_retries
    runtime.fact_store._allm_call_with_retries = extractor
    try:
        task = asyncio.create_task(
            routes.process_scoped_history(CHARACTER, _request(routes, subject, key))
        )
        await asyncio.wait_for(extractor.entered.wait(), timeout=10)
        pre_release_facts = await _facts_for(runtime, subject)
        await routes.forget_scoped_subject(
            CHARACTER,
            _forget_request(routes, subject),
        )
        extractor.gate.set()
        result = await asyncio.wait_for(task, timeout=20)
        post_facts = await _facts_for(runtime, subject)
        return {
            "extractor_calls": extractor.calls,
            "forget_landed_while_generation_blocked": True,
            "pre_release_fact_count": len(pre_release_facts),
            "created": int(result.get("created", -1)),
            "post_fact_count": len(post_facts),
            "canary_persisted": any(CANARY in str(row.get("text") or "") for row in post_facts),
            "pass": (
                extractor.calls == 1
                and len(pre_release_facts) == 0
                and int(result.get("created", -1)) == 0
                and len(post_facts) == 0
            ),
        }
    finally:
        runtime.fact_store._allm_call_with_retries = original


async def _case_staging_recheck(routes, runtime, idempotency, subject, key: str) -> dict:
    extractor = GatedExtractor(
        [{"text": CANARY, "importance": 8}],
        blocked=False,
    )
    original_llm = runtime.fact_store._allm_call_with_retries
    original_write = idempotency.write_staging
    state = {"forget_triggered": False}

    async def forget_then_write(lanlan_name, incoming_key, document):
        if incoming_key == key and not state["forget_triggered"]:
            state["forget_triggered"] = True
            await routes.forget_scoped_subject(
                CHARACTER,
                _forget_request(routes, subject),
            )
        return await original_write(lanlan_name, incoming_key, document)

    runtime.fact_store._allm_call_with_retries = extractor
    idempotency.write_staging = forget_then_write
    try:
        result = await routes.process_scoped_history(
            CHARACTER,
            _request(routes, subject, key),
        )
        post_facts = await _facts_for(runtime, subject)
        record = await idempotency.read_key(CHARACTER, key)
        staging = await idempotency.read_staging(CHARACTER, key)
        staging_contains_canary = CANARY in json.dumps(
            staging or {}, ensure_ascii=False, sort_keys=True
        )
        return {
            "extractor_calls": extractor.calls,
            "forget_triggered_inside_staging_write": state["forget_triggered"],
            "created": int(result.get("created", -1)),
            "post_fact_count": len(post_facts),
            "key_state": (record or {}).get("state"),
            "staging_contains_canary": staging_contains_canary,
            "canary_persisted": any(CANARY in str(row.get("text") or "") for row in post_facts),
            "pass": (
                extractor.calls == 1
                and state["forget_triggered"]
                and int(result.get("created", -1)) == 0
                and len(post_facts) == 0
                and not staging_contains_canary
            ),
        }
    finally:
        idempotency.write_staging = original_write
        runtime.fact_store._allm_call_with_retries = original_llm


async def _run(args: argparse.Namespace) -> int:
    if args.work_root.exists():
        shutil.rmtree(args.work_root)
    shutil.copytree(args.source_root, args.work_root)
    _set_storage(args.work_root)
    sys.path.insert(0, str(args.neko_root.resolve()))

    from app.memory_server import idempotency, routes, runtime
    from memory.scopes import MemorySubject

    result = {
        "schema_version": 1,
        "neko_commit": args.neko_commit,
        "source_root": str(args.source_root.resolve()),
        "work_root": str(args.work_root.resolve()),
        "source_product_data_touched": False,
        "synthetic_canary_only": True,
        "canary_text_recorded": False,
        "official_history_route": "/internal/memory/{lanlan_name}/scoped_history",
        "official_forget_route": "/internal/memory/{lanlan_name}/scoped_forget",
        "verdict": "FAIL",
    }

    try:
        await runtime.ensure_memory_server_runtime_initialized(
            reason="xiaoyu-live-erase-race"
        )

        case_a_subject = MemorySubject.group_chat("qq", "xiaoyu-erase-race-a")
        case_b_subject = MemorySubject.group_chat("qq", "xiaoyu-erase-race-b")

        case_a = await _case_generation_forget(
            routes,
            runtime,
            case_a_subject,
            "xiaoyu-erase-race-generation-v1",
        )
        case_b = await _case_staging_recheck(
            routes,
            runtime,
            idempotency,
            case_b_subject,
            "xiaoyu-erase-race-staging-v1",
        )

        result["generation_window"] = case_a
        result["staging_recheck_window"] = case_b
        result["pass"] = bool(case_a["pass"] and case_b["pass"])
        result["verdict"] = "PASS" if result["pass"] else "FAIL"
        return 0 if result["pass"] else 41
    finally:
        try:
            await runtime.shutdown_memory_server()
        except Exception:
            pass
        _close_logging_handlers()
        await asyncio.sleep(0.1)
        if args.work_root.exists():
            try:
                shutil.rmtree(args.work_root)
            except PermissionError:
                result["cleanup_deferred_due_to_open_log"] = True
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
    ap.add_argument("--evidence", type=Path)
    ap.add_argument(
        "--neko-commit",
        default="7b776173e758401a3819e3ad3d4179e86e23eb0e",
    )
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
