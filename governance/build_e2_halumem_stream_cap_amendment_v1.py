#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the post-entry HaluMem confirmatory stream-cap amendment candidate.

Reads only structural-safe count metadata, frozen manifests/hashes and durable
ledger/request-intent metadata. Never reads benchmark gold or calls a provider.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
OUT=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
BASE_MAN=GOV/"E2_CONFIRMATORY_EXECUTION_MANIFEST_CANDIDATE.json"
BASE_FREEZE=GOV/"E2_CONFIRMATORY_FINAL_FREEZE_RECORD.json"
REC_MAN=GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json"
REC_FREEZE=GOV/"E2_CONFIRMATORY_RECOVERY_V2_FINAL_FREEZE_RECORD.json"
SAFE=GOV/"lead_workspaces"/"halumem_stream_shape_20261029"/"HALUMEM_SAFE_STREAM_COUNTS.json"
SCANNER=GOV/"lead_workspaces"/"halumem_stream_shape_20261029"/"count_safe_roles.py"
GATEWAY=GOV/"confirmatory_stream_cap_gateway_v1.py"
PROXY=GOV/"research_api_proxy_recovery_cap_v1.py"
BASE_API=GOV/"research_api.py"
BASE_PROXY=GOV/"research_api_proxy.py"
RUNTIME=GOV/"halumem_confirmatory_runtime_v2"
SCOPE="proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"

