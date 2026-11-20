from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_SOURCE = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_WORK = Path(r"D:\xiaoyu_private_overlay_state\erasure-e2e")
CHARACTER = "XiaoYu"
SUBJECT_ID = "xiaoyu-erasure-e2e"
CANARY = "XIAOYU_ERASURE_CANARY_641"
REFLECTION_ID = "xiaoyu-erasure-reflection-641"


def _set_storage(root: Path) -> None:
    root = root.resolve()
    os.environ["NEKO_STORAGE_SELECTED_ROOT"] = str(root)
    os.environ["NEKO_STORAGE_ANCHOR_ROOT"] = str(root)
    os.environ["NEKO_RUNTIME_STATE_DIR"] = str(root / ".runtime")


def _contains(value: object, needle: str = CANARY) -> bool:
    return needle in json.dumps(value, ensure_ascii=False, sort_keys=True)


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


async def _snapshot(runtime, subject) -> dict:
    from memory.introspection import arender_scoped_injected_memory

    facts = await runtime.fact_store.aload_facts(CHARACTER)
    reflections = await runtime.reflection_engine._aload_reflections_full(CHARACTER)
    persona = await runtime.persona_manager.aensure_persona(CHARACTER)
    rendered = await arender_scoped_injected_memory(
        runtime.persona_manager,
        runtime.reflection_engine,
        CHARACTER,
        [subject],
    )
    return {
        "fact_has_canary": _contains(facts),
        "reflection_has_canary": _contains(reflections),
        "persona_has_canary": _contains(persona),
        "render_has_canary": CANARY in rendered,
    }


async def _verify_fresh_process(args: argparse.Namespace) -> int:
    _set_storage(args.work_root)
    sys.path.insert(0, str(args.neko_root.resolve()))

    from app.memory_server import routes, runtime
    from memory.scopes import MemorySubject
    from memory.subject_archive import arestore_scoped_subject

    subject = MemorySubject.group_chat("qq", SUBJECT_ID)
    result: dict = {
        "mode": "fresh_process_verify",
        "restored_after_restart": None,
        "forget_epoch_after_restart": None,
        "canary_visible_after_restart": None,
        "pass": False,
    }
    try:
        await runtime.ensure_memory_server_runtime_initialized(
            reason="xiaoyu-erasure-e2e-restart"
        )
        restore = await arestore_scoped_subject(
            CHARACTER,
            subject,
            fact_store=runtime.fact_store,
            persona_manager=runtime.persona_manager,
            reflection_engine=runtime.reflection_engine,
        )
        epoch_doc = await routes.get_forget_epochs(CHARACTER, subject=[subject.key])
        snap = await _snapshot(runtime, subject)
        result.update(
            {
                "restored_after_restart": restore,
                "forget_epoch_after_restart": (epoch_doc.get("epochs") or {}).get(subject.key),
                "canary_visible_after_restart": any(snap.values()),
                "snapshot": snap,
            }
        )
        result["pass"] = (
            restore.get("facts", 0) == 0
            and restore.get("reflections", 0) == 0
            and restore.get("persona_entries", 0) == 0
            and isinstance(result["forget_epoch_after_restart"], int)
            and result["forget_epoch_after_restart"] >= 1
            and not result["canary_visible_after_restart"]
        )
        return 0 if result["pass"] else 31
    finally:
        try:
            await runtime.shutdown_memory_server()
        except Exception:
            pass
        _close_logging_handlers()
        if args.child_output:
            args.child_output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


