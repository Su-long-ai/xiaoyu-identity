#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the E2 prospective protocol only after all pre-freeze gates pass.

Default is dry-run. --freeze changes only the protocol status and writes an
immutable-style hash record; it NEVER changes paid phase or benchmark_unlocked.
"""
from __future__ import annotations
import argparse,hashlib,json,os,time,uuid
from pathlib import Path

import p1_integration_doctor as p1
import p2_integration_doctor as p2
import smoke_exit_doctor as sx
from research_api import ResearchApiBudget

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
PROTOCOL=GOV/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
CONTRACT=GOV/"SMOKE_EXIT_CONTRACT.json"
RECORD=GOV/"E2_PROTOCOL_FREEZE_RECORD.json"
DB=GOV/"registry.sqlite3"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def budget_status():
    b=ResearchApiBudget(ROOT)
    try:return b.status()
    finally:b.close()


def preflight():
    protocol=load(PROTOCOL); contract=load(CONTRACT)
    errors=[]; blockers=[]
    if protocol.get("schema") not in (
            "xiaoyu-e2-prospective-protocol-candidate-v1",
            "xiaoyu-e2-pilot-protocol-v2"):
        errors.append({"type":"protocol_schema"})
    if protocol.get("schema")=="xiaoyu-e2-pilot-protocol-v2":
        if protocol.get("protocol_role")!="NONPROMOTIONAL_PILOT":
            errors.append({"type":"pilot_protocol_role_invalid"})
        if protocol.get("claim_eligibility")!="NONE":
            errors.append({"type":"pilot_claim_eligibility_must_be_none"})
        if protocol.get("scope",{}).get("confirmatory_calls_allowed") is not False:
            errors.append({"type":"pilot_confirmatory_calls_not_forbidden"})
        split=protocol.get("split_manifest") or {}
        split_path=ROOT/split.get("path","")
        actual=(hashlib.sha256(split_path.read_bytes()).hexdigest()
                if split_path.is_file() else None)
        if actual!=split.get("sha256"):
            errors.append({"type":"pilot_split_manifest_hash_drift",
                           "expected":split.get("sha256"),"actual":actual})
    if protocol.get("status") not in ("DRAFT_PRE_FREEZE","FROZEN_BEFORE_EXECUTION"):
        errors.append({"type":"protocol_status_invalid","actual":protocol.get("status")})
    tracks=protocol.get("required_tracks") or []
    unready=[{"id":x.get("id"),"blocker":x.get("blocker")} for x in tracks
             if not x.get("ready_to_freeze")]
    if unready:blockers.append({"type":"required_track_unready","tracks":unready})
    if protocol.get("scope",{}).get("private_identity_data") is not False:
        errors.append({"type":"private_identity_data_not_forbidden"})

    # Reuse smoke contract pinned-input verification without requiring protocol frozen.
    for name,spec in (contract.get("pinned_inputs") or {}).items():
        path=ROOT/spec["path"]
        got=(hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
        if got!=spec.get("sha256"):
            errors.append({"type":"pinned_input_hash_drift","input":name,
                           "expected":spec.get("sha256"),"actual":got})

    p1r=p1.evaluate(); p2r=p2.evaluate()
    if not p1r.get("integration_ready"):
        blockers.append({"type":"p1_not_ready"})
    if not p2r.get("p2_closeout_ready"):
        blockers.append({"type":"p2_not_closed",
                         "blocked_stages":p2r.get("blocked_required_stages",[])})
    scope=sx._p2_scope_state(
        DB,
        contract.get("p2_scope_lineages_legacy") or contract.get("p2_scope_lineages") or [],
        contract.get("blocking_scopes") or [])
    evidence=sx._prefreeze_evidence(DB,contract.get("required_prefreeze_evidence") or [])
    if not evidence["ok"]:
        blockers.append({"type":"prefreeze_evidence_incomplete",
                         "checks":[x for x in evidence["checks"] if not x["ok"]]})
    if scope["active"]:
        blockers.append({"type":"p2_scope_active",
                         "leases":[x["lease_id"] for x in scope["active"]]})
    if scope["pending_e1"]:
        blockers.append({"type":"p2_scope_pending_e1",
                         "submissions":[x["submission_id"] for x in scope["pending_e1"]]})

    bs=budget_status()
    paid=contract.get("paid_phase") or {}
    if bs.get("active_phase")!="smoke":
        blockers.append({"type":"paid_phase_not_smoke","actual":bs.get("active_phase")})
    if bool(bs.get("benchmark_unlocked")):
        blockers.append({"type":"benchmark_already_unlocked"})
    unknown=int((bs.get("calls_by_status") or {}).get("UNKNOWN",0))
    if unknown>int(paid.get("max_unknown_calls",0)):
        blockers.append({"type":"unknown_calls_increased","actual":unknown,
                         "allowed":int(paid.get("max_unknown_calls",0))})
    if int(bs.get("phase_used_or_reserved_tokens",0))>int(bs.get("phase_cap_tokens",0)):
        errors.append({"type":"smoke_budget_exceeded"})

    return {
      "schema":"xiaoyu-e2-protocol-freeze-preflight-v1",
      "protocol_status":protocol.get("status"),
      "required_tracks_ready":not unready,
      "p1_integration_ready":bool(p1r.get("integration_ready")),
      "p2_closeout_ready":bool(p2r.get("p2_closeout_ready")),
      "p2_blocked_stages":p2r.get("blocked_required_stages",[]),
      "p2_scope_state":scope,
      "prefreeze_evidence":evidence,
      "paid_phase":{
        "active_phase":bs.get("active_phase"),
        "benchmark_unlocked":bool(bs.get("benchmark_unlocked")),
        "used":int(bs.get("phase_used_or_reserved_tokens",0)),
        "cap":int(bs.get("phase_cap_tokens",0)),
        "remaining":int(bs.get("phase_remaining_tokens",0)),
        "unknown_calls":unknown,
      },
      "errors":errors,"blockers":blockers,
      "freeze_allowed":not errors and not blockers,
    }


def atomic_write(path,data):
    path=Path(path)
    tmp=path.with_name(path.name+".tmp."+uuid.uuid4().hex)
    with tmp.open("xb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def freeze():
    check=preflight()
    if not check["freeze_allowed"]:
        return {"frozen":False,"preflight":check}
    protocol=load(PROTOCOL)
    if protocol.get("status")=="FROZEN_BEFORE_EXECUTION":
        raw=PROTOCOL.read_bytes()
        return {"frozen":True,"already_frozen":True,
                "protocol_sha256":digest_bytes(raw),"preflight":check}

    protocol["status"]="FROZEN_BEFORE_EXECUTION"
    protocol["freeze_metadata"]={
      "frozen_at_epoch":time.time(),
      "basis":"P1 integration-ready + P2 closeout-ready + quiescent P2 scope + pinned benchmark inputs + smoke budget within cap",
      "phase_switch_performed":False,
      "e2_claim_allowed":False,
      "preflight_snapshot":{
        "p1_integration_ready":check["p1_integration_ready"],
        "p2_closeout_ready":check["p2_closeout_ready"],
        "paid_phase":check["paid_phase"],
      }
    }
    raw=(json.dumps(protocol,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    atomic_write(PROTOCOL,raw)
    psha=digest_bytes(raw)
    record={
      "schema":"xiaoyu-e2-protocol-freeze-record-v1",
      "protocol":"governance/E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json",
      "protocol_sha256":psha,
      "frozen_at_epoch":protocol["freeze_metadata"]["frozen_at_epoch"],
      "phase_switch_performed":False,
      "e2_claim_allowed":False,
      "preflight":check,
    }
    atomic_write(RECORD,(json.dumps(record,ensure_ascii=False,indent=2)+"\n").encode("utf-8"))
    return {"frozen":True,"already_frozen":False,
            "protocol_sha256":psha,"freeze_record":str(RECORD),"preflight":check}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--freeze",action="store_true",
                    help="perform the one-way protocol freeze after preflight PASS")
    a=ap.parse_args()
    out=freeze() if a.freeze else preflight()
    print(json.dumps(out,ensure_ascii=False,indent=2))
    ok=(out.get("frozen") if a.freeze else out.get("freeze_allowed"))
    if not ok: raise SystemExit(3)


if __name__=="__main__":
    main()
