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

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
SPLIT=GOV/"E2_SPLIT_MANIFEST.json"
PROTOCOL=GOV/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
OUT=GOV/"E2_PILOT_EXECUTION_MANIFEST.json"
HALU=ROOT/"external"/"halumem_dataset_cache"

PROMPTS=GOV/"E2_PILOT_PROMPTS.json"

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
         "full_pilot_extract_count":0,"full_pilot_qa_count":0}
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
                out["full_pilot_extract_count"]+=len(sessions)
                out["full_pilot_qa_count"]+=sum(len(x.get("questions",[])) for x in sessions)
                width=min(session_window,len(sessions))
                max_start=max(0,len(sessions)-width)
                seed=f"{split['halumem']['dataset_revision']}|{name}|{uuid}|e2-pilot-window-v1"
                start=(int(hashlib.sha256(seed.encode()).hexdigest()[:16],16)%(max_start+1)
                       if max_start else 0)
                chosen=list(range(start,start+width))
                qa_candidates=[]
                for si in chosen:
                    out["extract"].append(f"hm-{short}-i-{uh}-{si}")
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

    lme=[f"lme-a-{int(i):03d}" for i in split["longmemeval"]["pilot_indices"]]
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
      },
      "halumem_extract":{
        "scope":"proxy:xiaoyu:e2_halumem_extract_pilot",
        "run_header":"e2_halumem_extract_pilot",
        "case_ids":halu["extract"],
        "case_count":len(halu["extract"]),
        "max_completion_tokens":1536,
        "response_format":{"type":"json_object"},
        "invariant_prefix_messages":halu_extract_prefix,
        "invariant_prefix_sha256":prefix_hash(halu_extract_prefix),
        "prompt_semantics_source":"accepted P1 R27/R35 caller-bound event extraction protocol",
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
        "full_pilot_extract_count":halu["full_pilot_extract_count"],
        "full_pilot_qa_count":halu["full_pilot_qa_count"],
        "selected_extract_count":len(halu["extract"]),
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
      },
      "historical_completion_basis":{
        "longmemeval_observed_max":225,
        "longmemeval_cap":512,
        "halumem_observed_answer_or_judge_max":1064,
        "halumem_extract_cap":1536,
        "halumem_qa_cap":768,
        "note":"Caps retain margin; pilot observations may tighten only the later confirmatory protocol, never retroactively alter pilot outcomes."
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
