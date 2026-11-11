#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the E2 confirmatory recovery-v2 prefreeze manifest.

Reads only local code hashes, incident records and durable ledger metadata.
It never opens LongMemEval/HaluMem dataset contents or gold.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
CAND=GOV/"confirmatory_recovery_candidate"
FROZEN=GOV/"confirmatory_frozen"
OUT=GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json"
LEGACY_INDEX=GOV/"E2_HALUMEM_LEGACY_COMMITTED_RECEIPT_INDEX_V2.json"

def sha(p:Path)->str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def binding(p:Path)->dict:
    p=Path(p)
    if not p.is_file():raise SystemExit("missing bound file: "+str(p))
    return {"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size}

def main():
    base_manifest=GOV/"E2_CONFIRMATORY_EXECUTION_MANIFEST_CANDIDATE.json"
    base_freeze=GOV/"E2_CONFIRMATORY_FINAL_FREEZE_RECORD.json"
    halu_incident=GOV/"E2_HALUMEM_CONFIRMATORY_RESUME_INCIDENT_20261029.md"
    lme_incident=GOV/"E2_LME_CONFIRMATORY_GOLD_BOUNDARY_INCIDENT_20261029.md"
    halu_old=FROZEN/"HALUMEM_CONFIRMATORY_RUNNER.py"
    lme_old=FROZEN/"LME_CONFIRMATORY_RUNNER.py"
    halu_new=CAND/"HALUMEM_CONFIRMATORY_RUNNER_V2.py"
    lme_new=CAND/"LME_CONFIRMATORY_RUNNER_V2.py"
    reconcile=CAND/"confirmatory_unknown_reconciliation_v2.py"
    judge_wrapper=CAND/"HALUMEM_CONFIRMATORY_JUDGE_LEDGER_V2.py"
    lme_score=CAND/"LME_CONFIRMATORY_SCORE_WRAPPER_V2.py"
    judge_binding=FROZEN/"HALUMEM_JUDGE_BINDING.json"
    judge_cal=FROZEN/"HALUMEM_JUDGE_CALIBRATION_V1.json"

    db=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));db.row_factory=sqlite3.Row
    try:
        scope_h="proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"
        scope_l="proxy:xiaoyu:e2_lme_confirmatory_v1"
        hcounts={str(r["status"]):int(r["n"]) for r in db.execute(
            "select status,count(*) n from calls where phase='benchmark' and budget_scope=? group by status",(scope_h,))}
        lcounts={str(r["status"]):int(r["n"]) for r in db.execute(
            "select status,count(*) n from calls where phase='benchmark' and budget_scope=? group by status",(scope_l,))}
        unknowns=db.execute(
            "select call_id,case_id,status,error_class,budget_scope,prompt_prefix_sha256,response_text,response_sha256 "
            "from calls where phase='benchmark' and budget_scope=? and status='UNKNOWN' order by case_id",(scope_h,)).fetchall()
        committed=db.execute(
            "select call_id,case_id,status,response_sha256,budget_scope from calls "
            "where phase='benchmark' and budget_scope=? and status='COMMITTED' order by case_id",(scope_h,)).fetchall()
    finally:db.close()

    if hcounts!={"COMMITTED":68,"UNKNOWN":1}:
        raise SystemExit("unexpected HaluMem recovery ledger counts: "+repr(hcounts))
    if lcounts:
        raise SystemExit("LongMemEval provider exposure must remain zero for this recovery manifest: "+repr(lcounts))
    if len(unknowns)!=1:raise SystemExit("expected exactly one legacy HaluMem UNKNOWN")
    old_receipt_dir=GOV/"halumem_confirmatory_runtime"/"semantic_receipts"
    receipt_rows=[]
    for row in committed:
        p=old_receipt_dir/(str(row["case_id"])+".json")
        if not p.is_file():raise SystemExit("legacy COMMITTED receipt missing: "+str(row["case_id"]))
        old=json.loads(p.read_text("utf-8"))
        if old.get("case_id")!=row["case_id"] or old.get("call_id")!=row["call_id"]:
            raise SystemExit("legacy COMMITTED receipt identity drift: "+str(row["case_id"]))
        if old.get("response_sha256")!=row["response_sha256"] or not old.get("request_messages_sha256"):
            raise SystemExit("legacy COMMITTED receipt request/response binding drift: "+str(row["case_id"]))
        receipt_rows.append({
          "case_id":row["case_id"],"call_id":row["call_id"],
          "path":str(p.relative_to(ROOT)).replace("\\","/"),
          "sha256":sha(p),"bytes":p.stat().st_size,
          "request_messages_sha256":old["request_messages_sha256"],
          "response_sha256":old["response_sha256"],
        })
    if len(receipt_rows)!=68:raise SystemExit("legacy COMMITTED receipt coverage is not 68")
    legacy_index={
      "schema":"xiaoyu-e2-halumem-legacy-committed-receipt-index-v1",
      "count":len(receipt_rows),"receipts":receipt_rows,
    }
    LEGACY_INDEX.write_text(json.dumps(legacy_index,ensure_ascii=False,indent=2)+"\n","utf-8",newline="\n")
    u=dict(unknowns[0])
    if u.get("response_text") is not None or u.get("response_sha256"):
        raise SystemExit("legacy UNKNOWN unexpectedly has recoverable response")
    if u.get("case_id")!="hm-c-m-8e00ab0ec2dd-s4-t24" or u.get("error_class")!="IncompleteRead":
        raise SystemExit("legacy UNKNOWN identity drift")

    obj={
      "schema":"xiaoyu-e2-confirmatory-recovery-v2-manifest-candidate-v1",
      "status":"PREFREEZE_RECOVERY_V2_CANDIDATE",
      "generation_id":"e2-confirmatory-recovery-v2-20261029",
      "e2_claim_allowed":False,
      "recovery_execution_allowed":False,
      "required_independent_family":"audit.e2.confirmatory.recovery_v2_final",
      "required_independent_decision":"READY_FOR_RECOVERY_V2_FREEZE",
      "base_execution":binding(base_manifest),
      "base_final_freeze":binding(base_freeze),
      "incidents":{
        "halumem_resume_unknown":binding(halu_incident),
        "longmemeval_gold_boundary":binding(lme_incident),
      },
      "track_scopes":{
        "halumem":scope_h,
        "longmemeval":scope_l,
      },
      "track_disposition":{
        "halumem":{
          "status":"RECOVERY_V2_PREFREEZE_CANDIDATE",
          "recovery_execution_candidate":True,
          "prior_runtime":"IMMUTABLE_UNSEALED",
          "resume_strategy":"NEW_RUNTIME_REPLAY_COMMITTED_PLUS_TRANSPORT_ABSTAIN_UNKNOWN",
        },
        "longmemeval":{
          "status":"INVALIDATED_GOLD_BOUNDARY",
          "recovery_execution_candidate":False,
          "provider_calls_before_invalidation":0,
          "reason":"prior process materialized full holdout before prediction seal; same holdout is not auto-rehabilitated by a runner change",
        },
      },
      "runners":{
        "halumem":binding(halu_new),
        "longmemeval":binding(lme_new),
      },
      "support_files":{
        "unknown_reconciliation":binding(reconcile),
        "halumem_judge_wrapper":binding(judge_wrapper),
        "longmemeval_score_wrapper":binding(lme_score),
      },
      "origin_runners":{
        "halumem":binding(halu_old),
        "longmemeval":binding(lme_old),
      },
      "common_reconciliation":{
        "decision":"TRANSPORT_ABSTAIN_NO_RETRY",
        "provider_retry":False,
        "durable_unknown_status_mutated":False,
        "unknown_creates_semantic_claim":False,
        "unknown_source_envelope_preserved":True,
        "committed_response_reuse_requires_exact_durable_hash":True,
        "new_provider_calls_only_for_never_attempted_case_ids":True,
      },
      "legacy_committed_receipts_index":{
        **binding(LEGACY_INDEX),"count":68,
        "all_request_hashes_present":True,
        "reuse_requires_request_hash_match":True,
      },
      "legacy_unknowns":[{
        "call_id":u["call_id"],"case_id":u["case_id"],"error_class":u["error_class"],
        "budget_scope":u["budget_scope"],"prompt_prefix_sha256":u["prompt_prefix_sha256"],
        "origin_manifest_sha256":sha(base_manifest),
        "origin_freeze_sha256":sha(base_freeze),
        "origin_runner_sha256":sha(halu_old),
      }],
      "halumem_recovery_seed":{
        "durable_committed":68,"durable_unknown":1,"reserved":0,
        "old_runtime_sealed":False,
        "new_runtime":"governance/halumem_confirmatory_runtime_v2",
        "checkpoint_contract":{
          "granularity":"completed_session",
          "immutable_sqlite_checkpoint_per_completed_session":True,
          "progress_references_exact_checkpoint_sha256":True,
          "restart_restores_last_referenced_checkpoint":True,
          "unreferenced_future_checkpoint_ignored":True,
          "work_db_never_authoritative_for_resume":True,
          "pre_dispatch_request_intent_required_for_new_calls":True,
          "legacy_committed_reuse_requires_original_request_hash":True,
        },
      },
      "judge":{
        "model":"qwen3.8-flash","enable_thinking":False,
        "binding":binding(judge_binding),
        "calibration_contract":binding(judge_cal),
        "wrapper_path":str(judge_wrapper.relative_to(ROOT)).replace("\\","/"),
        "wrapper_sha256":sha(judge_wrapper),
        "fresh_recovery_v2_calibration_required":"12/12",
        "prior_judge_receipts_reusable":False,
        "gold_scoring_before_prediction_seal":False,
      },
      "longmemeval_boundary":{
        "same_holdout_execution_allowed":False,
        "replacement_holdout_substitution_allowed":False,
        "separate_scientific_disposition_required":True,
        "recovery_runner_retained_for_future_independently_frozen_generation_only":True,
      },
      "execution_rules":{
        "provider_calls_allowed_before_recovery_final_freeze":False,
        "judge_calls_allowed_before_recovery_final_freeze":False,
        "gold_reads_allowed_before_prediction_seal":False,
        "old_partial_runtime_must_remain_immutable":True,
        "old_unknown_retry_forbidden":True,
        "e2_claim_allowed":False,
      },
    }
    OUT.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n","utf-8",newline="\n")
    print(json.dumps({"path":str(OUT.relative_to(ROOT)).replace("\\","/"),"sha256":sha(OUT),
      "halumem_counts":hcounts,"longmemeval_counts":lcounts,
      "halumem_runner_sha256":sha(halu_new),"reconciliation_sha256":sha(reconcile)},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
