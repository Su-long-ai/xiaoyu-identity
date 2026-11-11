#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the exact E2 confirmatory final independent re-audit manifest.

Control-plane only. This hashes the bytes that can affect future confirmatory
membership, prediction, paid transport, sealing, scoring and audit gates.
It reads no confirmatory benchmark records and performs no provider/judge calls.
"""
from __future__ import annotations
import hashlib,json,importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
CF=GOV/"confirmatory_frozen"
OUT=GOV/"E2_CONFIRMATORY_FINAL_REAUDIT_MANIFEST_CANDIDATE.json"

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p:Path)->str:return str(p.relative_to(ROOT)).replace("\\","/")
def canon(x)->bytes:
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
def write_lf(path:Path,obj):
    with path.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")

def main():
    files={
      # Frozen split/protocol/execution topology.
      "split_manifest":GOV/"E2_SPLIT_MANIFEST.json",
      "protocol_candidate_v2":GOV/"E2_CONFIRMATORY_PROTOCOL_CANDIDATE_V2.json",
      "implementation_bindings":GOV/"E2_CONFIRMATORY_IMPLEMENTATION_BINDINGS.json",
      "execution_manifest":GOV/"E2_CONFIRMATORY_EXECUTION_MANIFEST_CANDIDATE.json",
      "halumem_runner_contract":CF/"HALUMEM_CONFIRMATORY_RUNNER_CONTRACT.json",

      # Shared execution authorization + paid transport.
      "confirmatory_gate":GOV/"e2_confirmatory_execution.py",
      "research_api":GOV/"research_api.py",
      "research_api_proxy":GOV/"research_api_proxy.py",
      "prefreeze_doctor":GOV/"e2_confirmatory_prefreeze_doctor.py",
      "token_efficiency_doctor":GOV/"e2_token_efficiency_doctor.py",

      # LongMemEval exact runtime.
      "lme_runner":CF/"LME_CONFIRMATORY_RUNNER.py",
      "lme_runner_test":GOV/"test_lme_confirmatory_runner.py",
      "lme_scorer":CF/"LME_CONFIRMATORY_SCORER_V1.py",
      "r48_retrieval":CF/"R48_FTS5_RETRIEVAL_V4_FROZEN.py",
      "r50_consumer":CF/"R50_TYPED_CONSUMER_V2_FROZEN.py",
      "r50_contract":CF/"R50_TYPED_CONTRACT_V2_FROZEN.json",
      "r51_v2":CF/"r51_semantic_binder_v2.py",
      "r51_v3":CF/"r51_semantic_binder_v3.py",
      "r51_v4":CF/"r51_semantic_binder_v4.py",

      # HaluMem exact R52 runtime and structural-v5 projector.
      "r52_r47":CF/"r47_open_domain_memory_store_frozen.py",
      "r52_r49_structural":CF/"r49_structural_v5.py",
      "r52_r49_parent":CF/"r49_confirmed_transition.py",
      "r52_r49_atomic":CF/"r49_atomic_confirmed_transition.py",
      "r52_qa":CF/"r52_qa_sufficiency_v7.py",
      "r52_reference":CF/"r52_candidate_v7.py",
      "r52_composition_v7":CF/"r52_composition_candidate_v7.py",
      "r52_entrypoint_v8":CF/"r52_composition_candidate_v8.py",
      "r52_holdout_inputs":CF/"r52_holdout_inputs.json",
      "r52_exact_outputs":CF/"r52_exact_components_outputs.json",
      "halumem_runner":CF/"HALUMEM_CONFIRMATORY_RUNNER.py",
      "halumem_runner_test":GOV/"test_halumem_confirmatory_runner_offline.py",
      "halumem_legacy_compat_audit":GOV/"E2_R52_R49_V5_LEGACY_RECEIPT_COMPAT.json",

      # Exact HaluMem judge/scoring path.
      "judge_binding":CF/"HALUMEM_JUDGE_BINDING.json",
      "judge_calibration":CF/"HALUMEM_JUDGE_CALIBRATION_V1.json",
      "judge_ledger":CF/"HALUMEM_CONFIRMATORY_JUDGE_LEDGER.py",
      "judge_binding_test":GOV/"test_halumem_judge_binding.py",
      "halumem_official_evaluation":CF/"HALUMEM_OFFICIAL_EVALUATION.PY",
      "halumem_official_eval_tools":CF/"HALUMEM_OFFICIAL_EVAL_TOOLS.PY",
      "halumem_official_llms_reference":CF/"HALUMEM_OFFICIAL_LLMS.PY",
    }
    missing=[str(p) for p in files.values() if not p.is_file()]
    if missing:raise SystemExit("missing bound artifacts: "+repr(missing))

    # Recompute the exact promoted structural-v5 prompt/schema/prefix.
    spec=importlib.util.spec_from_file_location("_r49_structural_final",files["r52_r49_structural"])
    structural=importlib.util.module_from_spec(spec);spec.loader.exec_module(structural)
    v5_prompt_sha=structural.prompt_sha256()
    v5_schema_sha=structural.schema_sha256()
    v5_prefix_sha=hashlib.sha256(canon([{"role":"system","content":structural.SYSTEM_PROMPT}])).hexdigest()

    protocol=json.loads(files["protocol_candidate_v2"].read_text("utf-8"))
    bindings=json.loads(files["implementation_bindings"].read_text("utf-8"))
    execution=json.loads(files["execution_manifest"].read_text("utf-8"))
    contract=json.loads(files["halumem_runner_contract"].read_text("utf-8"))
    legacy=json.loads(files["halumem_legacy_compat_audit"].read_text("utf-8"))

    # Fail closed while building the package if local prefreeze topology is not exact.
    if protocol.get("status")!="PREFREEZE_COMPLETE_WAITING_FINAL_INDEPENDENT_V2_REAUDIT":
        raise SystemExit("protocol not in final-v2 prefreeze state")
    if bindings.get("status")!="PREFREEZE_EXACT_BINDINGS_WAITING_FINAL_V2_REAUDIT":
        raise SystemExit("bindings not in final-v2 prefreeze state")
    if execution.get("status")!="FROZEN_SPEC_AWAITING_FINAL_FREEZE" or execution.get("confirmatory_execution_allowed") is not False:
        raise SystemExit("execution manifest is not prefreeze-locked")
    if contract.get("status")!="PREFREEZE_FINAL_RUNNER_BOUND_WAITING_FINAL_V2_REAUDIT":
        raise SystemExit("HaluMem contract is not final-v2 prefreeze")
    if legacy.get("all_legacy_accepted_survive_v5") is not False:
        raise SystemExit("legacy compatibility evidence unexpectedly changed")
    legacy_accepted=int(legacy.get("legacy_accepted_cases",-1))
    legacy_surviving=int(legacy.get("legacy_accepted_and_v5_accepted_cases",-1))
    if legacy_accepted!=9 or legacy_surviving!=7:
        raise SystemExit(
            f"legacy compatibility counts drift: accepted={legacy_accepted} surviving_v5={legacy_surviving}"
        )
    if protocol.get("e2_claim_allowed") is not False or protocol.get("execution_rules",{}).get("confirmatory_calls_allowed") is not False:
        raise SystemExit("protocol execution/claim gate is not closed")

    tracks=execution.get("tracks") or {}
    lme=tracks.get("longmemeval_answer") or {}
    halu=tracks.get("halumem_semantic_projection") or {}
    if len(lme.get("allowed_case_ids") or [])!=454 or len(set(lme.get("allowed_case_ids") or []))!=454:
        raise SystemExit("LME membership not exact 454")
    if len(halu.get("allowed_uuid_hashes") or [])!=18 or len(set(halu.get("allowed_uuid_hashes") or []))!=18:
        raise SystemExit("HaluMem membership not exact 18")

    doc={
      "schema":"xiaoyu-e2-confirmatory-final-reaudit-manifest-candidate-v2",
      "status":"READY_FOR_INDEPENDENT_V2_REAUDIT",
      "created":"2026-10-29",
      "bound_files":{
        k:{"path":rel(v),"sha256":sha(v),"bytes":v.stat().st_size}
        for k,v in files.items()
      },
      "membership":{
        "longmemeval_case_count":454,
        "longmemeval_allowed_case_ids_sha256":hashlib.sha256(canon(lme["allowed_case_ids"])).hexdigest(),
        "halumem_user_count":18,
        "halumem_allowed_uuid_hashes_sha256":hashlib.sha256(canon(halu["allowed_uuid_hashes"])).hexdigest(),
        "halumem_variants":list(halu.get("variants") or []),
        "untouched_provider_exposure_required":{"longmemeval":0,"halumem":0},
      },
      "r52":{
        "submission_id":"sub-0cc4e587fc8a46d4",
        "review_id":"review-c4b018f60f754002",
        "decision":"ACCEPT_E1",
        "promoted_entrypoint":"r52_entrypoint_v8",
        "entrypoint_sha256":sha(files["r52_entrypoint_v8"]),
      },
      "halumem_semantic_projector":{
        "promoted":"receipt-bound R52 structural-v5",
        "path":rel(files["r52_r49_structural"]),
        "file_sha256":sha(files["r52_r49_structural"]),
        "system_prompt_sha256":v5_prompt_sha,
        "schema_sha256":v5_schema_sha,
        "invariant_prefix_sha256":v5_prefix_sha,
        "assistant_provider_projection_allowed":False,
        "synthetic_fixture_projector_allowed":False,
        "legacy_r49_provider_contract_promoted":False,
        "legacy_compatibility_audit_sha256":sha(files["halumem_legacy_compat_audit"]),
        "legacy_accepted_cases":legacy_accepted,
        "legacy_accepted_surviving_v5":legacy_surviving,
      },
      "execution":{
        "manifest_sha256":sha(files["execution_manifest"]),
        "confirmatory_calls_allowed":False,
        "final_freeze_record_required":True,
        "reserved_or_unknown_blocks_retry_and_seal":True,
        "longmemeval_runner_sha256":sha(files["lme_runner"]),
        "halumem_runner_sha256":sha(files["halumem_runner"]),
        "shared_gate_sha256":sha(files["confirmatory_gate"]),
        "research_api_sha256":sha(files["research_api"]),
        "research_api_proxy_sha256":sha(files["research_api_proxy"]),
      },
      "halumem_prediction_boundary":{
        "stage_order":["prediction","seal_predictions","judge_calibration","gold_scoring"],
        "expected_prediction_files":36,
        "selective_parser_required":True,
        "all_predictions_sealed_before_gold":True,
        "destructive_auto_confirmation_allowed":False,
      },
      "judge":{
        "provider":"alibaba_model_studio",
        "model":"qwen3.8-flash",
        "temperature":0.0,
        "max_tokens":16384,
        "enable_thinking":False,
        "substitution_allowed":False,
        "external_gpt4o_medians_formal_gate_allowed":False,
        "required_calibration":"12/12",
        "missing_runtime_credential_blocks_execution":True,
      },
      "unbound_required":{},
      "reaudit_invariants":[
        "confirmatory split and execution-manifest membership are exact; no confirmatory paid exposure occurred before final freeze",
        "R47/R48/R49/R50/R51/R52 exact accepted dependency bytes are the only promoted implementation bytes",
        "LME runner cannot read question_type/answer/answer_session_ids/gold/evaluator fields before prediction and fails closed on typed insufficiency",
        "LME execute path is hard-blocked in PREFREEZE before provider transport and future paid cases are exact 454-member IDs",
        "Halu user-turn semantic extraction uses exact receipt-bound R52 structural-v5; assistant turns remain raw provenance history",
        "legacy R49 provider contract and synthetic fixture projector are not promoted into final Halu semantic extraction",
        "unconfirmed Halu destructive proposals do not mutate authoritative state and benchmark dialogue is not a separate confirmation",
        "Halu selective parser cannot materialize persona_info/memory_points/answers/evidence/difficulty/question_type/token_cost before prediction seal",
        "all 36 Halu prediction files seal before any gold read or judge scoring",
        "shared confirmatory gate validates exact LME membership and Halu UUID-hash membership before paid reservation",
        "current research_api/proxy bytes are exact-bound by the non-executable confirmatory manifest; historical pilot bytes remain historical evidence",
        "durable provider/judge receipts prevent duplicate paid work; RESERVED/UNKNOWN blocks retry and seal",
        "existing Halu prediction seal is never trusted by runner SHA alone: every reuse recomputes and matches all 36 prediction path+SHA bindings plus manifest/split/R52/ledger state",
        "Halu judge calibration reuse is allowed only after 12 fresh COMMITTED qwen3.8-flash durable judge-ledger receipts are bound to the current prediction seal; prior GPT-4o/qwen3.8-max-0902 receipts are not reusable",
        "existing LME provider receipt/prediction is rederived and cross-checked against COMMITTED research_api durable call_id/scope/response_text/response_sha256 before reuse",
        "existing Halu semantic provider receipt is cross-checked against COMMITTED research_api durable call_id/scope/response_text/response_sha256 before reuse even if local response_text and local hash are changed together",
        "frozen Halu judge is exact qwen3.8-flash temperature 0 max_tokens 16384 with thinking disabled; substitution is forbidden and fresh 12/12 Flash calibration is mandatory; GPT-4o and prior Max scores are reference-only",
        "missing DASHSCOPE_API_KEY blocks Halu gold scoring instead of substituting a judge",
        "prefreeze doctor and token-efficiency doctor are green with confirmatory execution and E2 claims still false",
        "independent auditor is distinct from Research B and Lead and must return READY_FOR_CONFIRMATORY_FREEZE on these exact bytes"
      ],
      "required_independent_decision":"READY_FOR_CONFIRMATORY_FREEZE",
      "confirmatory_execution_allowed":False,
      "e2_claim_allowed":False
    }
    write_lf(OUT,doc)
    print(json.dumps({
      "path":rel(OUT),"sha256":sha(OUT),
      "schema":doc["schema"],"status":doc["status"],
      "bound_count":len(files),"unbound":[],
      "lme_cases":454,"halumem_users":18,
      "v5_prompt_sha256":v5_prompt_sha,
      "v5_schema_sha256":v5_schema_sha,
      "v5_prefix_sha256":v5_prefix_sha,
      "confirmatory_reads":0,"provider_calls":0,"judge_calls":0,
      "confirmatory_execution_allowed":False
    },ensure_ascii=False,indent=2))

if __name__=="__main__":main()
