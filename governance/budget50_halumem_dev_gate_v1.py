#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Budget-50 HaluMem dev gate using the exact current structural-v5 + R52 stack.

The gate reuses the original exposed pilot windows (647 user semantic cases and
51 frozen QA questions). Prediction is gold-blind; gold is not decoded by this
runner. Paid calls use a dedicated bounded scope and distinct case IDs, so this
cannot mutate or consume the formal confirmatory generation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
FROZEN = GOV / "confirmatory_frozen"
MANIFEST = GOV / "BUDGET50_HALUMEM_DEV_GATE_V1.json"
RUNTIME = GOV / "budget50_halumem_dev_runtime_v1"
LEDGER = GOV / "research_api_usage.sqlite3"
MEDIUM = ROOT / "external" / "halumem_dataset_cache" / "HaluMem-Medium.jsonl"
LONG = ROOT / "external" / "halumem_dataset_cache" / "HaluMem-Long.jsonl"
SEAL = RUNTIME / "PREDICTION_SEAL.json"

for p in (str(FROZEN), str(GOV), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location(
    "_xiaoyu_budget50_base", FROZEN / "HALUMEM_CONFIRMATORY_RUNNER.py"
)
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)


class DevGateError(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def atomic_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_manifest() -> dict:
    if not MANIFEST.is_file():
        raise DevGateError("budget50 dev manifest missing")
    m = load_json(MANIFEST)
    if m.get("schema") != "xiaoyu-budget50-halumem-dev-gate-v1":
        raise DevGateError("bad budget50 dev manifest schema")
    if m.get("status") != "READY_FOR_BOUNDED_DEV_EXECUTION":
        raise DevGateError("budget50 dev manifest not executable")
    impl = m.get("implementation") or {}
    if sha_file(Path(__file__)) != impl.get("runner_sha256"):
        raise DevGateError("budget50 dev runner byte drift")
    proxy = GOV / "research_api_proxy_budget50_dev_v1.py"
    if sha_file(proxy) != impl.get("proxy_sha256"):
        raise DevGateError("budget50 dev proxy byte drift")
    if sha_file(FROZEN / "HALUMEM_CONFIRMATORY_RUNNER.py") != impl.get("base_runner_sha256"):
        raise DevGateError("base confirmatory runner byte drift")
    for rel, expected in (m.get("source_bindings") or {}).items():
        p = ROOT / rel
        if not p.is_file() or sha_file(p) != expected:
            raise DevGateError("source binding drift: " + rel)
    closure = base.verify_r52_closure()
    if closure != (m.get("current_stack") or {}).get("r52_closure"):
        raise DevGateError("R52 closure drift")
    if base.structural.prompt_sha256() != (m.get("current_stack") or {}).get("prompt_sha256"):
        raise DevGateError("structural-v5 prompt drift")
    if base.structural.schema_sha256() != (m.get("current_stack") or {}).get("schema_sha256"):
        raise DevGateError("structural-v5 schema drift")
    return m


def _sqlite_backup(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        if tmp.exists():
            tmp.unlink()
        a = sqlite3.connect(str(src))
        b = sqlite3.connect(str(tmp))
        try:
            a.backup(b)
            b.commit()
        finally:
            b.close()
            a.close()
        with tmp.open("rb+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _restore_checkpoint(src: Path, dst: Path):
    if not src.is_file():
        raise DevGateError("state checkpoint missing")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".restore.tmp")
    try:
        if tmp.exists():
            tmp.unlink()
        a = sqlite3.connect(str(src))
        b = sqlite3.connect(str(tmp))
        try:
            a.backup(b)
            b.commit()
        finally:
            b.close()
            a.close()
        for suffix in ("-wal", "-shm"):
            try:
                Path(str(dst) + suffix).unlink()
            except FileNotFoundError:
                pass
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _stream_key(spec: dict) -> str:
    return f"{spec['variant']}-{spec['uuid_hash_prefix']}"


def prediction_path(spec: dict) -> Path:
    return RUNTIME / "predictions" / (_stream_key(spec) + ".json")


def state_path(spec: dict) -> Path:
    return RUNTIME / "state" / (_stream_key(spec) + ".sqlite3")


def checkpoint_path(spec: dict, completed: int) -> Path:
    return RUNTIME / "state_checkpoints" / _stream_key(spec) / f"session-{completed:03d}.sqlite3"


def intent_path(case_id: str) -> Path:
    return RUNTIME / "request_intents" / (case_id + ".json")


def receipt_path(case_id: str) -> Path:
    return RUNTIME / "semantic_receipts" / (case_id + ".json")


def _ledger_row(case_id: str):
    con = sqlite3.connect(LEDGER)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """SELECT call_id,status,budget_scope,prompt_tokens,completion_tokens,
                      actual_tokens,cache_hit_tokens,cache_miss_tokens,
                      response_text,response_sha256,prompt_prefix_sha256
                 FROM calls WHERE phase='benchmark' AND case_id=?
                ORDER BY created_at DESC LIMIT 1""",
            (case_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    out = dict(row)
    if out["status"] == "COMMITTED":
        text = out.get("response_text")
        digest = out.get("response_sha256")
        if not isinstance(text, str) or not digest:
            raise DevGateError("committed dev case missing durable response")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise DevGateError("committed dev response hash mismatch")
    return out


def _ensure_intent(m: dict, case_id: str, messages: list[dict]) -> dict:
    expected = {
        "schema": "xiaoyu-budget50-halumem-dev-intent-v1",
        "case_id": case_id,
        "scope": m["paid_track"]["scope"],
        "request_messages_sha256": stable(messages),
        "manifest_sha256": sha_file(MANIFEST),
        "runner_sha256": sha_file(Path(__file__)),
    }
    p = intent_path(case_id)
    if p.is_file():
        if load_json(p) != expected:
            raise DevGateError("dev request intent drift: " + case_id)
    else:
        atomic_json(p, expected)
    return expected


def _validate_receipt(m: dict, case_id: str, messages: list[dict]) -> dict:
    p = receipt_path(case_id)
    if not p.is_file():
        raise DevGateError("local dev receipt missing")
    local = load_json(p)
    durable = _ledger_row(case_id)
    if durable is None or durable.get("status") != "COMMITTED":
        raise DevGateError("local dev receipt lacks COMMITTED durable ledger row")
    required = {
        "schema": "xiaoyu-budget50-halumem-dev-receipt-v1",
        "case_id": case_id,
        "scope": m["paid_track"]["scope"],
        "call_id": durable["call_id"],
        "response_sha256": durable["response_sha256"],
        "request_messages_sha256": stable(messages),
        "manifest_sha256": sha_file(MANIFEST),
    }
    for k, v in required.items():
        if local.get(k) != v:
            raise DevGateError(f"dev receipt drift {case_id}:{k}")
    if local.get("response_text") != durable.get("response_text"):
        raise DevGateError("local dev response differs from durable ledger")
    return local


def load_or_call_provider(m: dict, case_id: str, messages: list[dict]) -> dict:
    _ensure_intent(m, case_id, messages)
    p = receipt_path(case_id)
    if p.is_file():
        return _validate_receipt(m, case_id, messages)

    durable = _ledger_row(case_id)
    if durable is not None:
        if durable.get("status") != "COMMITTED":
            raise DevGateError(
                f"dev case {case_id} already {durable.get('status')}; paid retry forbidden"
            )
        rec = {
            "schema": "xiaoyu-budget50-halumem-dev-receipt-v1",
            "case_id": case_id,
            "scope": m["paid_track"]["scope"],
            "call_id": durable["call_id"],
            "response_text": durable["response_text"],
            "response_sha256": durable["response_sha256"],
            "request_messages_sha256": stable(messages),
            "manifest_sha256": sha_file(MANIFEST),
            "recovered_from_ledger": True,
            "usage": {
                "prompt_tokens": durable.get("prompt_tokens"),
                "completion_tokens": durable.get("completion_tokens"),
                "total_tokens": durable.get("actual_tokens"),
                "prompt_cache_hit_tokens": durable.get("cache_hit_tokens"),
                "prompt_cache_miss_tokens": durable.get("cache_miss_tokens"),
            },
        }
        atomic_json(p, rec)
        return _validate_receipt(m, case_id, messages)

    track = m["paid_track"]
    body = {
        "model": __import__("model_adapter").load_provider(ROOT)["model"],
        "messages": messages,
        "max_tokens": int(track["max_completion_tokens"]),
        "stream": False,
        "thinking": {"type": "disabled"},
        "reasoning_effort": "none",
        "temperature": 0.0,
        "top_p": 1.0,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:18082/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer local-budget-proxy:xiaoyu",
            "X-XiaoYu-Research-Run": "budget50_halumem_dev_v1",
            "X-XiaoYu-Case-ID": case_id,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as f:
            payload = json.loads(f.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", "replace")
        raise DevGateError(f"dev provider HTTP {exc.code}: {msg[:1200]}") from exc
    except Exception as exc:
        raise DevGateError(type(exc).__name__ + ":" + str(exc)) from exc

    durable = _ledger_row(case_id)
    if durable is None or durable.get("status") != "COMMITTED":
        raise DevGateError("provider returned but durable dev receipt is not COMMITTED")
    content = str(payload["choices"][0]["message"]["content"])
    if durable.get("response_text") != content:
        raise DevGateError("proxy response differs from durable dev receipt")
    rec = {
        "schema": "xiaoyu-budget50-halumem-dev-receipt-v1",
        "case_id": case_id,
        "scope": track["scope"],
        "call_id": durable["call_id"],
        "response_text": content,
        "response_sha256": durable["response_sha256"],
        "request_messages_sha256": stable(messages),
        "manifest_sha256": sha_file(MANIFEST),
        "recovered_from_ledger": False,
        "usage": payload.get("usage"),
    }
    atomic_json(p, rec)
    return _validate_receipt(m, case_id, messages)


def _safe_record(path: Path, uuid_value: str) -> dict:
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            row = base.safe_project_line(raw.strip(), {uuid_value})
            if row is not None:
                return row
    raise DevGateError("pilot UUID not found in dataset")


def _dev_case_id(variant: str, pref: str, si: int, ti: int) -> str:
    return f"hm-b50-{variant}-{pref}-s{si}-t{ti}"


def _old_extract_id(variant: str, pref: str, si: int, ti: int) -> str:
    return f"hm-{variant}-i-{pref}-{si}-{ti}"


def _old_qa_id(variant: str, pref: str, si: int, qi: int) -> str:
    return f"hm-{variant}-q-{pref}-{si}-{qi}"


def _initial_progress(m: dict, spec: dict, safe: dict) -> dict:
    return {
        "schema": "xiaoyu-budget50-halumem-dev-prediction-v1",
        "variant": spec["variant"],
        "uuid": spec["uuid"],
        "uuid_hash_prefix": spec["uuid_hash_prefix"],
        "window_start": spec["window_start"],
        "window_count": spec["window_count"],
        "safe_projection_sha256": stable(safe),
        "completed_sessions": 0,
        "total_sessions": spec["window_count"],
        "sessions": [],
        "complete": False,
        "semantic_calls": 0,
        "semantic_rejects_fail_closed": 0,
        "selected_qa_count": 0,
        "manifest_sha256": sha_file(MANIFEST),
        "runner_sha256": sha_file(Path(__file__)),
        "gold_fields_materialized": 0,
        "state_checkpoint": None,
    }


def _ensure_checkpoint_zero(spec: dict, progress: dict, dbp: Path):
    ref = progress.get("state_checkpoint")
    if ref is not None:
        return ref
    if int(progress.get("completed_sessions") or 0) != 0:
        raise DevGateError("progress missing checkpoint")
    for p in (dbp, Path(str(dbp) + "-wal"), Path(str(dbp) + "-shm")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    comp = base.r52.R52Composition(dbp, identity_id="budget50-dev:" + _stream_key(spec))
    comp.close()
    cp = checkpoint_path(spec, 0)
    _sqlite_backup(dbp, cp)
    ref = {
        "completed_sessions": 0,
        "path": str(cp.relative_to(GOV)).replace("\\", "/"),
        "sha256": sha_file(cp),
    }
    progress["state_checkpoint"] = ref
    return ref


def process_stream(m: dict, spec: dict) -> dict:
    source = MEDIUM if spec["variant"] == "m" else LONG
    safe = _safe_record(source, spec["uuid"])
    uh = hashlib.sha256(spec["uuid"].encode()).hexdigest()
    if uh[:12] != spec["uuid_hash_prefix"]:
        raise DevGateError("pilot UUID hash prefix drift")
    outp = prediction_path(spec)
    progress = _initial_progress(m, spec, safe)
    if outp.is_file():
        progress = load_json(outp)
        if progress.get("safe_projection_sha256") != stable(safe):
            raise DevGateError("safe projection drift")
        if progress.get("manifest_sha256") != sha_file(MANIFEST):
            raise DevGateError("prediction manifest drift")
        if progress.get("runner_sha256") != sha_file(Path(__file__)):
            raise DevGateError("prediction runner drift")
        if progress.get("complete") is True:
            return progress

    start = int(spec["window_start"])
    count = int(spec["window_count"])
    end = start + count
    if end > len(safe["sessions"]):
        raise DevGateError("pilot window outside safe record")
    completed = int(progress.get("completed_sessions") or 0)
    if completed != len(progress.get("sessions") or []):
        raise DevGateError("prediction progress cardinality drift")

    dbp = state_path(spec)
    dbp.parent.mkdir(parents=True, exist_ok=True)
    ref = _ensure_checkpoint_zero(spec, progress, dbp)
    if not outp.is_file():
        atomic_json(outp, progress)

    old_extract = set(m["pilot_membership"]["extract_case_ids"])
    old_qa = set(m["pilot_membership"]["qa_case_ids"])
    new_cases = set(m["paid_track"]["case_ids"])
    pref = spec["uuid_hash_prefix"]

    for local_index in range(completed, count):
        global_si = start + local_index
        cp = GOV / ref["path"]
        if not cp.is_file() or sha_file(cp) != ref["sha256"]:
            raise DevGateError("checkpoint drift before session")
        _restore_checkpoint(cp, dbp)
        comp = base.r52.R52Composition(dbp, identity_id="budget50-dev:" + _stream_key(spec))
        session_sources = []
        session_calls = 0
        session_rejects = 0
        qrows = []
        try:
            ordinal = sum(len(x["dialogue"]) for x in safe["sessions"][:global_si])
            session = safe["sessions"][global_si]
            for ti, turn in enumerate(session["dialogue"]):
                ordinal += 1
                src = base.source_for(spec["variant"], uh, global_si, ti, ordinal, turn)
                session_sources.append(src)
                if turn["role"] == "assistant":
                    comp.ingest_source_envelope_only(src)
                    continue
                old_id = _old_extract_id(spec["variant"], pref, global_si, ti)
                if old_id not in old_extract:
                    raise DevGateError("user turn outside frozen 647 pilot membership: " + old_id)
                cid = _dev_case_id(spec["variant"], pref, global_si, ti)
                if cid not in new_cases:
                    raise DevGateError("derived dev case outside manifest: " + cid)
                messages, _built = base.messages_for(comp, src)
                rec = load_or_call_provider(m, cid, messages)
                session_calls += 1
                try:
                    comp.ingest_source(src, raw_projection=rec["response_text"])
                except Exception:
                    comp.ingest_source_envelope_only(src)
                    session_rejects += 1

            extracted = base._session_claims(comp, session_sources)
            snapshot = [dict(x) for x in comp.current_rows()]
            for qi, q in enumerate(session["questions"]):
                qid = _old_qa_id(spec["variant"], pref, global_si, qi)
                if qid not in old_qa:
                    continue
                ans, abstain, retrieved = comp.answer(q["question"])
                qrows.append(
                    {
                        "qa_case_id": qid,
                        "question": q["question"],
                        "system_response": "I don't know." if abstain or ans is None else str(ans),
                        "abstained": bool(abstain),
                        "retrieved_sha256": stable(retrieved),
                    }
                )
        finally:
            comp.close()

        next_cp = checkpoint_path(spec, local_index + 1)
        _sqlite_backup(dbp, next_cp)
        next_ref = {
            "completed_sessions": local_index + 1,
            "path": str(next_cp.relative_to(GOV)).replace("\\", "/"),
            "sha256": sha_file(next_cp),
        }
        progress["sessions"].append(
            {
                "session_index": global_si,
                "extracted_memories": extracted,
                "current_state_snapshot": snapshot,
                "questions": qrows,
                "semantic_calls": session_calls,
                "semantic_rejects_fail_closed": session_rejects,
            }
        )
        progress["semantic_calls"] += session_calls
        progress["semantic_rejects_fail_closed"] += session_rejects
        progress["selected_qa_count"] += len(qrows)
        progress["completed_sessions"] = local_index + 1
        progress["state_checkpoint"] = next_ref
        atomic_json(outp, progress)
        ref = next_ref

    progress["complete"] = True
    atomic_json(outp, progress)
    return progress


def preflight() -> dict:
    m = load_manifest()
    pilot = load_json(GOV / "E2_PILOT_EXECUTION_MANIFEST.json")
    extract_ids = list((pilot["tracks"]["halumem_extract"]).get("case_ids") or [])
    qa_ids = list((pilot["tracks"]["halumem_qa"]).get("case_ids") or [])
    if extract_ids != m["pilot_membership"]["extract_case_ids"]:
        raise DevGateError("647 extraction membership drift")
    if qa_ids != m["pilot_membership"]["qa_case_ids"]:
        raise DevGateError("51 QA membership drift")
    if len(extract_ids) != 647 or len(set(extract_ids)) != 647:
        raise DevGateError("pilot extraction cardinality is not 647 unique")
    if len(qa_ids) != 51 or len(set(qa_ids)) != 51:
        raise DevGateError("pilot QA cardinality is not 51 unique")
    new_ids = list(m["paid_track"]["case_ids"])
    if len(new_ids) != 647 or len(set(new_ids)) != 647:
        raise DevGateError("dev paid case cardinality is not 647 unique")
    return {
        "ok": True,
        "paid_calls": 0,
        "gold_fields_materialized": 0,
        "streams": len(m["streams"]),
        "semantic_cases": len(new_ids),
        "selected_qa": len(qa_ids),
        "scope": m["paid_track"]["scope"],
        "max_completion_tokens": m["paid_track"]["max_completion_tokens"],
        "thresholds": m["screening_thresholds"],
        "formal_confirmatory_unchanged": True,
    }


def predict() -> dict:
    m = load_manifest()
    if SEAL.exists():
        raise DevGateError("dev predictions already sealed")
    results = []
    for spec in m["streams"]:
        results.append(process_stream(m, spec))
    calls = sum(int(x.get("semantic_calls") or 0) for x in results)
    rejects = sum(int(x.get("semantic_rejects_fail_closed") or 0) for x in results)
    qa_n = sum(int(x.get("selected_qa_count") or 0) for x in results)
    if calls != 647:
        raise DevGateError(f"dev semantic call membership mismatch: {calls} != 647")
    if qa_n != 51:
        raise DevGateError(f"dev QA membership mismatch: {qa_n} != 51")
    return {
        "status": "DEV_PREDICTION_COMPLETE",
        "streams": len(results),
        "semantic_cases": calls,
        "semantic_rejects_fail_closed": rejects,
        "semantic_reject_rate": rejects / calls if calls else None,
        "selected_qa": qa_n,
        "gold_fields_materialized": 0,
    }


def _prediction_files(m: dict):
    rows = []
    for spec in m["streams"]:
        p = prediction_path(spec)
        if not p.is_file():
            raise DevGateError("dev prediction missing: " + p.name)
        obj = load_json(p)
        if obj.get("complete") is not True:
            raise DevGateError("dev prediction incomplete: " + p.name)
        if int(obj.get("gold_fields_materialized") or 0) != 0:
            raise DevGateError("dev prediction materialized gold")
        rows.append(
            {
                "path": str(p.relative_to(GOV)).replace("\\", "/"),
                "sha256": sha_file(p),
            }
        )
    return sorted(rows, key=lambda x: x["path"])


def seal_predictions() -> dict:
    m = load_manifest()
    files = _prediction_files(m)
    if SEAL.is_file():
        old = load_json(SEAL)
        if old.get("prediction_files") != files:
            raise DevGateError("existing dev seal drift")
        return old
    seal = {
        "schema": "xiaoyu-budget50-halumem-dev-prediction-seal-v1",
        "sealed": True,
        "manifest_sha256": sha_file(MANIFEST),
        "runner_sha256": sha_file(Path(__file__)),
        "prediction_files": files,
        "prediction_count": len(files),
        "gold_fields_materialized_before_seal": 0,
        "formal_confirmatory_claim_allowed": False,
    }
    atomic_json(SEAL, seal)
    return seal


def status() -> dict:
    m = load_manifest()
    con = sqlite3.connect(LEDGER)
    try:
        rows = con.execute(
            "SELECT status,count(*) FROM calls WHERE budget_scope=? GROUP BY status",
            (m["paid_track"]["scope"],),
        ).fetchall()
    finally:
        con.close()
    progress = []
    for spec in m["streams"]:
        p = prediction_path(spec)
        if p.is_file():
            d = load_json(p)
            progress.append(
                {
                    "stream": _stream_key(spec),
                    "completed_sessions": d.get("completed_sessions"),
                    "total_sessions": d.get("total_sessions"),
                    "semantic_calls": d.get("semantic_calls"),
                    "selected_qa_count": d.get("selected_qa_count"),
                    "complete": d.get("complete"),
                }
            )
    return {
        "ledger": {str(k): int(v) for k, v in rows},
        "progress": progress,
        "seal_exists": SEAL.is_file(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "action",
        nargs="?",
        default="preflight",
        choices=["preflight", "status", "predict", "seal_predictions"],
    )
    args = ap.parse_args()
    try:
        if args.action == "preflight":
            out = preflight()
        elif args.action == "status":
            out = status()
        elif args.action == "predict":
            out = predict()
        else:
            out = seal_predictions()
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "action": args.action, "error": type(exc).__name__ + ":" + str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2)
    print(json.dumps({"ok": True, "action": args.action, "result": out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
