#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze XiaoYu E2 pilot execution controls before the first paid E2 call.

This freezes only the execution envelope. It never changes the frozen
scientific protocol/split and never grants an E2/E3 claim.
"""
from __future__ import annotations
import hashlib,json,sqlite3,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
POLICY=GOV/"policy.json"
OUT=GOV/"E2_PILOT_EXECUTION_FREEZE_RECORD.json"

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_lf(path,obj):
    with Path(path).open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")

def benchmark_usage():
    db=GOV/"research_api_usage.sqlite3"
    if not db.is_file():
        return {"calls":0,"used_or_reserved_tokens":0}
    con=sqlite3.connect(db);con.row_factory=sqlite3.Row
    row=con.execute("""SELECT count(*) calls,coalesce(sum(
      case when status='COMMITTED' then actual_tokens
           when status in ('RESERVED','UNKNOWN') then reserved_tokens else 0 end),0) tokens
      FROM calls WHERE phase='benchmark'""").fetchone()
    con.close()
    return {"calls":int(row["calls"] or 0),"used_or_reserved_tokens":int(row["tokens"] or 0)}

def main():
    protocol=GOV/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
    split=GOV/"E2_SPLIT_MANIFEST.json"
    prompts=GOV/"E2_PILOT_PROMPTS.json"
    manifest=GOV/"E2_PILOT_EXECUTION_MANIFEST.json"
    token_contract=GOV/"E2_TOKEN_EFFICIENCY_CONTRACT.json"
    builder=GOV/"build_e2_pilot_execution_manifest.py"
    api=GOV/"research_api.py"
    proxy=GOV/"research_api_proxy.py"
    p1c=GOV/"P1_INTEGRATION_CONTRACT.json"
    p1x=GOV/"P1_INTEGRATION_CANDIDATE.json"
    p2c=GOV/"P2_INTEGRATION_CONTRACT.json"
    self_path=Path(__file__)

    protocol_obj=load(protocol)
    manifest_obj=load(manifest)
    prompt_obj=load(prompts)
    if protocol_obj.get("status")!="FROZEN_BEFORE_EXECUTION":
        raise SystemExit("E2 scientific protocol is not frozen")
    if manifest_obj.get("status")!="FROZEN_BEFORE_FIRST_E2_PAID_CALL":
        raise SystemExit("E2 execution manifest is not frozen")
    if prompt_obj.get("status")!="FROZEN_BEFORE_FIRST_E2_PAID_CALL":
        raise SystemExit("E2 prompt freeze is not frozen")
    if manifest_obj.get("protocol_sha256")!=sha(protocol):
        raise SystemExit("execution manifest protocol hash drift")
    if manifest_obj.get("split_manifest_sha256")!=sha(split):
        raise SystemExit("execution manifest split hash drift")
    if manifest_obj.get("prompt_freeze_sha256")!=sha(prompts):
        raise SystemExit("execution manifest prompt hash drift")

    usage=benchmark_usage()
    if usage["calls"]!=0 or usage["used_or_reserved_tokens"]!=0:
        raise SystemExit("Execution freeze must occur before the first E2 paid call")

    paths={
      "protocol":protocol,"split":split,"prompt_freeze":prompts,
      "execution_manifest":manifest,"token_contract":token_contract,
      "builder":builder,"freeze_script":self_path,
      "research_api":api,"research_proxy":proxy,
      "p1_contract":p1c,"p1_candidate":p1x,"p2_contract":p2c,
    }
    record={
      "schema":"xiaoyu-e2-pilot-execution-freeze-record-v1",
      "created_at_epoch":time.time(),
      "status":"FROZEN_BEFORE_FIRST_E2_PAID_CALL",
      "hashes":{k:sha(v) for k,v in paths.items()},
      "scientific_protocol_unchanged":True,
      "scientific_split_unchanged":True,
      "prompt_semantics_unchanged_from_accepted_p1":True,
      "e2_claim_allowed":False,
      "confirmatory_calls_allowed":False,
      "benchmark_pilot_hard_cap_tokens":int(manifest_obj["benchmark_pilot_hard_cap_tokens"]),
      "paid_case_count":int(manifest_obj["paid_case_count"]),
      "track_case_counts":{k:int(v["case_count"]) for k,v in manifest_obj["tracks"].items()},
      "halumem_operation_subsample":{
        "role":manifest_obj["halumem_operation_subsample"]["role"],
        "full_pilot_extract_count":manifest_obj["halumem_operation_subsample"]["full_pilot_extract_count"],
        "full_pilot_qa_count":manifest_obj["halumem_operation_subsample"]["full_pilot_qa_count"],
        "selected_extract_count":manifest_obj["halumem_operation_subsample"]["selected_extract_count"],
        "selected_qa_count":manifest_obj["halumem_operation_subsample"]["selected_qa_count"],
        "confirmatory_users_touched":0,
        "selection_before_first_e2_paid_call":True,
      },
      "provider_state_at_freeze":{
        "benchmark_calls":usage["calls"],
        "benchmark_used_or_reserved_tokens":usage["used_or_reserved_tokens"],
      },
      "guards":[
        "execution_manifest_sha_bound_in_policy",
        "prompt_freeze_sha_bound_in_policy",
        "protocol_and_split_hash_revalidated_on_e2_manifest_load",
        "benchmark_scope_exact_allowlist",
        "pilot_case_id_exact_allowlist",
        "invariant_prefix_hash_recomputed_by_proxy",
        "per_track_completion_cap",
        "duplicate_case_check_under_begin_immediate",
        "first_two_real_cases_serial_per_scope",
        "global_paid_parallel_cap_2",
        "pilot_hard_cap_1m",
        "weekday_beijing_peak_block",
        "confirmatory_forbidden",
      ],
      "nonclaims":[
        "stable-prefix provider cache hit >=95% has not yet been empirically observed",
        "pilot quality cannot support E2 scientific acceptance",
        "confirmatory holdout remains untouched",
      ],
    }
    write_lf(OUT,record)

    policy=load(POLICY)
    e=policy.setdefault("e2_transition",{})
    e["pilot_execution_manifest"]="governance/E2_PILOT_EXECUTION_MANIFEST.json"
    e["pilot_execution_manifest_sha256"]=sha(manifest)
    e["pilot_prompt_freeze"]="governance/E2_PILOT_PROMPTS.json"
    e["pilot_prompt_freeze_sha256"]=sha(prompts)
    e["pilot_execution_freeze_record"]="governance/E2_PILOT_EXECUTION_FREEZE_RECORD.json"
    e["pilot_execution_freeze_record_sha256"]=sha(OUT)
    write_lf(POLICY,policy)

    print(json.dumps({
      "record":str(OUT),
      "record_sha256":sha(OUT),
      "manifest_sha256":sha(manifest),
      "prompt_freeze_sha256":sha(prompts),
      "paid_case_count":record["paid_case_count"],
      "benchmark_calls_at_freeze":usage["calls"],
      "benchmark_tokens_at_freeze":usage["used_or_reserved_tokens"],
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
