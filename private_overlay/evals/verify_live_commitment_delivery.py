from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_NEKO = Path(r"D:\xiaoyu_external_audit\N.E.K.O")
DEFAULT_WORK = Path(r"D:\xiaoyu_private_overlay_state\commitment-live-e2e")
DEFAULT_NAPCAT_CONFIG = Path(
    r"C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\config"
)
CHARACTER = "XiaoYu"
TEXT = "SYNTHETIC_XIAOYU_COMMITMENT_LIVE_DELIVERY_PROBE"


def _set_storage(root: Path) -> None:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
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


def _store(root: Path, neko_root: Path):
    _set_storage(root)
    sys.path.insert(0, str(neko_root.resolve()))
    from memory.pinned_facts import PinnedFactStore
    return PinnedFactStore()


def _extract_raw_message(sent: dict) -> str:
    raw = sent.get("raw_message") or sent.get("message") or ""
    if isinstance(raw, list):
        raw = json.dumps(raw, ensure_ascii=False)
    return str(raw)


def _verify_after(args: argparse.Namespace) -> int:
    store = _store(args.work_root, args.neko_root)
    due = store.get_due_commitment(CHARACTER, now=args.now)
    result = {
        "mode": "fresh_process_verify",
        "due_after_surface": due is not None,
        "pass": due is None,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["pass"] else 51


async def _run(args: argparse.Namespace) -> int:
    if args.work_root.exists():
        shutil.rmtree(args.work_root)
    args.work_root.mkdir(parents=True, exist_ok=True)

    store = _store(args.work_root, args.neko_root)
    eval_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(eval_dir))
    from verify_live_qq_connector import _load_napcat_server, _wait_connected

    from main_logic.topic.hooks import build_topic_hook_prompt
    from plugin.plugins.qq_auto_reply import connector_seam

    now = time.time()
    candidate = {
        "text": TEXT,
        "entity": "neko",
        "ttl_days": 3,
        "kind": "commitment",
        "due_at": now + 300,
    }
    counts = store.apply_decisions(
        CHARACTER,
        [candidate],
        [("add", None)],
        now=now,
    )
    due = store.get_due_commitment(CHARACTER, now=now)
    if not due:
        raise RuntimeError("seeded commitment was not due-soon")

    commitment = {
        "id": due["id"],
        "text": due["text"],
        "due": "soon",
    }
    cue = build_topic_hook_prompt("zh", commitment=commitment)
    cue_contains_commitment = TEXT in cue
    cue_sha256 = hashlib.sha256(cue.encode("utf-8")).hexdigest()

    onebot_url, token, expected_account = _load_napcat_server(args.napcat_config)
    client = connector_seam.OneBotClient(
        onebot_url=onebot_url,
        token=token,
        direction="forward",
    )

    result = {
        "schema_version": 1,
        "neko_commit": args.neko_commit,
        "qq_plugin_commit": args.qq_plugin_commit,
        "work_root": str(args.work_root.resolve()),
        "product_data_touched": False,
        "synthetic_commitment_only": True,
        "commitment_text_recorded": False,
        "account_recorded": False,
        "token_recorded": False,
        "native_commitment_seeded": counts.get("added", 0) == 1,
        "native_due_commitment_visible": bool(due),
        "native_topic_cue_nonempty": bool(cue.strip()),
        "native_topic_cue_contains_commitment": cue_contains_commitment,
        "native_topic_cue_sha256": cue_sha256,
        "delivery_target": "login_self",
        "message_sent": False,
        "verdict": "FAIL",
    }

    try:
        await client.connect()
        result["onebot_connected"] = await _wait_connected(client)
        if not result["onebot_connected"]:
            result["reason"] = "OneBot did not connect"
            return 52

        login = await client.get_login_info()
        user_id = str(login.get("user_id") or "").strip()
        result["login_identity_present"] = bool(user_id)
        result["login_identity_matches_saved_config"] = bool(
            expected_account and user_id == expected_account
        )
        if not user_id:
            result["reason"] = "login identity missing"
            return 53

        # Deliver only to the logged-in account itself. The marker is recalled
        # immediately after receipt verification.
        delivery_text = "[XiaoYu commitment E2E self-test] " + str(due["text"])
        message_id = await client.send_message(user_id, delivery_text)
        result["message_sent"] = bool(message_id)
        result["receipt_present"] = False
        result["receipt_content_match"] = False
        result["message_recalled"] = False
        if message_id:
            sent = await client.get_msg(message_id)
            result["receipt_present"] = bool(sent)
            result["receipt_content_match"] = (
                "XiaoYu commitment E2E self-test" in _extract_raw_message(sent)
                and TEXT in _extract_raw_message(sent)
            )
            await client.delete_msg(message_id)
            result["message_recalled"] = True

        transport_ok = all(
            [
                result["message_sent"],
                result["receipt_present"],
                result["receipt_content_match"],
                result["message_recalled"],
            ]
        )

        written = []
        if transport_ok:
            written = store.mark_surfaced(
                CHARACTER,
                [str(due["id"])],
                now=now,
            )
        result["surface_written_after_receipt"] = str(due["id"]) in written
        result["same_process_duplicate_suppressed"] = (
            store.get_due_commitment(CHARACTER, now=now + 60) is None
        )

        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--verify-after",
                "--work-root",
                str(args.work_root),
                "--neko-root",
                str(args.neko_root),
                "--now",
                str(now + 60),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        lines = [line for line in child.stdout.splitlines() if line.strip().startswith("{")]
        child_doc = json.loads(lines[-1]) if lines else {}
        result["fresh_process_exit_code"] = child.returncode
        result["fresh_process_duplicate_suppressed"] = bool(child_doc.get("pass"))

        result["pass"] = all(
            [
                result["native_commitment_seeded"],
                result["native_due_commitment_visible"],
                result["native_topic_cue_nonempty"],
                result["native_topic_cue_contains_commitment"],
                result["onebot_connected"],
                result["login_identity_present"],
                result["login_identity_matches_saved_config"],
                transport_ok,
                result["surface_written_after_receipt"],
                result["same_process_duplicate_suppressed"],
                result["fresh_process_exit_code"] == 0,
                result["fresh_process_duplicate_suppressed"],
            ]
        )
        result["verdict"] = "PASS" if result["pass"] else "FAIL"
        return 0 if result["pass"] else 54
    finally:
        try:
            await client.disconnect()
            result["disconnected_cleanly"] = not client.is_connected()
        except Exception:
            result["disconnected_cleanly"] = False
        _close_logging_handlers()
        await asyncio.sleep(0.1)
        if args.work_root.exists():
            shutil.rmtree(args.work_root, ignore_errors=True)
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
    ap.add_argument("--work-root", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--napcat-config", type=Path, default=DEFAULT_NAPCAT_CONFIG)
    ap.add_argument("--evidence", type=Path)
    ap.add_argument("--verify-after", action="store_true")
    ap.add_argument("--now", type=float, default=0.0)
    ap.add_argument(
        "--neko-commit",
        default="402695cd115323440dfd4e6860c25a32c10dda43",
    )
    ap.add_argument(
        "--qq-plugin-commit",
        default="54acf36bf978edad4757e5fffc743c5618360700",
    )
    args = ap.parse_args()
    if args.verify_after:
        return _verify_after(args)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
