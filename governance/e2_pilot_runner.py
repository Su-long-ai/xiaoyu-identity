#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crash-safe E2 pilot paid-call runner.

This is an execution helper, not a benchmark data builder. It consumes a
caller-prepared dynamic payload only after validating the frozen execution
manifest. Every paid call still goes through the loopback research proxy.

Default action is preflight; provider access requires --run-case explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"
MANIFEST = GOV / "E2_PILOT_EXECUTION_MANIFEST.json"
POLICY = GOV / "policy.json"
RUNTIME = GOV / "e2_pilot_runtime"

_FORBIDDEN_KEYS = {
    "answer", "golden_answer", "reference_answer", "gold", "answer_session_ids",
    "memory_points", "memory_points_count", "evidence", "difficulty",
    "original_memories", "has_answer",
}


class RunnerError(RuntimeError):
    pass


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def forbidden_hits(obj, path="$"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in _FORBIDDEN_KEYS:
                hits.append(path + "." + str(k))
            hits.extend(forbidden_hits(v, path + "." + str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(forbidden_hits(v, path + f"[{i}]"))
    return hits


def frozen_state():
    manifest = load(MANIFEST)
    policy = load(POLICY)
    e2 = policy.get("e2_transition") or {}
    actual = sha_file(MANIFEST)
    expected = str(e2.get("pilot_execution_manifest_sha256") or "")
    if not expected or actual != expected:
        raise RunnerError("execution manifest hash does not match frozen policy")
    if manifest.get("status") != "FROZEN_BEFORE_FIRST_E2_PAID_CALL":
        raise RunnerError("execution manifest is not frozen")
    if e2.get("current_stage") != "E2_PILOT":
        raise RunnerError("control plane is not E2_PILOT")
    return manifest, policy


def track_spec(manifest, track: str):
    spec = (manifest.get("tracks") or {}).get(track)
    if not isinstance(spec, dict):
        raise RunnerError(f"unknown frozen E2 track: {track}")
    return spec


def encode_dynamic_payload(spec, case_id: str, payload: dict) -> str:
    contract = spec.get("dynamic_payload_contract") or {}
    encoding = str(contract.get("encoding") or "")
    required = list(contract.get("required_keys") or [])
    allowed = set(contract.get("allowed_keys") or [])
    keys = set(payload)
    if not required or not allowed:
        raise RunnerError("frozen dynamic payload contract is incomplete")
    missing = [k for k in required if k not in payload]
    extra = sorted(keys - allowed)
    if missing:
        raise RunnerError("dynamic payload missing required keys: " + ",".join(missing))
    if extra:
        raise RunnerError("dynamic payload has non-frozen keys: " + ",".join(extra))

    if encoding == "r18_single_case_compact_json_v1":
        if str(payload.get("id")) != case_id:
            raise RunnerError("R18 dynamic payload id must equal frozen case_id")
        ordered = {k: payload[k] for k in ("id", "context", "question")}
        prefix = str(contract.get("user_prefix") or "")
        if not prefix:
            raise RunnerError("R18 frozen user prefix is missing")
        return prefix + json.dumps(
            [ordered], ensure_ascii=False, separators=(",", ":")
        )

    if encoding == "r35_single_target_message_compact_json_v1":
        if not isinstance(payload.get("current_state"), dict):
            raise RunnerError("R35 current_state must be an object")
        if not isinstance(payload.get("context_messages"), list):
            raise RunnerError("R35 context_messages must be an array")
        if not isinstance(payload.get("slots"), list):
            raise RunnerError("R35 slots must be an array")
        target = payload.get("target_message")
        if not isinstance(target, dict):
            raise RunnerError("R35 target_message must be an object")
        target_required = list(contract.get("target_message_required_keys") or [])
        missing_target = [k for k in target_required if k not in target]
        if missing_target:
            raise RunnerError(
                "R35 target_message missing required keys: " + ",".join(missing_target))
        if str(target.get("role") or "").lower() != str(
            contract.get("target_message_role") or ""
        ).lower():
            raise RunnerError("R35 target_message role must be frozen user role")
        # Preserve the accepted R35 top-level field order while making
        # serialization byte-deterministic.
        ordered = {
            "current_state": payload["current_state"],
            "context_messages": payload["context_messages"],
            "target_message": payload["target_message"],
            "slots": payload["slots"],
        }
        return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))

    raise RunnerError("unsupported frozen dynamic payload encoding: " + encoding)


def validate_payload(manifest, track: str, case_id: str, payload):
    spec = track_spec(manifest, track)
    if case_id not in set(str(x) for x in spec.get("case_ids", [])):
        raise RunnerError("case_id is outside frozen E2 pilot track")
    if not isinstance(payload, dict):
        raise RunnerError("dynamic payload must be a JSON object")
    hits = forbidden_hits(payload)
    if hits:
        raise RunnerError("gold/answer-only fields are forbidden from model input: " + ",".join(hits[:8]))
    prefix = spec.get("invariant_prefix_messages")
    if not isinstance(prefix, list) or not prefix:
        raise RunnerError("frozen invariant prefix is missing")
    dynamic_content = encode_dynamic_payload(spec, case_id, payload)
    user = {"role": "user", "content": dynamic_content}
    messages = [*prefix, user]
    prefix_sha = sha_bytes(canon(prefix).encode("utf-8"))
    if prefix_sha != spec.get("invariant_prefix_sha256"):
        raise RunnerError("computed invariant prefix hash differs from frozen manifest")
    return spec, messages, prefix_sha


def request_fingerprint(spec, messages):
    return sha_bytes(canon({
        "messages": messages,
        "max_tokens": int(spec["max_completion_tokens"]),
        "response_format": spec["response_format"],
    }).encode("utf-8"))


def recover_case(case_id: str):
    import sys
    if str(GOV) not in sys.path:
        sys.path.insert(0, str(GOV))
    from research_api import ResearchApiBudget
    b = ResearchApiBudget(ROOT)
    try:
        return b.recover_e2_case(case_id)
    finally:
        b.close()


def receipt_path(case_id: str):
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in case_id)
    return RUNTIME / (safe + ".json")


