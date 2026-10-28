#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit smoke -> benchmark paid-phase transition.

Default is dry-run. --switch is a separate Lead action after:
  1) E2 protocol is frozen,
  2) its freeze record hash matches,
  3) smoke_exit_doctor passes,
  4) no paid reservation is in flight.

This script never grants E2/E3 scientific/product status.
"""
from __future__ import annotations
import argparse,hashlib,json,os,time,uuid
from pathlib import Path

import smoke_exit_doctor as sx

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
POLICY=GOV/"policy.json"
PROTOCOL=GOV/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
FREEZE_RECORD=GOV/"E2_PROTOCOL_FREEZE_RECORD.json"
UNLOCK_RECORD=GOV/"BENCHMARK_PHASE_UNLOCK_RECORD.json"
LOCK=GOV/"BENCHMARK_PHASE_SWITCH.lock"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write(path,obj):
    path=Path(path)
    data=(json.dumps(obj,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    tmp=path.with_name(path.name+".tmp."+uuid.uuid4().hex)
    with tmp.open("xb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    return hashlib.sha256(data).hexdigest()


def preflight(root=ROOT, smoke_result=None):
    root=Path(root); gov=root/"governance"
    policy_path=gov/"policy.json"
    protocol_path=gov/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
    record_path=gov/"E2_PROTOCOL_FREEZE_RECORD.json"
    errors=[];blockers=[]

    if smoke_result is None:
        smoke_result=sx.evaluate(root=root)
    if not smoke_result.get("smoke_exit_ready"):
        blockers.append({
          "type":"smoke_exit_not_ready",
          "smoke_blockers":smoke_result.get("blockers",[]),
          "smoke_errors":smoke_result.get("errors",[])
        })

    policy=load(policy_path)
    paid=policy.get("budget",{}).get("paid_research",{})
    phase=paid.get("active_phase")
    unlocked=bool(paid.get("benchmark_unlocked",False))
    if phase!="smoke":
        blockers.append({"type":"policy_phase_not_smoke","actual":phase})
    if unlocked:
        blockers.append({"type":"benchmark_already_unlocked"})

    protocol=load(protocol_path) if protocol_path.is_file() else None
    record=load(record_path) if record_path.is_file() else None
    psha=sha(protocol_path) if protocol_path.is_file() else None
    if protocol is None:
        errors.append({"type":"protocol_missing"})
    elif protocol.get("status")!="FROZEN_BEFORE_EXECUTION":
        blockers.append({"type":"protocol_not_frozen","actual":protocol.get("status")})
    elif protocol.get("schema")=="xiaoyu-e2-pilot-protocol-v2":
        if protocol.get("protocol_role")!="NONPROMOTIONAL_PILOT":
            errors.append({"type":"pilot_protocol_role_invalid"})
        if protocol.get("claim_eligibility")!="NONE":
            errors.append({"type":"pilot_claim_eligibility_must_be_none"})
        if protocol.get("scope",{}).get("confirmatory_calls_allowed") is not False:
            errors.append({"type":"pilot_confirmatory_calls_not_forbidden"})
    if record is None:
        blockers.append({"type":"freeze_record_missing"})
    else:
        if record.get("schema")!="xiaoyu-e2-protocol-freeze-record-v1":
            errors.append({"type":"freeze_record_schema"})
        if record.get("protocol_sha256")!=psha:
            blockers.append({"type":"freeze_record_protocol_hash_mismatch",
                             "recorded":record.get("protocol_sha256"),"actual":psha})
        if bool(record.get("phase_switch_performed",False)):
            blockers.append({"type":"freeze_record_already_switched"})

    paid_state=smoke_result.get("paid_phase",{})
    if int(paid_state.get("reserved_calls",0))!=0:
        blockers.append({"type":"reserved_paid_calls_present",
                         "actual":int(paid_state.get("reserved_calls",0))})

    return {
      "schema":"xiaoyu-benchmark-phase-switch-preflight-v1",
      "smoke_exit_ready":bool(smoke_result.get("smoke_exit_ready")),
      "protocol_sha256":psha,
      "policy":{"active_phase":phase,"benchmark_unlocked":unlocked},
      "paid_phase_snapshot":paid_state,
      "errors":errors,"blockers":blockers,
      "switch_allowed":not errors and not blockers,
      "e2_claim_allowed":False
    }


def acquire_lock(path):
    path=Path(path)
    fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,(str(os.getpid())+"\n").encode("ascii"))
    os.fsync(fd)
    return fd


def perform_switch(root=ROOT, smoke_result=None):
    root=Path(root);gov=root/"governance"
    lock=gov/"BENCHMARK_PHASE_SWITCH.lock"
    try:
        fd=acquire_lock(lock)
    except FileExistsError:
        return {"switched":False,"error":"phase_switch_lock_exists"}
    try:
        os.close(fd)
        check=preflight(root,smoke_result=smoke_result)
        if not check["switch_allowed"]:
            return {"switched":False,"preflight":check}

        policy_path=gov/"policy.json"
        record_path=gov/"E2_PROTOCOL_FREEZE_RECORD.json"
        protocol_path=gov/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
        unlock_path=gov/"BENCHMARK_PHASE_UNLOCK_RECORD.json"

        # Re-read under the transition lock immediately before write.
        policy=load(policy_path)
        paid=policy["budget"]["paid_research"]
        if paid.get("active_phase")!="smoke" or bool(paid.get("benchmark_unlocked",False)):
            return {"switched":False,"error":"policy_changed_after_preflight"}

        now=time.time()
        protocol_sha=sha(protocol_path)
        transition={
          "schema":"xiaoyu-benchmark-phase-unlock-v1",
          "switched_at_epoch":now,
          "from_phase":"smoke",
          "to_phase":"benchmark",
          "protocol_sha256":protocol_sha,
          "smoke_used_or_reserved_tokens":check["paid_phase_snapshot"].get("phase_used_or_reserved_tokens"),
          "smoke_remaining_tokens":check["paid_phase_snapshot"].get("phase_remaining_tokens"),
          "unknown_calls":check["paid_phase_snapshot"].get("unknown_calls"),
          "reserved_calls":check["paid_phase_snapshot"].get("reserved_calls"),
          "e2_claim_allowed":False,
          "note":"This unlock authorizes only paid execution under the frozen prospective protocol; it is not an E2/E3 scientific or product claim."
        }
        paid["active_phase"]="benchmark"
        paid["benchmark_unlocked"]=True
        paid["benchmark_unlock"]=transition
        atomic_write(policy_path,policy)

        freeze_record=load(record_path)
        freeze_record["phase_switch_performed"]=True
        freeze_record["phase_switch_at_epoch"]=now
        freeze_record["benchmark_unlock_protocol_sha256"]=protocol_sha
        atomic_write(record_path,freeze_record)
        unlock_sha=atomic_write(unlock_path,transition)
        return {"switched":True,"unlock_record":str(unlock_path),
                "unlock_record_sha256":unlock_sha,"transition":transition,
                "e2_claim_allowed":False}
    finally:
        try:lock.unlink()
        except FileNotFoundError:pass


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--switch",action="store_true",
                    help="perform the explicit paid-phase transition after preflight PASS")
    a=ap.parse_args()
    out=perform_switch() if a.switch else preflight()
    print(json.dumps(out,ensure_ascii=False,indent=2))
    ok=out.get("switched") if a.switch else out.get("switch_allowed")
    if not ok: raise SystemExit(3)


if __name__=="__main__":
    main()
