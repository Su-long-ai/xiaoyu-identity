# -*- coding: utf-8 -*-
"""Build the exact XiaoYu E2 confirmatory execution spec without reading holdout records.

Despite the historical filename, the output freezes BOTH LongMemEval and
HaluMem confirmatory execution. It is a PREFREEZE specification only and never
authorizes provider or judge execution; a later independently approved final
freeze record is required by e2_confirmatory_execution.py.
"""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
FROZEN=GOV/"confirmatory_frozen"
OUT=GOV/"E2_CONFIRMATORY_EXECUTION_MANIFEST_CANDIDATE.json"

def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open("rb") as f:
  for c in iter(lambda:f.read(1024*1024),b""):h.update(c)
 return h.hexdigest()

def stable(x)->str:
 return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()

def main():
 split_path=GOV/"E2_SPLIT_MANIFEST.json"
 split=json.loads(split_path.read_text("utf-8"))

 # Membership only: no confirmatory benchmark record is opened here.
 lme_indices=[int(x) for x in split["longmemeval"]["confirmatory_indices"]]
 if len(lme_indices)!=454 or len(set(lme_indices))!=454:
  raise SystemExit("bad LongMemEval confirmatory split")
 lme_case_ids=[f"lme-c-{i:03d}" for i in lme_indices]

 hcfg=split["halumem"];uuids=list(map(str,hcfg["confirmatory_uuids"]))
 if len(uuids)!=18 or len(set(uuids))!=18:raise SystemExit("bad HaluMem confirmatory split")
 hashes=[hashlib.sha256(u.encode()).hexdigest() for u in uuids]

 sys.path.insert(0,str(FROZEN));sys.path.insert(0,str(GOV))
 import r49_structural_v5 as structural

 halu_prefix=[{"role":"system","content":structural.SYSTEM_PROMPT}]
 halu_prefix_sha=stable(halu_prefix)

 prompts=json.loads((GOV/"E2_PILOT_PROMPTS.json").read_text("utf-8"))
 lme_system=str(prompts["prompts"]["context_answer"]["system"])
 lme_system_sha=hashlib.sha256(lme_system.encode("utf-8")).hexdigest()
 if lme_system_sha!=str(prompts["prompts"]["context_answer"]["system_sha256"]):
  raise SystemExit("LME frozen context-answer system prompt drift")
 lme_prefix_sha=stable([{"role":"system","content":lme_system}])

 closure={}
 for n in (
  "r47_open_domain_memory_store_frozen.py","r49_structural_v5.py",
  "r49_confirmed_transition.py","r49_atomic_confirmed_transition.py",
  "r52_qa_sufficiency_v7.py","r52_candidate_v7.py",
  "r52_composition_candidate_v7.py","r52_composition_candidate_v8.py"
 ):
  closure[n]=sha(FROZEN/n)

 halu_runner=FROZEN/"HALUMEM_CONFIRMATORY_RUNNER.py"
 lme_runner=FROZEN/"LME_CONFIRMATORY_RUNNER.py"
 out={
  "schema":"xiaoyu-e2-confirmatory-execution-manifest-v1",
  "status":"FROZEN_SPEC_AWAITING_FINAL_FREEZE",
  "purpose":"Exact non-executable execution specification for the fixed LongMemEval 454-case and HaluMem 18-user Medium+Long confirmatory holdouts.",
  "confirmatory_execution_allowed":False,
  "e2_claim_allowed":False,
  "split_manifest_path":"governance/E2_SPLIT_MANIFEST.json",
  "split_manifest_sha256":sha(split_path),
  "membership":{
    "longmemeval_confirmatory_case_count":454,
    "halumem_confirmatory_user_count":18,
    "halumem_variants":["m","l"],
  },
  # Halu runner consumes these historical top-level aliases; keep exact values
  # while the shared tracks block below is authoritative for the gateway.
  "confirmatory_user_count":18,
  "variants":["m","l"],
  "allowed_uuid_hashes":hashes,
  "runner_path":"governance/confirmatory_frozen/HALUMEM_CONFIRMATORY_RUNNER.py",
  "runner_sha256":sha(halu_runner),
  "runners":{
    "halumem":{
      "path":"governance/confirmatory_frozen/HALUMEM_CONFIRMATORY_RUNNER.py",
      "sha256":sha(halu_runner),
      "offline_test_path":"governance/test_halumem_confirmatory_runner_offline.py",
      "offline_test_sha256":sha(GOV/"test_halumem_confirmatory_runner_offline.py"),
    },
    "longmemeval":{
      "path":"governance/confirmatory_frozen/LME_CONFIRMATORY_RUNNER.py",
      "sha256":sha(lme_runner),
      "test_path":"governance/test_lme_confirmatory_runner.py",
      "test_sha256":sha(GOV/"test_lme_confirmatory_runner.py"),
      "scorer_path":"governance/confirmatory_frozen/LME_CONFIRMATORY_SCORER_V1.py",
      "scorer_sha256":sha(FROZEN/"LME_CONFIRMATORY_SCORER_V1.py"),
    }
  },
  "stage_order":{
    "longmemeval":["prediction","seal_predictions","gold_scoring"],
    "halumem":["prediction","seal_predictions","judge_calibration","gold_scoring"],
  },
  "prediction_gold_boundary":{
    "longmemeval":"runner input forbids answer/answer_session_ids/question_type/gold/evaluator metadata; scoring reads gold only after durable prediction seal",
    "halumem_allowed_materialized_fields":["uuid","sessions[].dialogue[].role","sessions[].dialogue[].content","sessions[].questions[].question"],
    "halumem_forbidden_before_seal":["persona_info","memory_points","questions[].answer","questions[].evidence","questions[].difficulty","questions[].question_type","token_cost","all evaluator/gold fields"],
    "halumem_selective_structural_parser_required":True,
    "all_36_halumem_variant_user_prediction_files_sealed_before_gold":True,
  },
  "r52_entrypoint_path":"governance/confirmatory_frozen/r52_composition_candidate_v8.py",
  "r52_entrypoint_sha256":closure["r52_composition_candidate_v8.py"],
  "r52_dependency_closure":closure,
  "semantic_projector":{
    "path":"governance/confirmatory_frozen/r49_structural_v5.py",
    "sha256":closure["r49_structural_v5.py"],
    "prompt_sha256":structural.prompt_sha256(),
    "schema_sha256":structural.schema_sha256(),
    "invariant_prefix_sha256":halu_prefix_sha,
    "legacy_r49_provider_contract_promoted":False,
    "legacy_compatibility_audit":"governance/E2_R52_R49_V5_LEGACY_RECEIPT_COMPAT.json",
    "legacy_compatibility_audit_sha256":sha(GOV/"E2_R52_R49_V5_LEGACY_RECEIPT_COMPAT.json"),
    "synthetic_fixture_projector_allowed":False,
    "assistant_provider_projection_allowed":False,
    "destructive_auto_confirmation_allowed":False,
    "destructive_relations":["SUPERSEDE","RETRACT","CONFLICT"],
    "unconfirmed_destructive_mutates_authoritative_state":False,
  },
  "tracks":{
    "longmemeval_answer":{
      "scope":"proxy:xiaoyu:e2_lme_confirmatory_v1",
      "allowed_case_ids":lme_case_ids,
      "case_id_rule":"lme-c-{confirmatory_index:03d}",
      "max_case_calls":454,
      "max_completion_tokens":512,
      "response_format":{"type":"json_object"},
      "system_prompt_sha256":lme_system_sha,
      "invariant_prefix_sha256":lme_prefix_sha,
      "duplicate_paid_case_forbidden":True,
      "reserved_or_unknown_blocks_retry":True,
      "zero_provider_route":"typed_r50/fail_closed predictions remain local and consume no paid call",
    },
    "halumem_semantic_projection":{
      "scope":"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
      "variants":["m","l"],
      "allowed_uuid_hashes":hashes,
      "case_id_rule":"hm-c-{m|l}-{first12_sha256(uuid)}-s{session_index}-t{turn_index}",
      "max_session_index":9999,
      "max_turn_index":9999,
      "max_case_calls":10000,
      "max_calls_per_stream":768,
      "max_completion_tokens":768,
      "response_format":{"type":"json_object"},
      "invariant_prefix_sha256":halu_prefix_sha,
      "system_prompt_sha256":structural.prompt_sha256(),
      "schema_sha256":structural.schema_sha256(),
      "duplicate_paid_case_forbidden":True,
      "reserved_or_unknown_blocks_retry":True,
      "serial_state_order_per_user_variant":True,
    }
  },
  "gateway":{
    "gate_path":"governance/e2_confirmatory_execution.py",
    "gate_sha256":sha(GOV/"e2_confirmatory_execution.py"),
    "research_api_path":"governance/research_api.py",
    "research_api_sha256":sha(GOV/"research_api.py"),
    "research_api_proxy_path":"governance/research_api_proxy.py",
    "research_api_proxy_sha256":sha(GOV/"research_api_proxy.py"),
    "prefreeze_paid_calls_forbidden":True,
    "final_freeze_record_required":True,
  },
  "judge":{
    "binding_path":"governance/confirmatory_frozen/HALUMEM_JUDGE_BINDING.json",
    "binding_sha256":sha(FROZEN/"HALUMEM_JUDGE_BINDING.json"),
    "calibration_path":"governance/confirmatory_frozen/HALUMEM_JUDGE_CALIBRATION_V1.json",
    "calibration_sha256":sha(FROZEN/"HALUMEM_JUDGE_CALIBRATION_V1.json"),
    "ledger_wrapper_path":"governance/confirmatory_frozen/HALUMEM_CONFIRMATORY_JUDGE_LEDGER.py",
    "ledger_wrapper_sha256":sha(FROZEN/"HALUMEM_CONFIRMATORY_JUDGE_LEDGER.py"),
    "required_calibration":"12/12",
    "calibration_after_prediction_seal":True,
    "unknown_or_reserved_blocks_retry":True,
  },
  "official_scorer":{
    "halumem_evaluation":{"path":"governance/confirmatory_frozen/HALUMEM_OFFICIAL_EVALUATION.PY","sha256":sha(FROZEN/"HALUMEM_OFFICIAL_EVALUATION.PY")},
    "halumem_eval_tools":{"path":"governance/confirmatory_frozen/HALUMEM_OFFICIAL_EVAL_TOOLS.PY","sha256":sha(FROZEN/"HALUMEM_OFFICIAL_EVAL_TOOLS.PY")},
    "halumem_official_llms_reference":{"path":"governance/confirmatory_frozen/HALUMEM_OFFICIAL_LLMS.PY","sha256":sha(FROZEN/"HALUMEM_OFFICIAL_LLMS.PY")},
    "halumem_runtime_rule":"evaluation.py and eval_tools.py are copied byte-identically; only llms.py is replaced by exact durable judge wrapper.",
    "medium_and_long_scored_separately":True,
    "longmemeval_scorer":{"path":"governance/confirmatory_frozen/LME_CONFIRMATORY_SCORER_V1.py","sha256":sha(FROZEN/"LME_CONFIRMATORY_SCORER_V1.py")},
  },
  "authorization":{
    "required_policy_stage":"E2_CONFIRMATORY",
    "required_policy_confirmatory_calls_allowed":True,
    "required_freeze_record_schema":"xiaoyu-e2-confirmatory-final-freeze-v1",
    "required_independent_reaudit_decision":"READY_FOR_CONFIRMATORY_FREEZE",
    "this_manifest_self_authorizes":False,
  }
 }
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n","utf-8")
 print(json.dumps({
   "path":str(OUT),"sha256":sha(OUT),
   "halumem_runner_sha256":out["runners"]["halumem"]["sha256"],
   "lme_runner_sha256":out["runners"]["longmemeval"]["sha256"],
   "halumem_prompt_sha256":out["semantic_projector"]["prompt_sha256"],
   "halumem_prefix_sha256":halu_prefix_sha,
   "lme_prompt_sha256":lme_system_sha,
   "lme_prefix_sha256":lme_prefix_sha,
   "halumem_user_hashes":len(hashes),"lme_case_ids":len(lme_case_ids),
   "confirmatory_execution_allowed":False,
 },indent=2))
if __name__=="__main__":main()
