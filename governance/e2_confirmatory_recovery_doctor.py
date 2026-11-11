#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Current-state doctor for post-freeze E2 confirmatory recovery-v2.

Unlike the historical prefreeze doctor, authorized post-freeze calls are not
reported as contamination merely because they exist. This doctor never opens
benchmark dataset/gold files.
"""
from __future__ import annotations
import hashlib,json,sqlite3,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance";CAND=GOV/"confirmatory_recovery_candidate"
sys.path.insert(0,str(CAND))
import confirmatory_unknown_reconciliation_v2 as recovery

def sha(p:Path)->str:return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p:Path):
    return json.loads(Path(p).read_text("utf-8"))

def counts(scope:str)->dict:
    db=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));db.row_factory=sqlite3.Row
    try:
        rows=db.execute("select status,count(*) n from calls where phase='benchmark' and budget_scope=? group by status",(scope,)).fetchall()
    finally:db.close()
    return {str(r["status"]):int(r["n"]) for r in rows}

def latest_auditor():
    dbp=GOV/"registry.sqlite3"
    if not dbp.is_file():return None
    db=sqlite3.connect(str(dbp));db.row_factory=sqlite3.Row
    try:
        row=db.execute("""select lease_id,agent_id,family,state,workspace,claimed_at,heartbeat_at
                          from leases where family='audit.e2.confirmatory.recovery_v2_final'
                          order by claimed_at desc limit 1""").fetchone()
    finally:db.close()
    return dict(row) if row else None

def evaluate():
    errors=[];blockers=[];notes=[]
    base_freeze=GOV/"E2_CONFIRMATORY_FINAL_FREEZE_RECORD.json"
    statusp=GOV/"E2_CONFIRMATORY_EXECUTION_STATUS_20261029.json"
    manifest=GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json"
    recovery_freeze=GOV/"E2_CONFIRMATORY_RECOVERY_V2_FINAL_FREEZE_RECORD.json"
    halu_runner=CAND/"HALUMEM_CONFIRMATORY_RUNNER_V2.py"
    lme_runner=CAND/"LME_CONFIRMATORY_RUNNER_V2.py"

    if not base_freeze.is_file():errors.append({"id":"BASE_FINAL_FREEZE_MISSING"})
    else:
        bf=load(base_freeze)
        if bf.get("status")!="FINAL_EXECUTION_FREEZE_AUTHORIZED" or bf.get("confirmatory_execution_allowed") is not True:
            errors.append({"id":"BASE_FINAL_FREEZE_INVALID"})

    if not manifest.is_file():errors.append({"id":"RECOVERY_V2_MANIFEST_MISSING"})
    else:
        try:
            r,_=recovery.load_recovery("halumem",halu_runner,require_authorized=False)
            if r.get("track_disposition",{}).get("longmemeval",{}).get("recovery_execution_candidate") is not False:
                errors.append({"id":"LME_MUST_REMAIN_DISABLED_AFTER_GOLD_BOUNDARY"})
        except Exception as exc:
            errors.append({"id":"RECOVERY_V2_BINDING_INVALID","error":type(exc).__name__+":"+str(exc)})

    hc=counts("proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1")
    lc=counts("proxy:xiaoyu:e2_lme_confirmatory_v1")
    if int(hc.get("RESERVED",0))!=0:
        errors.append({"id":"HALUMEM_RESERVED_PRESENT","count":hc.get("RESERVED")})
    committed=int(hc.get("COMMITTED",0) or 0)
    unknown=int(hc.get("UNKNOWN",0) or 0)
    other={k:v for k,v in hc.items() if k not in ("COMMITTED","UNKNOWN","RESERVED") and int(v or 0)!=0}
    if committed < 68:
        errors.append({"id":"HALUMEM_COMMITTED_REGRESSED","count":committed,"minimum":68})
    if unknown != 1:
        errors.append({"id":"HALUMEM_UNKNOWN_CARDINALITY_DRIFT","count":unknown,"expected":1})
    if other:
        errors.append({"id":"HALUMEM_UNEXPECTED_LEDGER_STATUS","counts":other})
    if unknown==1:
        db=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));db.row_factory=sqlite3.Row
        try:
            u=db.execute(
                "SELECT call_id,case_id,error_class,response_text,response_sha256 FROM calls "
                "WHERE phase='benchmark' AND budget_scope=? AND status='UNKNOWN'",
                ("proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",),
            ).fetchone()
        finally:
            db.close()
        if (
            u is None
            or u["call_id"]!="api-9c5dcdb177334b69b1229d5880fe1a4f"
            or u["case_id"]!="hm-c-m-8e00ab0ec2dd-s4-t24"
            or u["error_class"]!="IncompleteRead"
            or u["response_text"] is not None
            or u["response_sha256"] is not None
        ):
            errors.append({"id":"HALUMEM_ORIGINAL_UNKNOWN_DRIFT"})
    if lc:
        errors.append({"id":"LME_PROVIDER_EXPOSURE_AFTER_INVALIDATION","counts":lc})

    st=load(statusp) if statusp.is_file() else {}
    if st.get("longmemeval",{}).get("status")!="INVALIDATED_GOLD_BOUNDARY":
        errors.append({"id":"LME_INVALIDATION_STATUS_MISSING"})
    if st.get("halumem",{}).get("status")!="BLOCKED_RESUME_INTEGRITY_AND_UNKNOWN":
        notes.append({"id":"HALUMEM_BASE_STATUS_CHANGED","status":st.get("halumem",{}).get("status")})

    aud=latest_auditor()
    if aud is None:
        blockers.append({"id":"RECOVERY_V2_INDEPENDENT_REAUDIT","status":"NOT_ASSIGNED"})
    elif aud.get("state")!="SUBMITTED":
        blockers.append({"id":"RECOVERY_V2_INDEPENDENT_REAUDIT","status":aud.get("state"),"lease_id":aud.get("lease_id")})
    else:
        notes.append({"id":"RECOVERY_V2_INDEPENDENT_REAUDIT_SUBMITTED","lease_id":aud.get("lease_id")})

    if not recovery_freeze.is_file():
        blockers.append({"id":"RECOVERY_V2_FINAL_FREEZE","status":"NOT_AUTHORIZED"})
    else:
        try:
            recovery.load_recovery("halumem",halu_runner,require_authorized=True)
            notes.append({"id":"HALUMEM_RECOVERY_V2_AUTHORIZED"})
        except Exception as exc:
            errors.append({"id":"RECOVERY_V2_FINAL_FREEZE_INVALID","error":type(exc).__name__+":"+str(exc)})

    cap_amend=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
    cap_freeze=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE_V1.json"
    if committed + unknown >= 768 and not cap_freeze.is_file():
        blockers.append({
          "id":"HALUMEM_STREAM_CAP_AMENDMENT",
          "status":"INDEPENDENT_REAUDIT_REQUIRED" if cap_amend.is_file() else "AMENDMENT_REQUIRED",
          "reason":"base final manifest hard-capped each HaluMem stream at 768 calls; safe structural count proves all 36 confirmatory streams exceed it"
        })
    elif cap_freeze.is_file():
        notes.append({"id":"HALUMEM_STREAM_CAP_AMENDMENT_FREEZE_PRESENT"})

    blockers.append({
      "id":"LONGMEMEVAL_SCIENTIFIC_DISPOSITION",
      "status":"INVALIDATED_GOLD_BOUNDARY",
      "reason":"same holdout remains disabled; no silent substitution or automatic rehabilitation"
    })

    return {
      "schema":"xiaoyu-e2-confirmatory-recovery-doctor-v1",
      "phase":"RECOVERY_V2_AUTHORIZED" if recovery_freeze.is_file() else "RECOVERY_V2_PREFREEZE",
      "base_final_freeze_sha256":sha(base_freeze) if base_freeze.is_file() else None,
      "recovery_manifest_sha256":sha(manifest) if manifest.is_file() else None,
      "halumem_recovery_runner_sha256":sha(halu_runner) if halu_runner.is_file() else None,
      "longmemeval_recovery_runner_sha256":sha(lme_runner) if lme_runner.is_file() else None,
      "ledger":{"halumem":hc,"longmemeval":lc},
      "auditor":aud,
      "errors":errors,"blockers":blockers,"notes":notes,
      "recovery_candidate_healthy":not errors,
      "halumem_recovery_execution_allowed":recovery_freeze.is_file() and not errors,
      "longmemeval_execution_allowed":False,
      "e2_claim_allowed":False,
      "historical_prefreeze_doctor_applicable":False,
    }

if __name__=="__main__":
    print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
