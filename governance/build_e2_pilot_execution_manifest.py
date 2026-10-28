#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the frozen E2 pilot paid-execution envelope without model/network calls.

The scientific E2 protocol/split is already frozen. This file derives only
execution-layer controls: allowed paid scopes/case IDs, reuse of accepted P1
prompt prefixes, and conservative per-call completion ceilings.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import e2_longmemeval_context as lme_context

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
PROTOCOL=GOV/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
OUT=GOV/"E2_PILOT_EXECUTION_MANIFEST.json"
HALU=ROOT/"external"/"halumem_dataset_cache"

PROMPTS=GOV/"E2_PILOT_PROMPTS.json"
LME_CONTEXT_BUILDER=GOV/"e2_longmemeval_context.py"

def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p): return sha_bytes(Path(p).read_bytes())
def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def hobj(x): return sha_bytes(canon(x).encode("utf-8"))
def prefix_hash(messages): return hobj(messages)

def halu_pilot_cases(split):
    """Deterministic nonpromotional operation subsample inside frozen pilot users.

    The user-level split remains unchanged. Because the engineering pilot has a
    hard 1M raw-token ceiling, executing every Medium+Long session for the two
    pilot users would exceed the envelope before model quality is learned.
    Freeze a contiguous 8-session window per (variant,user), then select at most
    16 questions from those windows by stable hash. No outcome/gold is used.
    """
    pilot=set(split["halumem"]["pilot_uuids"])
    uuid_re=re.compile(r'"uuid"\s*:\s*"([^"]+)"')
    session_window=8
    qa_per_user_variant=16
    out={"extract":[],"qa":[],"sampling":[],
         "full_pilot_session_count":0,"full_pilot_user_turn_count":0,
         "full_pilot_qa_count":0,"selected_session_count":0,
         "selected_extract_message_count":0}
    variants=(("m","HaluMem-Medium.jsonl"),("l","HaluMem-Long.jsonl"))
    found=set()
    for short,name in variants:
        path=HALU/name
        with path.open("r",encoding="utf-8") as f:
            for raw in f:
                m=uuid_re.search(raw[:4096])
                if not m or m.group(1) not in pilot:
                    continue
                row=json.loads(raw)
                uuid=str(row["uuid"]);found.add((name,uuid))
                uh=hashlib.sha256(uuid.encode()).hexdigest()[:12]
                sessions=row["sessions"]
                out["full_pilot_session_count"]+=len(sessions)
                out["full_pilot_user_turn_count"]+=sum(
                    1 for sess in sessions for turn in sess.get("dialogue",[])
                    if str(turn.get("role") or "").lower()=="user")
                out["full_pilot_qa_count"]+=sum(len(x.get("questions",[])) for x in sessions)
                width=min(session_window,len(sessions))
                max_start=max(0,len(sessions)-width)
                seed=f"{split['halumem']['dataset_revision']}|{name}|{uuid}|e2-pilot-window-v1"
                start=(int(hashlib.sha256(seed.encode()).hexdigest()[:16],16)%(max_start+1)
                       if max_start else 0)
                chosen=list(range(start,start+width))
                qa_candidates=[]
                selected_user_turns=0
                for si in chosen:
                    out["selected_session_count"]+=1
                    for ti,turn in enumerate(sessions[si].get("dialogue",[])):
                        if str(turn.get("role") or "").lower()!="user":
                            continue
                        # Accepted P1 extractor semantics are exactly one target
                        # user message per paid call; case identity therefore
                        # binds variant/user/session/turn, never whole session.
                        out["extract"].append(f"hm-{short}-i-{uh}-{si}-{ti}")
                        selected_user_turns+=1
                        out["selected_extract_message_count"]+=1
                    for qi,_q in enumerate(sessions[si].get("questions",[])):
                        cid=f"hm-{short}-q-{uh}-{si}-{qi}"
                        rank=hashlib.sha256(
                            f"{name}|{uuid}|{si}|{qi}|e2-pilot-qa-v1".encode()
                        ).hexdigest()
                        qa_candidates.append((rank,cid,si,qi))
                qa_candidates.sort()
                selected=qa_candidates[:qa_per_user_variant]
                out["qa"].extend(x[1] for x in selected)
                out["sampling"].append({
                  "variant":name,"uuid":uuid,
                  "session_count_total":len(sessions),
                  "session_window_start":start,
                  "session_window_count":width,
                  "selected_session_indices":chosen,
                  "selected_user_turn_count":selected_user_turns,
                  "questions_in_window":len(qa_candidates),
                  "selected_qa_count":len(selected),
                  "selection_basis":"SHA256 dataset_revision|variant|uuid chooses contiguous session window; SHA256 variant|uuid|session|question ranks QA within window; no outcome/gold used."
                })
    expected={(name,u) for name in ("HaluMem-Medium.jsonl","HaluMem-Long.jsonl") for u in pilot}
    if found!=expected:
        raise RuntimeError(f"pilot UUID coverage mismatch: missing={sorted(expected-found)} extra={sorted(found-expected)}")
    return out

