#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create final execution authorization for the Halu stream-cap amendment.

Requires exact independent READY evidence. Does not edit policy; policy
registration is a separate post-freeze operational step and the amended gateway
requires both the exact freeze and exact policy registration.
"""
from __future__ import annotations
import hashlib,json,sqlite3,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];GOV=ROOT/"governance"
AMEND=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
OUT=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE_V1.json"
FAMILY="audit.e2.confirmatory.halumem_stream_cap_amendment_v1"
AGENT="xy-auditor-independent-20261026-01"
DECISION="READY_FOR_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE"
SCOPE="proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))

def main():
    if OUT.exists():raise SystemExit("stream-cap amendment freeze already exists; refuse overwrite")
    a=load(AMEND);asha=sha(AMEND)
    if a.get("status")!="FROZEN_POST_ENTRY_AMENDMENT" or a.get("execution_allowed_by_this_file") is not False:
        raise SystemExit("bad amendment candidate status")
    if a.get("required_independent_family")!=FAMILY or a.get("required_independent_decision")!=DECISION:
        raise SystemExit("amendment independent contract drift")

    reg=sqlite3.connect(str(GOV/"registry.sqlite3"));reg.row_factory=sqlite3.Row
    try:
        lease=reg.execute("""select lease_id,agent_id,role,family,state,workspace from leases
                             where family=? order by claimed_at desc limit 1""",(FAMILY,)).fetchone()
        if lease is None:raise SystemExit("independent cap amendment audit missing")
        lease=dict(lease)
        if lease["agent_id"]!=AGENT or lease["role"]!="auditor" or lease["state"]!="SUBMITTED":
            raise SystemExit("independent cap amendment audit not submitted by exact auditor")
        sub=reg.execute("select submission_id,manifest_sha,receipt_sha from submissions where lease_id=? order by at desc limit 1",(lease["lease_id"],)).fetchone()
        if sub is None:raise SystemExit("cap amendment audit submission missing")
        sub=dict(sub)
    finally:
        reg.close()

    ledger=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));ledger.row_factory=sqlite3.Row
    try:
        counts={str(r["status"]):int(r["n"]) for r in ledger.execute(
          "select status,count(*) n from calls where phase='benchmark' and budget_scope=? group by status",(SCOPE,))}
    finally:
        ledger.close()
    if counts!={"COMMITTED":767,"UNKNOWN":1}:
        raise SystemExit("ledger changed after cap candidate freeze: "+repr(counts))

    ws=Path(lease["workspace"]);rp=ws/"result.json";cp=ws/"receipt.json"
    if not rp.is_file() or not cp.is_file():raise SystemExit("audit result/receipt missing")
    result=load(rp);receipt=load(cp)
    if result.get("classification")!=DECISION or result.get("decision")!=DECISION:
        raise SystemExit("independent READY decision missing")
    if result.get("amendment_sha256")!=asha:raise SystemExit("audit result amendment SHA drift")
    if result.get("findings") not in ([],None):raise SystemExit("audit has remaining findings")
    checks=result.get("checks") or {}
    required=[
      "exact_candidate_and_parent_hashes",
      "safe_scanner_uuid_role_only",
      "pilot_7900_control_exact",
      "confirmatory_counts_36_75691_2917",
      "cap_hit_boundary_no_provider_dispatch",
      "only_two_numeric_caps_change",
      "base_gateway_bytes_unchanged",
      "amended_proxy_halu_only",
      "longmemeval_remains_disabled",
      "authorization_fail_closed_without_freeze",
      "provider_calls_during_audit_zero",
      "judge_calls_during_audit_zero",
      "gold_reads_during_audit_zero",
    ]
    miss=[k for k in required if checks.get(k) is not True]
    if miss:raise SystemExit("audit READY missing required checks: "+repr(miss))
    if receipt.get("schema")!="fish-evidence-receipt-v1" or receipt.get("lease_id")!=lease["lease_id"]:
        raise SystemExit("audit receipt provenance invalid")
    if receipt.get("manifest_relative")!="result.json" or receipt.get("manifest_sha256")!=sha(rp):
        raise SystemExit("audit receipt/result binding invalid")
    if sub["manifest_sha"]!=sha(rp) or sub["receipt_sha"]!=sha(cp):
        raise SystemExit("registry submission hash drift")

    impl=a["amendment_implementation"]
    obj={
      "schema":"xiaoyu-e2-halumem-stream-cap-amendment-freeze-v1",
      "status":"STREAM_CAP_AMENDMENT_EXECUTION_AUTHORIZED",
      "created_at_epoch":time.time(),
      "execution_allowed":True,
      "e2_claim_allowed":False,
      "amendment_sha256":asha,
      "scope":SCOPE,
      "cap_delta":a["cap_delta"],
      "implementation_bindings":{
        "gateway":{"path":impl["gateway"]["path"],"sha256":impl["gateway"]["sha256"],"bytes":impl["gateway"]["bytes"]},
        "proxy":{"path":impl["proxy"]["path"],"sha256":impl["proxy"]["sha256"],"bytes":impl["proxy"]["bytes"]},
      },
      "independent_reaudit":{
        "submission_id":sub["submission_id"],"lease_id":lease["lease_id"],"agent_id":lease["agent_id"],
        "family":FAMILY,"decision":DECISION,
        "result_path":str(rp.relative_to(ROOT)).replace("\\","/"),"result_sha256":sha(rp),
        "receipt_path":str(cp.relative_to(ROOT)).replace("\\","/"),"receipt_sha256":sha(cp),
      },
      "parents":a["parents"],
      "hard_boundaries":[
        "Only HaluMem semantic_projection max_case_calls and max_calls_per_stream are amended.",
        "The dedicated amended proxy is HaluMem-only during E2 confirmatory.",
        "All case membership/prompt/schema/model/completion/UNKNOWN/recovery semantics remain inherited from exact frozen parents.",
        "LongMemEval remains disabled.",
        "This freeze does not authorize E2/E3 claim promotion."
      ]
    }
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8",newline="\n")
    print(json.dumps({"path":str(OUT.relative_to(ROOT)).replace("\\","/"),"sha256":sha(OUT),
      "amendment_sha256":asha,"caps":obj["cap_delta"],"decision":DECISION},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