def materialize_recovery(track: str, case_id: str, spec, recovered, request_sha=None):
    if not recovered or recovered.get("status") != "COMMITTED":
        return None
    receipt = {
        "schema": "xiaoyu-e2-pilot-case-receipt-v1",
        "track": track,
        "case_id": case_id,
        "scope": spec["scope"],
        "call_id": recovered["call_id"],
        "status": "COMMITTED",
        "prompt_prefix_sha256": recovered["prompt_prefix_sha256"],
        "request_sha256": request_sha,
        "response_text": recovered["response_text"],
        "response_sha256": recovered["response_sha256"],
        "usage": {
            "prompt_tokens": recovered["prompt_tokens"],
            "completion_tokens": recovered["completion_tokens"],
            "actual_tokens": recovered["actual_tokens"],
            "cache_hit_tokens": recovered["cache_hit_tokens"],
            "cache_miss_tokens": recovered["cache_miss_tokens"],
        },
        "recovered_from_paid_ledger": True,
    }
    atomic_json(receipt_path(case_id), receipt)
    return receipt


def call_proxy(url: str, track: str, case_id: str, spec, messages):
    body = {
        "messages": messages,
        "max_tokens": int(spec["max_completion_tokens"]),
        "response_format": spec["response_format"],
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer local-budget-proxy:xiaoyu",
            "X-XiaoYu-Research-Run": str(spec["run_header"]),
            "X-XiaoYu-Case-ID": case_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise RunnerError(f"research proxy rejected call ({exc.code}): {detail[:1000]}") from exc


def preflight():
    manifest, policy = frozen_state()
    import sys
    if str(GOV) not in sys.path:
        sys.path.insert(0, str(GOV))
    import e2_token_efficiency_doctor
    doctor = e2_token_efficiency_doctor.evaluate(ROOT)
    if not doctor.get("pilot_execution_ready"):
        raise RunnerError("E2 token-efficiency doctor is not ready")
    return {
        "schema": "xiaoyu-e2-pilot-runner-preflight-v1",
        "manifest_sha256": sha_file(MANIFEST),
        "paid_case_count": manifest["paid_case_count"],
        "track_case_counts": {k: v["case_count"] for k, v in manifest["tracks"].items()},
        "pilot_remaining_tokens": doctor["runtime"]["pilot_remaining_tokens"],
        "runtime_dir": str(RUNTIME),
        "provider_calls": 0,
        "ready": True,
    }


def run_case(track: str, case_id: str, payload_path: Path, proxy_url: str):
    manifest, _policy = frozen_state()
    payload = load(payload_path)
    spec, messages, prefix_sha = validate_payload(manifest, track, case_id, payload)
    request_sha = request_fingerprint(spec, messages)

    prior = recover_case(case_id)
    if prior is not None:
        if prior["status"] == "COMMITTED":
            receipt = materialize_recovery(track, case_id, spec, prior, request_sha=request_sha)
            return {"paid_call": False, "recovered": True, "receipt": receipt}
        raise RunnerError(
            f"case {case_id} has paid-ledger status {prior['status']}; "
            "fail closed until explicit reconciliation"
        )

    response = call_proxy(proxy_url, track, case_id, spec, messages)
    call_id = str(response.get("id") or "")
    content = str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""))
    if not call_id or not content:
        raise RunnerError("proxy returned incomplete response")

    recovered = recover_case(case_id)
    if not recovered or recovered.get("status") != "COMMITTED":
        raise RunnerError("provider returned but durable paid-ledger receipt is missing")
    if recovered.get("call_id") != call_id:
        raise RunnerError("proxy call_id differs from durable paid-ledger receipt")
    if recovered.get("response_text") != content:
        raise RunnerError("proxy response differs from durable paid-ledger response")
    receipt = materialize_recovery(track, case_id, spec, recovered, request_sha=request_sha)
    return {"paid_call": True, "recovered": False, "receipt": receipt}


