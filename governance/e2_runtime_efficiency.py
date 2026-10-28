#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-launch E2 runtime efficiency report.

This is intentionally separate from the pre-first-paid-call freeze contract.
It never makes provider calls and never changes the frozen pilot protocol.
"""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
POLICY=GOV/"policy.json"
RUNTIME_POLICY=GOV/"E2_RUNTIME_EFFICIENCY_POLICY.json"
DB=GOV/"research_api_usage.sqlite3"

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def price(policy):
    return policy["budget"]["paid_research"]["pricing_cny_per_million"]

def cost(hit,miss,out,p,band):
    return (hit*float(p["cache_hit"][band])+
            miss*float(p["cache_miss"][band])+
            out*float(p["output"][band]))/1_000_000.0

def evaluate(root=ROOT):
    root=Path(root);gov=root/"governance"
    policy=load(gov/"policy.json")
    runtime_path=gov/"E2_RUNTIME_EFFICIENCY_POLICY.json"
    runtime_policy=load(runtime_path)
    actual_runtime_sha=hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    expected_runtime_sha=str(
        (policy.get("e2_transition") or {}).get("runtime_efficiency_policy_sha256") or "")
    if actual_runtime_sha!=expected_runtime_sha:
        raise RuntimeError(
            "E2 runtime efficiency policy hash drift: "
            f"{actual_runtime_sha} != {expected_runtime_sha}")
    pricing=price(policy)
    db=gov/"research_api_usage.sqlite3"
    rows=[]
    if db.is_file():
        con=sqlite3.connect(db);con.row_factory=sqlite3.Row
        try:
            rows=con.execute("""SELECT budget_scope,case_id,status,
              prompt_tokens,completion_tokens,actual_tokens,
              cache_hit_tokens,cache_miss_tokens
              FROM calls WHERE phase='benchmark' AND status='COMMITTED'
              ORDER BY created_at""").fetchall()
        finally:
            con.close()

    scopes={}
    for r in rows:
        scope=str(r["budget_scope"] or "")
        d=scopes.setdefault(scope,{"committed_cases":0,"prompt_tokens":0,
            "completion_tokens":0,"total_tokens":0,"cache_hit_tokens":0,
            "cache_miss_tokens":0,"case_ids":[]})
        d["committed_cases"]+=1
        d["case_ids"].append(str(r["case_id"] or ""))
        d["prompt_tokens"]+=int(r["prompt_tokens"] or 0)
        d["completion_tokens"]+=int(r["completion_tokens"] or 0)
        d["total_tokens"]+=int(r["actual_tokens"] or 0)
        d["cache_hit_tokens"]+=int(r["cache_hit_tokens"] or 0)
        d["cache_miss_tokens"]+=int(r["cache_miss_tokens"] or 0)

    for scope,d in scopes.items():
        n=max(1,d["committed_cases"])
        denom=d["cache_hit_tokens"]+d["cache_miss_tokens"]
        d["whole_prompt_cache_hit_rate_observational"]=(
            round(d["cache_hit_tokens"]/denom,6) if denom else None)
        d["cache_miss_tokens_per_committed_case"]=round(d["cache_miss_tokens"]/n,2)
        d["total_tokens_per_committed_case"]=round(d["total_tokens"]/n,2)
        d["completion_tokens_per_committed_case"]=round(d["completion_tokens"]/n,2)
        off=cost(d["cache_hit_tokens"],d["cache_miss_tokens"],
                 d["completion_tokens"],pricing,"off_peak")
        peak=cost(d["cache_hit_tokens"],d["cache_miss_tokens"],
                  d["completion_tokens"],pricing,"peak")
        d["off_peak_cny_total"]=round(off,9)
        d["off_peak_cny_per_committed_case"]=round(off/n,9)
        d["peak_cny_total"]=round(peak,9)
        d["peak_cny_per_committed_case"]=round(peak/n,9)

    lme_scope="proxy:xiaoyu:e2_lme_answer_pilot"
    lme=scopes.get(lme_scope,{"committed_cases":0})
    return {
      "schema":"xiaoyu-e2-runtime-efficiency-report-v1",
      "postlaunch_policy_status":runtime_policy["status"],
      "runtime_policy_sha256":actual_runtime_sha,
      "legacy_95pct_cache_target_for_longmemeval":
        runtime_policy["legacy_cache_target"]["status_for_longmemeval"],
      "longmemeval_cache_classification":
        runtime_policy["longmemeval_cache_geometry"]["classification"],
      "current_pilot_prompt_mutation_for_cache_forbidden":
        runtime_policy["rules"]["current_pilot_prompt_mutation_for_cache_forbidden"],
      "batching_in_current_pilot_forbidden":
        runtime_policy["rules"]["batching_in_current_pilot_forbidden"],
      "primary_runtime_metrics":runtime_policy["primary_runtime_metrics"],
      "scopes":scopes,
      "longmemeval":{
        "committed_cases":lme.get("committed_cases",0),
        "cache_miss_tokens_per_case":lme.get("cache_miss_tokens_per_committed_case"),
        "total_tokens_per_case":lme.get("total_tokens_per_committed_case"),
        "off_peak_cny_per_case":lme.get("off_peak_cny_per_committed_case"),
        "whole_prompt_cache_hit_rate_observational":
            lme.get("whole_prompt_cache_hit_rate_observational"),
      },
      "correctness_gate_changed":False,
      "scientific_protocol_changed":False,
      "provider_calls":0,
    }

def main():
    print(json.dumps(evaluate(),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
