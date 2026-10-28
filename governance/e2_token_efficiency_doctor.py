#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit E2 pilot token/cost execution invariants without making provider calls."""
from __future__ import annotations
import argparse,hashlib,json,sqlite3,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
sys.path.insert(0,str(GOV))
import build_e2_pilot_execution_manifest as builder

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def hobj(x): return hashlib.sha256(canon(x).encode("utf-8")).hexdigest()
def peak(ts):
    dt=datetime.fromtimestamp(float(ts),timezone(timedelta(hours=8)))
    return dt.weekday()<5 and ((9<=dt.hour<12) or (14<=dt.hour<18))

def evaluate(root=ROOT):
    root=Path(root);gov=root/"governance"
    policy=load(gov/"policy.json")
    protocol=gov/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
    split_path=gov/"E2_SPLIT_MANIFEST.json"
    manifest_path=gov/"E2_PILOT_EXECUTION_MANIFEST.json"
    prompt_path=gov/"E2_PILOT_PROMPTS.json"
    contract_path=gov/"E2_TOKEN_EFFICIENCY_CONTRACT.json"
    impl_paths={
      "token_contract":contract_path,
      "builder":gov/"build_e2_pilot_execution_manifest.py",
      "freeze_script":gov/"freeze_e2_pilot_execution.py",
      "research_api":gov/"research_api.py",
      "research_proxy":gov/"research_api_proxy.py",
      "pilot_runner":gov/"e2_pilot_runner.py",
      "token_doctor":gov/"e2_token_efficiency_doctor.py",
    }
    e=policy.get("e2_transition") or {}
    paid=policy.get("budget",{}).get("paid_research",{})
    errors=[];warnings=[]

    manifest=load(manifest_path)
    split=load(split_path)
    prompts=load(prompt_path)
    contract=load(contract_path)
    protocol_sha=sha(protocol);split_sha=sha(split_path);manifest_sha=sha(manifest_path)
    prompt_sha=sha(prompt_path)
    freeze_rel=e.get("pilot_execution_freeze_record")
    freeze_path=root/str(freeze_rel) if freeze_rel else None
    freeze_record=load(freeze_path) if freeze_path and freeze_path.is_file() else None
    freeze_sha=sha(freeze_path) if freeze_path and freeze_path.is_file() else None

    def check(ok,typ,**extra):
        if not ok: errors.append({"type":typ,**extra})

    check(e.get("current_stage")=="E2_PILOT","stage_not_e2_pilot",actual=e.get("current_stage"))
    check(paid.get("active_phase")=="benchmark","paid_phase_not_benchmark",actual=paid.get("active_phase"))
    check(bool(paid.get("benchmark_unlocked")),"benchmark_not_unlocked")
    check(manifest.get("status")=="FROZEN_BEFORE_FIRST_E2_PAID_CALL",
          "execution_manifest_status",actual=manifest.get("status"))
    check(manifest.get("protocol_sha256")==protocol_sha,"protocol_hash_drift")
    check(manifest.get("split_manifest_sha256")==split_sha,"split_hash_drift")
    check(manifest.get("prompt_freeze_sha256")==prompt_sha,"prompt_freeze_hash_drift")
    check(e.get("pilot_prompt_freeze_sha256")==prompt_sha,
          "policy_prompt_freeze_hash_drift",
          recorded=e.get("pilot_prompt_freeze_sha256"),actual=prompt_sha)
    check(e.get("pilot_execution_manifest_sha256")==manifest_sha,
          "policy_execution_manifest_hash_drift",
          recorded=e.get("pilot_execution_manifest_sha256"),actual=manifest_sha)
    check(contract.get("protocol_sha256")==protocol_sha,"token_contract_protocol_hash_drift")
    check(freeze_record is not None,"execution_freeze_record_missing")
    if freeze_record is not None:
        check(freeze_record.get("schema")=="xiaoyu-e2-pilot-execution-freeze-record-v1",
              "execution_freeze_record_schema")
        check(freeze_record.get("status")=="FROZEN_BEFORE_FIRST_E2_PAID_CALL",
              "execution_freeze_record_status",actual=freeze_record.get("status"))
        check(e.get("pilot_execution_freeze_record_sha256")==freeze_sha,
              "execution_freeze_record_hash_drift",
              recorded=e.get("pilot_execution_freeze_record_sha256"),actual=freeze_sha)
        hashes=freeze_record.get("hashes") or {}
        check(hashes.get("protocol")==protocol_sha,"freeze_record_protocol_hash_drift")
        check(hashes.get("split")==split_sha,"freeze_record_split_hash_drift")
        check(hashes.get("prompt_freeze")==prompt_sha,"freeze_record_prompt_hash_drift")
        check(hashes.get("execution_manifest")==manifest_sha,
              "freeze_record_execution_manifest_hash_drift")
        for name,path in impl_paths.items():
            actual=sha(path) if path.is_file() else None
            check(hashes.get(name)==actual,
                  "freeze_record_implementation_hash_drift",
                  component=name,recorded=hashes.get(name),actual=actual)
        check(int(freeze_record.get("paid_case_count") or -1)==int(manifest.get("paid_case_count") or -2),
              "freeze_record_paid_case_count_drift")
        check(bool(freeze_record.get("e2_claim_allowed")) is False,
              "freeze_record_e2_claim_must_remain_false")
    pilot_cap=int(manifest.get("benchmark_pilot_hard_cap_tokens") or 0)
    check(pilot_cap==int(e.get("pilot_hard_cap_tokens") or 0) and pilot_cap>0,
          "pilot_cap_mismatch",manifest=pilot_cap,policy=e.get("pilot_hard_cap_tokens"))

    tracks=manifest.get("tracks") or {}
    scopes=[];all_ids=[];prefix_errors=[]
    for name,t in tracks.items():
        scope=t.get("scope");scopes.append(scope)
        ids=[str(x) for x in t.get("case_ids",[])]
        all_ids.extend(ids)
        check(t.get("case_count")==len(ids),"track_case_count_mismatch",track=name)
        check(isinstance(scope,str) and scope.startswith("proxy:xiaoyu:e2_"),
              "track_scope_not_e2_xiaoyu",track=name,scope=scope)
        expected=hobj(t.get("invariant_prefix_messages"))
        if expected!=t.get("invariant_prefix_sha256"):
            prefix_errors.append(name)
        check(int(t.get("max_completion_tokens") or 0)>0,
              "track_completion_cap_missing",track=name)
        check(t.get("response_format")=={"type":"json_object"},
              "track_response_format_not_json_object",track=name)
    check(len(scopes)==len(set(scopes)),"duplicate_track_scope")
    check(len(all_ids)==len(set(all_ids)),"duplicate_manifest_case_id")
    check(not prefix_errors,"prefix_hash_drift",tracks=prefix_errors)

    # Exact split-first membership recomputation.
    expected_lme={f"lme-a-{int(i):03d}" for i in split["longmemeval"]["pilot_indices"]}
    actual_lme=set(tracks["longmemeval_answer"]["case_ids"])
    check(actual_lme==expected_lme,"longmemeval_pilot_membership_drift",
          missing=len(expected_lme-actual_lme),extra=len(actual_lme-expected_lme))
    expected_h=builder.halu_pilot_cases(split)
    check(set(tracks["halumem_extract"]["case_ids"])==set(expected_h["extract"]),
          "halumem_extract_pilot_membership_drift")
    check(set(tracks["halumem_qa"]["case_ids"])==set(expected_h["qa"]),
          "halumem_qa_pilot_membership_drift")

    db=gov/"research_api_usage.sqlite3"
    runtime={
      "benchmark_calls":0,"pilot_used_or_reserved_tokens":0,
      "pilot_remaining_tokens":pilot_cap,"outside_scope_calls":[],
      "missing_case_id_calls":[],"wrong_case_calls":[],"prefix_mismatch_calls":[],
      "duplicate_case_ids":[],"completion_cap_violations":[],
      "missing_response_receipts":[],"response_receipt_hash_mismatches":[],
      "peak_calls":[],"reserved_calls":[],"unknown_calls":[],"scopes":{}
    }
    if db.is_file():
        con=sqlite3.connect(db);con.row_factory=sqlite3.Row
        cols={r[1] for r in con.execute("pragma table_info(calls)")}
        required_cols={"case_id","prompt_prefix_sha256","response_text","response_sha256"}
        if not required_cols.issubset(cols):
            errors.append({"type":"usage_db_missing_e2_columns",
                           "missing":sorted(required_cols-cols)})
        else:
            rows=con.execute("select * from calls where phase='benchmark' order by created_at").fetchall()
            runtime["benchmark_calls"]=len(rows)
            by_scope={t["scope"]:(name,t) for name,t in tracks.items()}
            allowed_case={t["scope"]:set(t["case_ids"]) for t in tracks.values()}
            for r in rows:
                rd=dict(r);scope=rd.get("budget_scope")
                if rd["status"]=="COMMITTED": used=int(rd.get("actual_tokens") or 0)
                elif rd["status"] in ("RESERVED","UNKNOWN"): used=int(rd.get("reserved_tokens") or 0)
                else: used=0
                runtime["pilot_used_or_reserved_tokens"]+=used
                if scope not in by_scope:
                    runtime["outside_scope_calls"].append(rd["call_id"]);continue
                name,t=by_scope[scope]
                cid=rd.get("case_id")
                if not cid: runtime["missing_case_id_calls"].append(rd["call_id"])
                elif cid not in allowed_case[scope]: runtime["wrong_case_calls"].append(rd["call_id"])
                if rd.get("prompt_prefix_sha256")!=t["invariant_prefix_sha256"]:
                    runtime["prefix_mismatch_calls"].append(rd["call_id"])
                if int(rd.get("completion_tokens") or 0)>int(t["max_completion_tokens"]):
                    runtime["completion_cap_violations"].append(rd["call_id"])
                if rd["status"]=="COMMITTED":
                    body=rd.get("response_text");digest=rd.get("response_sha256")
                    if not isinstance(body,str) or not digest:
                        runtime["missing_response_receipts"].append(rd["call_id"])
                    else:
                        actual=hashlib.sha256(body.encode("utf-8")).hexdigest()
                        if actual!=digest:
                            runtime["response_receipt_hash_mismatches"].append(rd["call_id"])
                if peak(rd["created_at"]):runtime["peak_calls"].append(rd["call_id"])
                if rd["status"]=="RESERVED":runtime["reserved_calls"].append(rd["call_id"])
                if rd["status"]=="UNKNOWN":runtime["unknown_calls"].append(rd["call_id"])
            dup=con.execute("""select case_id,count(*) n from calls
              where phase='benchmark' and case_id is not null
                and status in ('RESERVED','COMMITTED','UNKNOWN')
              group by case_id having count(*)>1""").fetchall()
            runtime["duplicate_case_ids"]=[dict(x) for x in dup]
            for scope,(name,t) in by_scope.items():
                q=con.execute("""select count(*) calls,
                  sum(case when status='COMMITTED' then 1 else 0 end) committed,
                  coalesce(sum(case when status='COMMITTED' then prompt_tokens else 0 end),0) prompt,
                  coalesce(sum(case when status='COMMITTED' then completion_tokens else 0 end),0) completion,
                  coalesce(sum(case when status='COMMITTED' then cache_hit_tokens else 0 end),0) hit,
                  coalesce(sum(case when status='COMMITTED' then cache_miss_tokens else 0 end),0) miss
                  from calls where phase='benchmark' and budget_scope=?""",(scope,)).fetchone()
                d={k:int(q[k] or 0) for k in q.keys()}
                den=d["hit"]+d["miss"]
                d["cache_hit_rate"]=round(d["hit"]/den,6) if den else None
                d["avg_cache_miss_per_committed"]=round(d["miss"]/d["committed"],2) if d["committed"] else None
                d["avg_completion_per_committed"]=round(d["completion"]/d["committed"],2) if d["committed"] else None
                d["max_completion_tokens"]=int(t["max_completion_tokens"])
                runtime["scopes"][scope]=d
        con.close()

    runtime["pilot_remaining_tokens"]=max(0,pilot_cap-runtime["pilot_used_or_reserved_tokens"])
    for key in ("outside_scope_calls","missing_case_id_calls","wrong_case_calls",
                "prefix_mismatch_calls","duplicate_case_ids","completion_cap_violations",
                "missing_response_receipts","response_receipt_hash_mismatches","peak_calls"):
        check(not runtime[key],"runtime_"+key,actual=runtime[key][:10] if isinstance(runtime[key],list) else runtime[key])
    check(runtime["pilot_used_or_reserved_tokens"]<=pilot_cap,
          "pilot_token_cap_exceeded",used=runtime["pilot_used_or_reserved_tokens"],cap=pilot_cap)
    if runtime["reserved_calls"]:
        warnings.append({"type":"reserved_calls_in_flight","calls":runtime["reserved_calls"]})
    if runtime["unknown_calls"]:
        warnings.append({"type":"benchmark_unknown_calls_fail_closed","calls":runtime["unknown_calls"]})

    return {
      "schema":"xiaoyu-e2-token-efficiency-doctor-v1",
      "stage":e.get("current_stage"),
      "protocol_sha256":protocol_sha,
      "split_sha256":split_sha,
      "prompt_freeze_sha256":prompt_sha,
      "execution_manifest_sha256":manifest_sha,
      "execution_freeze_record_sha256":freeze_sha,
      "pilot_hard_cap_tokens":pilot_cap,
      "manifest_paid_case_count":len(all_ids),
      "track_case_counts":{k:v.get("case_count") for k,v in tracks.items()},
      "prefix_byte_stability_enforced":not prefix_errors,
      "stable_prefix_cache_target":contract.get("targets",{}).get("stable_prefix_cache_hit_rate"),
      "stable_prefix_cache_target_note":"Provider telemetry exposes prompt hit/miss totals, not prefix-token denominator; exact byte-prefix hash is enforced, provider hit rate remains observational.",
      "runtime":runtime,
      "errors":errors,"warnings":warnings,
      "healthy":not errors,
      "pilot_execution_ready":not errors and not runtime["reserved_calls"] and not runtime["unknown_calls"],
      "e2_claim_allowed":False,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--require-ready",action="store_true")
    args=ap.parse_args()
    out=evaluate()
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if args.require_ready and not out["pilot_execution_ready"]:
        raise SystemExit(3)

if __name__=="__main__":main()