def validate_plan(path: Path):
    manifest, _ = frozen_state()
    seen = set()
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            track = str(row.get("track") or "")
            cid = str(row.get("case_id") or "")
            payload = row.get("payload")
            spec, messages, _ = validate_payload(manifest, track, cid, payload)
            if cid in seen:
                raise RunnerError(f"duplicate case_id in plan at line {n}: {cid}")
            seen.add(cid)
            rows.append({
                "track": track,
                "case_id": cid,
                "request_sha256": request_fingerprint(spec, messages),
            })
    return {
        "schema": "xiaoyu-e2-pilot-input-plan-check-v1",
        "rows": len(rows),
        "unique_case_ids": len(seen),
        "plan_sha256": sha_bytes(canon(rows).encode("utf-8")),
        "provider_calls": 0,
        "valid": True,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("preflight")
    vp = sub.add_parser("validate-plan")
    vp.add_argument("path")
    rp = sub.add_parser("recover")
    rp.add_argument("--track", required=True)
    rp.add_argument("--case-id", required=True)
    cp = sub.add_parser("run-case")
    cp.add_argument("--track", required=True)
    cp.add_argument("--case-id", required=True)
    cp.add_argument("--payload", required=True)
    cp.add_argument("--proxy-url", default="http://127.0.0.1:18081")
    args = ap.parse_args()

    cmd = args.cmd or "preflight"
    if cmd == "preflight":
        out = preflight()
    elif cmd == "validate-plan":
        out = validate_plan(Path(args.path))
    elif cmd == "recover":
        manifest, _ = frozen_state()
        spec = track_spec(manifest, args.track)
        if args.case_id not in set(spec["case_ids"]):
            raise RunnerError("case_id outside frozen track")
        recovered = recover_case(args.case_id)
        if recovered is None:
            out = {"case_id": args.case_id, "status": "NOT_CALLED", "provider_calls": 0}
        elif recovered["status"] == "COMMITTED":
            out = materialize_recovery(args.track, args.case_id, spec, recovered)
            out["provider_calls"] = 0
        else:
            out = {"case_id": args.case_id, "status": recovered["status"], "provider_calls": 0}
    else:
        out = run_case(args.track, args.case_id, Path(args.payload), args.proxy_url)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