def sha(p:Path)->str:return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p:Path):return json.loads(Path(p).read_text("utf-8"))
def bind(p:Path)->dict:
    return {"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size}

def main():
    for p in (BASE_MAN,BASE_FREEZE,REC_MAN,REC_FREEZE,SAFE,SCANNER,GATEWAY,PROXY,BASE_API,BASE_PROXY):
        if not p.is_file():raise SystemExit("missing required file: "+str(p))
    base=load(BASE_MAN);safe=load(SAFE)
    track=(base.get("tracks") or {}).get("halumem_semantic_projection") or {}
    if int(track.get("max_case_calls") or -1)!=10000 or int(track.get("max_calls_per_stream") or -1)!=768:
        raise SystemExit("base cap ancestry drift")
    controls=safe.get("controls") or {};cs=safe.get("confirmatory") or {}
    if controls.get("pilot_control_pass") is not True or int(controls.get("pilot_user_turns_observed") or -1)!=7900:
        raise SystemExit("safe structural counter pilot control failed")
    if int(cs.get("streams") or -1)!=36 or int(cs.get("total_semantic_calls_required") or -1)!=75691:
        raise SystemExit("safe confirmatory total drift")
    if int(cs.get("max_semantic_calls_per_stream") or -1)!=2917:
        raise SystemExit("safe confirmatory stream max drift")
    if int(cs.get("streams_over_old_768_cap") or -1)!=36:
        raise SystemExit("old 768 cap is not falsified on all streams")

    db=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));db.row_factory=sqlite3.Row
    try:
        rows=db.execute("select status,count(*) n from calls where phase='benchmark' and budget_scope=? group by status",(SCOPE,)).fetchall()
        counts={str(r["status"]):int(r["n"]) for r in rows}
        if counts!={"COMMITTED":767,"UNKNOWN":1}:
            raise SystemExit("cap-hit ledger boundary drift: "+repr(counts))
        u=db.execute("select call_id,case_id,error_class,response_text,response_sha256 from calls where phase='benchmark' and budget_scope=? and status='UNKNOWN'",(SCOPE,)).fetchone()
        if u is None or u["call_id"]!="api-9c5dcdb177334b69b1229d5880fe1a4f" or u["case_id"]!="hm-c-m-8e00ab0ec2dd-s4-t24":
            raise SystemExit("original UNKNOWN drift")
        durable_cases={str(r[0]) for r in db.execute("select case_id from calls where phase='benchmark' and budget_scope=?",(SCOPE,))}
    finally:db.close()

    intents=[]
    for p in sorted((RUNTIME/"semantic_request_intents").glob("*.json")):
        o=load(p);cid=str(o.get("case_id") or "")
        if cid and cid not in durable_cases:
            intents.append((p,o))
    if len(intents)!=1:
        raise SystemExit("expected exactly one pre-dispatch intent beyond durable cap: "+repr([x[1].get("case_id") for x in intents]))
    ip,io=intents[0]
    if io.get("case_id")!="hm-c-m-8e00ab0ec2dd-s36-t22":
        raise SystemExit("unexpected next intent at cap boundary")

    obj={
      "schema":"xiaoyu-e2-execution-amendment-v1",
      "status":"FROZEN_POST_ENTRY_AMENDMENT",
      "amendment_id":"halumem-confirmatory-stream-cap-v1",
      "created_at":"2026-10-29",
      "scope":"HALUMEM_CONFIRMATORY_RECOVERY_V2_CAP_ONLY",
      "execution_allowed_by_this_file":False,
      "e2_claim_allowed":False,
      "requires_separate_final_freeze":True,
      "required_independent_family":"audit.e2.confirmatory.halumem_stream_cap_amendment_v1",
      "required_independent_decision":"READY_FOR_HALUMEM_STREAM_CAP_AMENDMENT_FREEZE",
      "parents":{
        "base_execution_manifest":bind(BASE_MAN),
        "base_final_freeze":bind(BASE_FREEZE),
        "recovery_v2_manifest":bind(REC_MAN),
        "recovery_v2_final_freeze":bind(REC_FREEZE),
      },
      "safe_structural_count":{
        **bind(SAFE),
        "scanner":bind(SCANNER),
        "method":safe.get("method"),
        "pilot_control":controls,
        "confirmatory_summary":{
          "streams":cs["streams"],
          "total_semantic_calls_required":cs["total_semantic_calls_required"],
          "max_semantic_calls_per_stream":cs["max_semantic_calls_per_stream"],
          "min_semantic_calls_per_stream":cs["min_semantic_calls_per_stream"],
          "streams_over_old_768_cap":cs["streams_over_old_768_cap"],
        },
        "gold_fields_materialized":0,
        "provider_calls":0,
      },
      "cap_delta":{
        "old_max_case_calls":10000,
        "new_max_case_calls":75691,
        "old_max_calls_per_stream":768,
        "new_max_calls_per_stream":2917,
        "derivation":"exact safe structural user-turn counts across all 36 frozen confirmatory streams",
      },
      "cap_hit_boundary":{
        "durable_status_counts":counts,
        "original_unknown":{
          "call_id":u["call_id"],"case_id":u["case_id"],"error_class":u["error_class"],
          "response_text_is_null":u["response_text"] is None,
          "response_sha256_is_null":u["response_sha256"] is None,
        },
        "next_case_request_intent":{
          "case_id":io["case_id"],
          "path":str(ip.relative_to(ROOT)).replace("\\","/"),
          "sha256":sha(ip),
          "request_messages_sha256":io["request_messages_sha256"],
          "durable_row_exists":False,
          "local_response_receipt_exists":False,
        },
        "interpretation":"old max_calls_per_stream rejected the next case before provider dispatch; no new ambiguous paid outcome",
      },
      "unchanged_scientific_contract":{
        "allowed_uuid_hashes_sha256":hashlib.sha256(json.dumps(track.get("allowed_uuid_hashes") or [],separators=(",",":")).encode()).hexdigest(),
        "variants":track.get("variants"),
        "case_id_rule":track.get("case_id_rule"),
        "max_session_index":track.get("max_session_index"),
        "max_turn_index":track.get("max_turn_index"),
        "max_completion_tokens":track.get("max_completion_tokens"),
        "response_format":track.get("response_format"),
        "invariant_prefix_sha256":track.get("invariant_prefix_sha256"),
        "system_prompt_sha256":track.get("system_prompt_sha256"),
        "schema_sha256":track.get("schema_sha256"),
        "duplicate_paid_case_forbidden":track.get("duplicate_paid_case_forbidden"),
        "reserved_or_unknown_blocks_retry":track.get("reserved_or_unknown_blocks_retry"),
        "serial_state_order_per_user_variant":track.get("serial_state_order_per_user_variant"),
        "recovery_v2_checkpoint_request_binding_unchanged":True,
        "qwen38_flash_post_seal_calibration_12_of_12_unchanged":True,
        "longmemeval_execution_remains_disabled":True,
      },
      "base_gateway":{
        "research_api_sha256":sha(BASE_API),
        "research_api_proxy_sha256":sha(BASE_PROXY),
        "base_gateway_files_unchanged":True,
      },
      "amendment_implementation":{
        "gateway":bind(GATEWAY),
        "proxy":bind(PROXY),
        "mechanism":"dedicated loopback proxy reuses exact base HTTP/gateway code and wraps only validated Halu case metadata caps after amendment authorization",
        "longmemeval_rejected_by_amended_proxy":True,
      },
      "hard_boundaries":[
        "Only max_case_calls and max_calls_per_stream may change.",
        "No case membership, prompt, schema, completion cap, model, UNKNOWN semantics, recovery checkpoint or request-intent semantics change.",
        "The original base manifest/freeze and recovery-v2 manifest/freeze remain immutable.",
        "No provider/judge/gold access is authorized by this amendment candidate.",
        "LongMemEval remains disabled.",
        "Execution requires exact independent READY plus a separate amendment final-freeze record and policy registration."
      ]
    }
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8",newline="\n")
    print(json.dumps({"path":str(OUT.relative_to(ROOT)).replace("\\","/"),"sha256":sha(OUT),
      "old_caps":[10000,768],"new_caps":[75691,2917],"ledger":counts,
      "next_case":io["case_id"],"provider_calls_during_build":0,"gold_reads_during_build":0},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
