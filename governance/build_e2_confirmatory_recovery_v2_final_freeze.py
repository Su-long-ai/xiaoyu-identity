#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build recovery-v2 final freeze only from an exact independent READY result.

No provider, judge, benchmark dataset or gold access occurs here.
"""
from __future__ import annotations
import hashlib,json,sqlite3,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];GOV=ROOT/"governance"
MAN=GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json"
OUT=GOV/"E2_CONFIRMATORY_RECOVERY_V2_FINAL_FREEZE_RECORD.json"
FAMILY="audit.e2.confirmatory.recovery_v2_final"
AGENT="xy-auditor-independent-20261026-01"
DECISION="READY_FOR_RECOVERY_V2_FREEZE"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))
def ledger_counts(scope):
    db=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));db.row_factory=sqlite3.Row
    try:rows=db.execute("select status,count(*) n from calls where phase='benchmark' and budget_scope=? group by status",(scope,)).fetchall()
    finally:db.close()
    return {str(r["status"]):int(r["n"]) for r in rows}

def main():
    if OUT.exists():raise SystemExit("recovery-v2 final freeze already exists; refuse overwrite")
    m=load(MAN);msha=sha(MAN)
    if m.get("status")!="PREFREEZE_RECOVERY_V2_CANDIDATE":raise SystemExit("bad recovery manifest status")
    if m.get("required_independent_family")!=FAMILY or m.get("required_independent_decision")!=DECISION:
        raise SystemExit("recovery manifest audit contract drift")
    if m["track_disposition"]["halumem"].get("recovery_execution_candidate") is not True:
        raise SystemExit("HaluMem not eligible in manifest")
    if m["track_disposition"]["longmemeval"].get("recovery_execution_candidate") is not False:
        raise SystemExit("LongMemEval must remain disabled")
    if ledger_counts(m["track_scopes"]["halumem"])!={"COMMITTED":68,"UNKNOWN":1}:
        raise SystemExit("HaluMem ledger drift before recovery freeze")
    if ledger_counts(m["track_scopes"]["longmemeval"]):
        raise SystemExit("LongMemEval provider exposure detected")

    db=sqlite3.connect(str(GOV/"registry.sqlite3"));db.row_factory=sqlite3.Row
    try:
        lease=db.execute("""select lease_id,agent_id,role,family,state,workspace from leases
                            where family=? order by claimed_at desc limit 1""",(FAMILY,)).fetchone()
        if lease is None:raise SystemExit("independent recovery-v2 audit lease missing")
        lease=dict(lease)
        if lease["state"]!="SUBMITTED" or lease["agent_id"]!=AGENT or lease["role"]!="auditor":
            raise SystemExit("independent recovery-v2 audit not submitted by exact auditor")
        sub=db.execute("""select submission_id,manifest_sha,receipt_sha from submissions
                          where lease_id=? order by at desc limit 1""",(lease["lease_id"],)).fetchone()
        if sub is None:raise SystemExit("independent recovery-v2 submission missing")
        sub=dict(sub)
    finally:db.close()

    ws=Path(lease["workspace"]);rp=ws/"result.json";cp=ws/"receipt.json"
    if not rp.is_file() or not cp.is_file():raise SystemExit("independent recovery-v2 result/receipt missing")
    result=load(rp);receipt=load(cp)
    if result.get("decision")!=DECISION or result.get("classification")!=DECISION:
        raise SystemExit("independent recovery-v2 READY decision missing")
    if result.get("manifest_sha256")!=msha:raise SystemExit("audit result manifest SHA drift")
    if result.get("findings") not in ([],None):raise SystemExit("audit result still has findings")
    checks=result.get("checks") or {}
    required_checks=[
      "exact_manifest_and_bound_files","legacy_68_request_response_bindings_exact",
      "legacy_unknown_no_retry_no_semantic_state","checkpoint_crash_recovery_fail_closed",
      "new_call_request_intent_pre_dispatch","old_runtime_immutable",
      "halumem_only_track_authorized","longmemeval_remains_disabled",
      "judge_calibration_post_seal_12_of_12","provider_calls_during_audit_zero",
      "judge_calls_during_audit_zero","gold_reads_during_audit_zero",
    ]
    missing=[k for k in required_checks if checks.get(k) is not True]
    if missing:raise SystemExit("audit READY missing required checks: "+repr(missing))
    if receipt.get("schema")!="fish-evidence-receipt-v1" or receipt.get("lease_id")!=lease["lease_id"]:
        raise SystemExit("audit receipt provenance invalid")
    if receipt.get("manifest_relative")!="result.json" or receipt.get("manifest_sha256")!=sha(rp):
        raise SystemExit("audit receipt/result binding invalid")
    if sub["manifest_sha"]!=sha(rp) or sub["receipt_sha"]!=sha(cp):
        raise SystemExit("registry submission hashes do not bind audit result/receipt")

    obj={
      "schema":"xiaoyu-e2-confirmatory-recovery-v2-final-freeze-v1",
      "status":"RECOVERY_V2_FINAL_EXECUTION_FREEZE_AUTHORIZED",
      "created_at_epoch":time.time(),
      "recovery_execution_allowed":True,"e2_claim_allowed":False,
      "recovery_manifest_sha256":msha,
      "authorized_tracks":["halumem"],
      "disabled_tracks":{"longmemeval":"INVALIDATED_GOLD_BOUNDARY"},
      "runner_bindings":{k:v["sha256"] for k,v in m["runners"].items()},
      "independent_reaudit":{
        "submission_id":sub["submission_id"],"lease_id":lease["lease_id"],"agent_id":lease["agent_id"],
        "family":FAMILY,"decision":DECISION,
        "result_path":str(rp.relative_to(ROOT)).replace("\\","/"),"result_sha256":sha(rp),
        "receipt_path":str(cp.relative_to(ROOT)).replace("\\","/"),"receipt_sha256":sha(cp),
        "reaudit_manifest_path":str(MAN.relative_to(ROOT)).replace("\\","/"),"reaudit_manifest_sha256":msha,
      },
      "hard_boundaries":[
        "HaluMem only; LongMemEval remains disabled.",
        "Legacy UNKNOWN is TRANSPORT_ABSTAIN_NO_RETRY and durable UNKNOWN is never mutated.",
        "Legacy COMMITTED reuse requires original request_messages_sha256 and response SHA match.",
        "New calls require immutable pre-dispatch request intent.",
        "Session resume restores only the progress-bound immutable SQLite checkpoint.",
        "Fresh qwen3.8-flash 12/12 calibration remains after prediction seal and before gold scoring.",
        "This freeze does not authorize E2/E3 claim promotion."
      ]
    }
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8",newline="\n")
    print(json.dumps({"path":str(OUT.relative_to(ROOT)).replace("\\","/"),"sha256":sha(OUT),
                      "authorized_tracks":obj["authorized_tracks"],"decision":DECISION},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
