#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Activate the independently frozen HaluMem stream-cap amendment.

Default is dry-run. --apply performs one atomic policy.json replacement only if
all exact amendment/freeze/audit bindings are valid. This is operational budget
activation, not a scientific protocol mutation.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
POLICY=GOV/"policy.json"
AMEND=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
FREEZE=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE_V1.json"
SCOPE="proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"
EXPECTED_AMEND_SHA="f1a5dbbf40c7391017cfe5781f7504978d0277899a20b313dd08c798a0217b84"
READY="READY_FOR_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE"

def sha(p:Path)->str:return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p:Path):return json.loads(Path(p).read_text("utf-8"))

def validate()->tuple[dict,dict,dict]:
    if not AMEND.is_file():raise SystemExit("amendment missing")
    if sha(AMEND)!=EXPECTED_AMEND_SHA:raise SystemExit("amendment SHA drift")
    if not FREEZE.is_file():raise SystemExit("amendment final freeze missing")
    a=load(AMEND);f=load(FREEZE);p=load(POLICY)
    if f.get("schema")!="xiaoyu-e2-halumem-stream-cap-amendment-freeze-v1":
        raise SystemExit("bad amendment freeze schema")
    if f.get("status")!="STREAM_CAP_AMENDMENT_EXECUTION_AUTHORIZED" or f.get("execution_allowed") is not True:
        raise SystemExit("amendment freeze not authorized")
    if f.get("amendment_sha256")!=EXPECTED_AMEND_SHA:
        raise SystemExit("freeze/amendment binding drift")
    audit=f.get("independent_reaudit") or {}
    if audit.get("agent_id")!="xy-auditor-independent-20261026-01" or audit.get("decision")!=READY:
        raise SystemExit("independent amendment READY binding missing")
    if f.get("scope")!=SCOPE:
        raise SystemExit("freeze scope drift")
    delta=f.get("cap_delta") or {}
    if (
      int(delta.get("old_max_case_calls") or -1)!=10000
      or int(delta.get("new_max_case_calls") or -1)!=75691
      or int(delta.get("old_max_calls_per_stream") or -1)!=768
      or int(delta.get("new_max_calls_per_stream") or -1)!=2917
    ):
        raise SystemExit("freeze cap delta drift")
    b=p.get("budget",{}).get("paid_research") or {}
    if int(b.get("benchmark_max_tokens") or -1)!=95000000 or int(b.get("max_total_tokens") or -1)!=100000000:
        raise SystemExit("owner authorized benchmark/total budget drift")
    return a,f,p

def desired_policy(a:dict,f:dict,p:dict)->dict:
    q=copy.deepcopy(p)
    e2=q.setdefault("e2_transition",{})
    rel=str(AMEND.relative_to(ROOT)).replace("\\","/")
    row={"path":rel,"sha256":EXPECTED_AMEND_SHA}
    arr=[x for x in (e2.get("execution_amendments") or []) if not (isinstance(x,dict) and x.get("path")==rel)]
    arr.append(row)
    e2["execution_amendments"]=arr
    frel=str(FREEZE.relative_to(ROOT)).replace("\\","/")
    e2["halumem_stream_cap_amendment_freeze"]=frel
    e2["halumem_stream_cap_amendment_freeze_sha256"]=sha(FREEZE)

    guard=q["budget"]["paid_research"]["runtime_guard"]
    ov=guard["scope_overrides"][SCOPE]
    # Keep rolling circuit breakers unchanged; only the full-run epoch budget
    # is raised enough for the independently counted 75,691 exact cases.
    if int(ov.get("rolling_call_cap") or -1)!=1000:
        raise SystemExit("unexpected Halu rolling_call_cap; expected prior soft-throttle 1000")
    if int(ov.get("rolling_raw_token_cap") or -1)!=900000:
        raise SystemExit("unexpected Halu rolling_raw_token_cap")
    if int(ov.get("rolling_cache_miss_cap") or -1)!=650000:
        raise SystemExit("unexpected Halu rolling_cache_miss_cap")
    if int(ov.get("rolling_output_token_cap") or -1)!=300000:
        raise SystemExit("unexpected Halu rolling_output_token_cap")

    ov["epoch_call_cap"]=75691
    ov["epoch_raw_token_cap"]=90000000
    ov["epoch_cache_miss_cap"]=45000000
    # 8M output cap already exceeds observed ~3.2M projection; keep it.
    if int(ov.get("epoch_output_token_cap") or -1)!=8000000:
        raise SystemExit("unexpected Halu epoch_output_token_cap")
    q["budget"]["paid_research"]["budget_note"]=(
      "Owner authorized 100M raw tokens. E2 HaluMem recovery-v2 stream-cap amendment is independently "
      "frozen; operational epoch caps allow the exact 75,691 frozen semantic cases while rolling "
      "token/call circuit breakers remain unchanged. LongMemEval remains disabled."
    )
    return q

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    a,f,p=validate()
    q=desired_policy(a,f,p)
    before=sha(POLICY)
    raw=(json.dumps(q,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    after=hashlib.sha256(raw).hexdigest()
    report={
      "ok":True,"mode":"apply" if args.apply else "dry-run",
      "policy_before_sha256":before,"policy_after_sha256":after,
      "amendment_sha256":EXPECTED_AMEND_SHA,"freeze_sha256":sha(FREEZE),
      "scope":SCOPE,
      "soft_budget":{
        "rolling_call_cap":1000,"rolling_raw_token_cap":900000,
        "rolling_cache_miss_cap":650000,"rolling_output_token_cap":300000,
        "epoch_call_cap":75691,"epoch_raw_token_cap":90000000,
        "epoch_cache_miss_cap":45000000,"epoch_output_token_cap":8000000,
      },
      "longmemeval_enabled":False,
    }
    if args.apply:
        fd,tmp=tempfile.mkstemp(prefix="policy-",suffix=".json.tmp",dir=str(GOV))
        os.close(fd);tp=Path(tmp)
        try:
            tp.write_bytes(raw)
            # Parse once more before atomic replace.
            json.loads(tp.read_text("utf-8"))
            os.replace(tp,POLICY)
        finally:
            try:tp.unlink()
            except FileNotFoundError:pass
        if sha(POLICY)!=after:raise SystemExit("atomic policy activation SHA mismatch")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