def main():
    split=json.loads(SPLIT.read_text(encoding="utf-8"))
    protocol=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    prompts=json.loads(PROMPTS.read_text(encoding="utf-8"))
    if prompts.get("schema")!="xiaoyu-e2-pilot-prompts-v1" or prompts.get("status")!="FROZEN_BEFORE_FIRST_E2_PAID_CALL":
        raise RuntimeError("E2 pilot prompt freeze is invalid")
    context_system=prompts["prompts"]["context_answer"]["system"]
    extract_system=prompts["prompts"]["event_extraction"]["system"]
    if hashlib.sha256(context_system.encode("utf-8")).hexdigest()!=prompts["prompts"]["context_answer"]["system_sha256"]:
        raise RuntimeError("context-answer prompt hash mismatch")
    if hashlib.sha256(extract_system.encode("utf-8")).hexdigest()!=prompts["prompts"]["event_extraction"]["system_sha256"]:
        raise RuntimeError("event-extraction prompt hash mismatch")
    if protocol.get("status")!="FROZEN_BEFORE_EXECUTION":
        raise RuntimeError("E2 pilot protocol is not frozen")

    lme_indices=[int(i) for i in split["longmemeval"]["pilot_indices"]]
    lme=[f"lme-a-{i:03d}" for i in lme_indices]

    # Freeze the exact local retrieval/context payloads before the first E2
    # paid call. LongMemEval payloads do not depend on prior model outputs, so
    # pre-freezing them closes retrieval drift without touching gold fields.
    lme_data=lme_context.load_dataset()
    lme_payload_rows=[]
    lme_payload_hashes={}
    lme_context_counts={}
    for idx,cid in zip(lme_indices,lme):
        payload,diag=lme_context.build_payload(idx,lme_data)
        if payload.get("id")!=cid:
            raise RuntimeError("LongMemEval payload/case identity mismatch")
        lme_payload_rows.append({"track":"longmemeval_answer",
                                 "case_id":cid,"payload":payload})
        lme_payload_hashes[cid]=hobj(payload)
        lme_context_counts[cid]=len(payload.get("context") or [])

    halu=halu_pilot_cases(split)

    # Reuse accepted P1 prompt semantics; only the dynamic final user payload
    # changes per benchmark case.
    lme_prefix=[{"role":"system","content":context_system}]
    halu_extract_prefix=[{"role":"system","content":extract_system}]
    halu_qa_prefix=[{"role":"system","content":context_system}]

    tracks={
      "longmemeval_answer":{
        "scope":"proxy:xiaoyu:e2_lme_answer_pilot",
        "run_header":"e2_lme_answer_pilot",
        "case_ids":lme,
        "case_count":len(lme),
        "max_completion_tokens":512,
        "response_format":{"type":"json_object"},
        "invariant_prefix_messages":lme_prefix,
        "invariant_prefix_sha256":prefix_hash(lme_prefix),
        "prompt_semantics_source":"accepted P1 R18 context-answer protocol",
        "execution_status":"READY",
        "context_builder":{
          "path":"governance/e2_longmemeval_context.py",
          "sha256":sha_file(LME_CONTEXT_BUILDER),
          "dataset":"external/OmniMemEval/data/longmemeval/longmemeval_s_cleaned.json",
          "dataset_sha256":"d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
          "retrieval_mode":"history",
          "relevance":"sqlite_fts5",
          "limit":7,
          "max_posting":128,
          "authority_map":{"user":"user_history","assistant":"conversation_history"},
          "manual_context_forbidden":True
        },
        "dynamic_payload_contract":{
          "encoding":"r18_single_case_compact_json_v1",
          "required_keys":["id","context","question"],
          "allowed_keys":["id","context","question"],
          "user_prefix":"逐项回答以下独立案例：\n",
          "container":"single-item-json-array",
          "source_submission":"sub-2dd80e4a13a44743"
        },
        "offline_input_freeze":{
          "builder":"governance/e2_longmemeval_context.py",
          "builder_sha256":sha_file(GOV/"e2_longmemeval_context.py"),
          "dataset_sha256":lme_context.DATASET_SHA256,
          "payload_plan_sha256":hobj(lme_payload_rows),
          "payload_sha256_by_case":lme_payload_hashes,
          "context_count_by_case":lme_context_counts,
          "gold_fields_read_into_payload":False,
          "provider_calls":0
        },
      },
      "halumem_extract":{
        "scope":"proxy:xiaoyu:e2_halumem_extract_pilot",
        "run_header":"e2_halumem_extract_pilot",
        "case_ids":halu["extract"],
        "case_count":len(halu["extract"]),
        "max_completion_tokens":512,
        "response_format":{"type":"json_object"},
        "invariant_prefix_messages":halu_extract_prefix,
        "invariant_prefix_sha256":prefix_hash(halu_extract_prefix),
        "prompt_semantics_source":"accepted P1 R27/R35 caller-bound event extraction protocol",
        "execution_status":"HOLD_OPEN_DOMAIN_SCHEMA_MISMATCH",
        "execution_hold_reason":"Accepted P1 R27/R35 extractor is finite-slot current-state extraction; HaluMem is open-domain memory. Paid execution would not represent the frozen E2 capability.",
        "dynamic_payload_contract":{
          "encoding":"r35_single_target_message_compact_json_v1",
          "required_keys":["current_state","context_messages","target_message","slots"],
          "allowed_keys":["current_state","context_messages","target_message","slots"],
          "target_message_required_keys":["message_index","role","text"],
          "target_message_role":"user",
          "container":"json-object",
          "source_submission":"sub-2b974fd436624d87"
        },
      },
      "halumem_qa":{
        "scope":"proxy:xiaoyu:e2_halumem_qa_pilot",
        "run_header":"e2_halumem_qa_pilot",
        "case_ids":halu["qa"],
        "case_count":len(halu["qa"]),
        "max_completion_tokens":768,
        "response_format":{"type":"json_object"},
        "invariant_prefix_messages":halu_qa_prefix,
        "invariant_prefix_sha256":prefix_hash(halu_qa_prefix),
        "prompt_semantics_source":"accepted P1 R18 context-answer protocol",
        "execution_status":"HOLD_DEPENDS_ON_VALID_HALUMEM_MEMORY_PIPELINE",
        "execution_hold_reason":"QA is blocked until an open-domain HaluMem ingest/update pipeline is frozen; hand-built context is forbidden.",
        "dynamic_payload_contract":{
          "encoding":"r18_single_case_compact_json_v1",
          "required_keys":["id","context","question"],
          "allowed_keys":["id","context","question"],
          "user_prefix":"逐项回答以下独立案例：\n",
          "container":"single-item-json-array",
          "source_submission":"sub-2dd80e4a13a44743"
        },
      },
    }
    all_ids=[]
    for t in tracks.values(): all_ids.extend(t["case_ids"])
    if len(all_ids)!=len(set(all_ids)): raise RuntimeError("duplicate pilot paid case IDs")

    out={
      "schema":"xiaoyu-e2-pilot-execution-manifest-v1",
      "status":"FROZEN_BEFORE_FIRST_E2_PAID_CALL",
      "protocol_sha256":sha_file(PROTOCOL),
      "split_manifest_sha256":sha_file(SPLIT),
      "prompt_freeze_sha256":sha_file(PROMPTS),
      "scientific_semantics_changed":False,
      "benchmark_pilot_hard_cap_tokens":1000000,
      "warmup":{
        "serial_real_cases_per_scope":2,
        "synthetic_paid_warmup_forbidden":True,
        "bounded_parallelism_after_warmup":2,
      },
      "tracks":tracks,
      "paid_case_count":len(all_ids),
      "halumem_operation_subsample":{
        "role":"NONPROMOTIONAL_ENGINEERING_SUBSAMPLE_WITHIN_FROZEN_PILOT_USERS",
        "full_pilot_session_count":halu["full_pilot_session_count"],
        "full_pilot_user_turn_count":halu["full_pilot_user_turn_count"],
        "full_pilot_qa_count":halu["full_pilot_qa_count"],
        "selected_session_count":halu["selected_session_count"],
        "selected_extract_message_count":len(halu["extract"]),
        "selected_qa_count":len(halu["qa"]),
        "sampling":halu["sampling"],
        "confirmatory_users_touched":0,
        "note":"This execution-envelope refinement is frozen before the first E2 paid call. It does not change the user-level pilot/confirmatory split and cannot support an E2 claim."
      },
      "confirmatory_case_ids_included":0,
      "trust_layer_paid_model_required":False,
      "rules":{
        "final_dynamic_message_role":"user",
        "all_invariant_messages_must_precede_dynamic_case_payload":True,
        "proxy_recomputes_invariant_prefix_sha256":True,
        "case_id_header_required":True,
        "duplicate_reserved_committed_unknown_forbidden":True,
        "response_format_json_object_required":True,
        "gold_answer_fields_forbidden_from_system_under_test":True,
        "track_execution_status_enforced_before_provider":True,
        "longmemeval_context_rebuilt_and_verified_before_provider":True,
      },
      "historical_completion_basis":{
        "longmemeval_observed_max":225,
        "longmemeval_cap":512,
        "halumem_observed_answer_or_judge_max":1064,
        "halumem_extract_observed_completion_max_r35":83,
        "halumem_extract_cap":512,
        "halumem_extract_basis_submission":"sub-2b974fd436624d87",
        "halumem_qa_cap":768,
        "note":"Extractor cap is >6x the accepted R35 observed completion maximum; QA/LME caps retain historical margin. Pilot observations may tighten only the later confirmatory protocol, never retroactively alter pilot outcomes."
      }
    }
    with OUT.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({
      "manifest":str(OUT),
      "sha256":sha_file(OUT),
      "paid_case_count":len(all_ids),
      "track_counts":{k:v["case_count"] for k,v in tracks.items()},
      "prefix_hashes":{k:v["invariant_prefix_sha256"] for k,v in tracks.items()}
    },ensure_ascii=False,indent=2))

if __name__=="__main__": main()