async def _run(args: argparse.Namespace) -> int:
    if args.work_root.exists():
        shutil.rmtree(args.work_root)
    shutil.copytree(args.source_root, args.work_root)
    _set_storage(args.work_root)
    sys.path.insert(0, str(args.neko_root.resolve()))

    from app.memory_server import routes, runtime
    from memory.scopes import MemorySubject
    from memory.subject_archive import arestore_scoped_subject

    subject = MemorySubject.group_chat("qq", SUBJECT_ID)
    result: dict = {
        "schema_version": 1,
        "neko_commit": args.neko_commit,
        "source_root": str(args.source_root.resolve()),
        "work_root": str(args.work_root.resolve()),
        "source_product_data_touched": False,
        "synthetic_canary_only": True,
        "canary_text_recorded_in_evidence": False,
        "official_forget_route": "/internal/memory/{lanlan_name}/scoped_forget",
        "verdict": "FAIL",
    }

    try:
        await runtime.ensure_memory_server_runtime_initialized(
            reason="xiaoyu-erasure-e2e"
        )

        subject_req = routes.MemorySubjectRequest(
            subject_kind=subject.kind,
            subject_id=subject.subject_id,
            scope=subject.scope,
        )
        fact_req = routes.ScopedFactsWriteRequest(
            subject=subject_req,
            facts=[
                routes.ScopedFactInput(
                    text=CANARY,
                    importance=8,
                    source="user_observation",
                )
            ],
            display_name="XiaoYu erasure E2E",
        )
        await routes.append_scoped_facts(CHARACTER, fact_req)

        persona_add = await runtime.persona_manager.aadd_fact(
            CHARACTER,
            CANARY,
            source="manual",
            subject=subject,
        )
        persona = await runtime.persona_manager.aensure_persona(CHARACTER)
        section = persona.get(subject.persona_section_key, {})
        persona_entries = [
            item
            for item in section.get("facts", [])
            if isinstance(item, dict) and str(item.get("text") or "") == CANARY
        ]
        if not persona_entries:
            raise RuntimeError("failed to locate seeded scoped persona entry")
        persona_id = str(persona_entries[-1].get("id") or "")
        if not persona_id:
            raise RuntimeError("seeded scoped persona entry has no id")

        now = datetime.now()
        reflections = await runtime.reflection_engine._aload_reflections_full(CHARACTER)
        reflection = {
            "id": REFLECTION_ID,
            "text": CANARY,
            "entity": subject.kind,
            "status": "confirmed",
            "confirmed_at": now.isoformat(),
            "auto_confirmed": True,
            "source_fact_ids": [],
            "created_at": now.isoformat(),
            "reinforcement": 0.1,
            "rein_last_signal_at": now.isoformat(),
            **subject.as_entry_fields(),
        }
        reflections = [
            row for row in reflections
            if not (isinstance(row, dict) and row.get("id") == REFLECTION_ID)
        ]
        await runtime.reflection_engine.asave_reflections(
            CHARACTER, reflections + [reflection]
        )

        seeded = await _snapshot(runtime, subject)
        if not (
            seeded["fact_has_canary"]
            and seeded["reflection_has_canary"]
            and seeded["persona_has_canary"]
            and seeded["render_has_canary"]
        ):
            raise RuntimeError(f"seed snapshot incomplete: {seeded}")

        archived_at = now.isoformat()
        cutoff = now + timedelta(days=1)
        archived_facts = await runtime.fact_store.aarchive_subject_facts(
            CHARACTER, subject, archived_at, cutoff
        )
        archived_reflection = await runtime.reflection_engine.aarchive_reflection(
            CHARACTER, REFLECTION_ID
        )
        archived_persona = await runtime.persona_manager.aarchive_persona_entry(
            CHARACTER, subject.persona_section_key, persona_id
        )
        restore_before_forget = await arestore_scoped_subject(
            CHARACTER,
            subject,
            fact_store=runtime.fact_store,
            persona_manager=runtime.persona_manager,
            reflection_engine=runtime.reflection_engine,
        )
        restored_snapshot = await _snapshot(runtime, subject)

        archive_roundtrip_ok = (
            bool(archived_reflection)
            and bool(archived_persona)
            and restore_before_forget.get("reflections", 0) >= 1
            and restore_before_forget.get("persona_entries", 0) >= 1
            and all(restored_snapshot.values())
        )

        forget_req = routes.ScopedForgetRequest(
            subject=subject_req,
            forget_epoch=1,
        )
        forget_response = await routes.forget_scoped_subject(CHARACTER, forget_req)
        epoch_doc = await routes.get_forget_epochs(CHARACTER, subject=[subject.key])
        post_forget_snapshot = await _snapshot(runtime, subject)

        restore_after_forget = await arestore_scoped_subject(
            CHARACTER,
            subject,
            fact_store=runtime.fact_store,
            persona_manager=runtime.persona_manager,
            reflection_engine=runtime.reflection_engine,
        )
        post_restore_snapshot = await _snapshot(runtime, subject)
        epoch = (epoch_doc.get("epochs") or {}).get(subject.key)

        result.update(
            {
                "persona_add_result": persona_add,
                "archive_roundtrip": {
                    "facts_archived": archived_facts,
                    "fact_archive_required_for_this_probe": False,
                    "fact_active_seeded": seeded["fact_has_canary"],
                    "reflection_archived": bool(archived_reflection),
                    "persona_archived": bool(archived_persona),
                    "restore_before_forget": restore_before_forget,
                    "pre_forget_restore_visible": all(restored_snapshot.values()),
                    "native_cold_store_evidence": "evals/evidence/2026-11-18-neko-erasure-native.json",
                    "pass": archive_roundtrip_ok,
                },
                "forget_receipt_present": forget_response is not None,
                "forget_epoch": epoch,
                "post_forget": {
                    "canary_visible": any(post_forget_snapshot.values()),
                    "snapshot": post_forget_snapshot,
                },
                "restore_after_forget": restore_after_forget,
                "post_restore": {
                    "canary_visible": any(post_restore_snapshot.values()),
                    "snapshot": post_restore_snapshot,
                },
            }
        )

        same_process_ok = (
            archive_roundtrip_ok
            and isinstance(epoch, int)
            and epoch >= 1
            and not any(post_forget_snapshot.values())
            and restore_after_forget.get("facts", 0) == 0
            and restore_after_forget.get("reflections", 0) == 0
            and restore_after_forget.get("persona_entries", 0) == 0
            and not any(post_restore_snapshot.values())
        )
        result["same_process_pass"] = same_process_ok

        await runtime.shutdown_memory_server()

        child_output = args.work_root / "fresh_process_erasure_verify.json"
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--verify-only",
                "--neko-root",
                str(args.neko_root),
                "--work-root",
                str(args.work_root),
                "--child-output",
                str(child_output),
                "--neko-commit",
                args.neko_commit,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        child_doc = (
            json.loads(child_output.read_text(encoding="utf-8"))
            if child_output.exists()
            else {}
        )
        result["fresh_process"] = {
            "exit_code": child.returncode,
            "pass": bool(child_doc.get("pass")),
            "forget_epoch_after_restart": child_doc.get("forget_epoch_after_restart"),
            "restored_after_restart": child_doc.get("restored_after_restart"),
            "canary_visible_after_restart": child_doc.get("canary_visible_after_restart"),
        }
        result["verdict"] = (
            "PASS"
            if same_process_ok and child.returncode == 0 and child_doc.get("pass")
            else "FAIL"
        )
        return 0 if result["verdict"] == "PASS" else 32
    finally:
        try:
            from app.memory_server import runtime as _runtime

            await _runtime.shutdown_memory_server()
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
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--child-output", type=Path)
    ap.add_argument("--evidence", type=Path)
    ap.add_argument(
        "--neko-commit",
        default="6261a5f653af066d2a7da8e265f624e3df03e3f7",
    )
    args = ap.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.verify_only:
        return asyncio.run(_verify_fresh_process(args))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
