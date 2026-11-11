#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only E2 confirmatory pre-freeze doctor.

Never reads confirmatory benchmark contents. It uses only the already-frozen
split membership, governance receipts/hashes, and paid-call ledger.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def evaluate():
    split_path=GOV/"E2_SPLIT_MANIFEST.json"
    cand_path=GOV/"E2_CONFIRMATORY_PROTOCOL_CANDIDATE_V2.json"
    bind_path=GOV/"E2_CONFIRMATORY_IMPLEMENTATION_BINDINGS.json"
    backlog_path=GOV/"RESEARCH_BACKLOG.json"
    split=load(split_path); cand=load(cand_path); bindings=load(bind_path); backlog=load(backlog_path)
    policy=load(GOV/"policy.json")
    errors=[]; blockers=[]; warnings=[]
    def err(ok,typ,**extra):
        if not ok: errors.append({"type":typ,**extra})

    err(cand.get("schema")=="xiaoyu-e2-confirmatory-protocol-candidate-v2","candidate_schema")
    err(cand.get("status") in (
        "BLOCKED_PREFREEZE",
        "PREFREEZE_COMPLETE_WAITING_FINAL_INDEPENDENT_REAUDIT",
        "PREFREEZE_COMPLETE_WAITING_FINAL_INDEPENDENT_V2_REAUDIT",
    ),"candidate_prefreeze_status",actual=cand.get("status"))
    err(cand.get("split_manifest",{}).get("sha256")==sha(split_path),"split_hash_drift")
    err(cand.get("implementation_bindings",{}).get("sha256")==sha(bind_path),"bindings_hash_drift")
    err(cand.get("execution_rules",{}).get("confirmatory_calls_allowed") is False,
        "candidate_confirmatory_calls_must_be_false")
    err(cand.get("e2_claim_allowed") is False,"candidate_e2_claim_must_be_false")

    # Exact accepted implementation artifacts.
    for rid,row in (bindings.get("components") or {}).items():
        art=row.get("artifact") or {}
        p=ROOT/str(art.get("path") or "")
        err(p.is_file(),"bound_artifact_missing",component=rid,path=str(p))
        if p.is_file():
            err(sha(p)==art.get("expected_sha256")==art.get("actual_sha256"),
                "bound_artifact_hash_drift",component=rid,actual=sha(p))
        review=row.get("review") or {}
        err(review.get("decision")=="ACCEPT_E1","bound_review_not_accept_e1",component=rid)
        err(review.get("reviewer_id")=="xy-auditor-independent-20261026-01",
            "bound_review_not_independent",component=rid)

    # Exact R51 dependency closure and tracked LME runner must remain hash-bound.
    r51_binding=(bindings.get("components") or {}).get("R51") or {}
    for name,meta in (r51_binding.get("dependency_closure") or {}).items():
        p=ROOT/str(meta.get("path") or "")
        err(p.is_file(),"r51_dependency_missing",name=name,path=str(p))
        if p.is_file():
            err(sha(p)==meta.get("sha256"),"r51_dependency_hash_drift",name=name,actual=sha(p))
    lme_runner_binding=bindings.get("longmemeval_confirmatory_runner") or {}
    lme_runner_path=ROOT/str(lme_runner_binding.get("path") or "")
    err(lme_runner_path.is_file(),"lme_runner_binding_missing",path=str(lme_runner_path))
    if lme_runner_path.is_file():
        err(sha(lme_runner_path)==lme_runner_binding.get("sha256"),
            "lme_runner_hash_drift",actual=sha(lme_runner_path))
    err(lme_runner_binding.get("evaluator_metadata_forbidden") is True,
        "lme_runner_evaluator_metadata_guard_missing")

    # R51 is the reopened semantic-binding research blocker.
    r51=next((x for x in backlog.get("candidates",[]) if x.get("id")=="R51"),None)
    if r51 is None:
        blockers.append({"id":"R51","reason":"backlog row missing"})
    elif not (r51.get("status")=="done" and r51.get("completion_level")=="ACCEPT_E1"):
        blockers.append({"id":"R51","reason":"semantic binding not independently ACCEPT_E1",
                         "status":r51.get("status"),"completion_level":r51.get("completion_level")})

    # R52 is the final HaluMem end-to-end research dependency. A runner file
    # must never substitute for independent acceptance of the composition itself.
    r52=next((x for x in backlog.get("candidates",[]) if x.get("id")=="R52"),None)
    if r52 is None:
        blockers.append({"id":"R52","reason":"HaluMem composition backlog row missing"})
    elif not (r52.get("status")=="done" and r52.get("completion_level")=="ACCEPT_E1"):
        blockers.append({"id":"R52","reason":"HaluMem open-domain composition not independently ACCEPT_E1",
                         "status":r52.get("status"),"completion_level":r52.get("completion_level")})

    # Candidate explicitly carries unresolved execution/judge gates.
    for b in cand.get("blockers",[]):
        bid=str(b.get("id") or "")
        if bid=="R51" and r51 and r51.get("status")=="done" and r51.get("completion_level")=="ACCEPT_E1":
            continue
        # Final-runner existence/hash is audited below from the filesystem and
        # implementation bindings. Do not double-count the candidate's design
        # placeholder as a second blocker for the same missing runner.
        if bid in ("LME_INTEGRATED_RUNNER","HALUMEM_CONFIRMATORY_RUNNER"):
            continue
        bstatus=str(b.get("status") or "")
        if bstatus not in ("CLOSED","RESOLVED","ACCEPT_E1") and not bstatus.startswith("CLOSED_"):
            blockers.append({"id":bid,"reason":b.get("required"),"status":b.get("status")})

    # Paid ledger anti-peeking: only split IDs/UUID hashes are consulted, never dataset contents.
    db=GOV/"research_api_usage.sqlite3"
    confirm_lme={f"lme-a-{int(i):03d}" for i in split["longmemeval"]["confirmatory_indices"]}
    confirm_lme|={f"lme-c-{int(i):03d}" for i in split["longmemeval"]["confirmatory_indices"]}
    confirm_halu_prefixes={hashlib.sha256(str(u).encode("utf-8")).hexdigest()[:12]
                           for u in split["halumem"]["confirmatory_uuids"]}
    touched_lme=[]; touched_halu=[]; reserved=[]; unknown=[]
    if not db.is_file():
        errors.append({"type":"paid_ledger_missing"})
    else:
        con=sqlite3.connect(db); con.row_factory=sqlite3.Row
        rows=con.execute("""select call_id,status,phase,budget_scope,case_id
                            from calls where phase='benchmark'""").fetchall()
        con.close()
        for r in rows:
            cid=str(r["case_id"] or "")
            if cid in confirm_lme:
                touched_lme.append({"call_id":r["call_id"],"case_id":cid})
            if cid and any(f"-{h}-" in cid or cid.endswith("-"+h) for h in confirm_halu_prefixes):
                touched_halu.append({"call_id":r["call_id"],"case_id":cid})
            if r["status"]=="RESERVED":reserved.append(r["call_id"])
            if r["status"]=="UNKNOWN":unknown.append(r["call_id"])
    err(not touched_lme,"confirmatory_lme_paid_call_detected",calls=touched_lme[:10])
    err(not touched_halu,"confirmatory_halumem_paid_call_detected",calls=touched_halu[:10])
    err(not reserved,"benchmark_reserved_calls_present",calls=reserved[:10])
    err(not unknown,"benchmark_unknown_calls_present",calls=unknown[:10])

    # Independent prefreeze auditor state (read registry metadata only).
    reg=GOV/"registry.sqlite3"
    auditor_state=None
    if reg.is_file():
        con=sqlite3.connect(reg);con.row_factory=sqlite3.Row
        row=con.execute("""select lease_id,agent_id,state,workspace,heartbeat_at
                           from leases where family='audit.e2.confirmatory.prefreeze_readiness'
                           order by claimed_at desc limit 1""").fetchone()
        con.close()
        if row:auditor_state=dict(row)
    if auditor_state is None:
        blockers.append({"id":"INDEPENDENT_PREFREEZE_AUDIT","reason":"no audit lease found"})
    elif auditor_state.get("state")!="SUBMITTED":
        blockers.append({"id":"INDEPENDENT_PREFREEZE_AUDIT","reason":"audit not submitted",
                         "state":auditor_state.get("state"),"lease_id":auditor_state.get("lease_id")})

    # HaluMem judge binding: exact official prompts/config + frozen calibration.
    judge_ref=bindings.get("halumem_official_scorer_reference") or {}
    judge_status=judge_ref.get("judge_model_binding_status")
    if judge_status!="FROZEN_ALTERNATIVE_QWEN_CONFIRMATORY_BINDING":
        blockers.append({"id":"HALUMEM_JUDGE","reason":"judge/scorer comparability not frozen",
                         "status":judge_status})
    else:
        jb=judge_ref.get("final_judge_binding") or {}
        jp=ROOT/str(jb.get("path") or "")
        err(jp.is_file(),"halumem_judge_binding_missing",path=str(jp))
        judge_obj=None
        if jp.is_file():
            err(sha(jp)==jb.get("sha256"),"halumem_judge_binding_hash_drift",actual=sha(jp))
            judge_obj=load(jp)
            err(judge_obj.get("status")=="FROZEN_ALTERNATIVE_QWEN_CONFIRMATORY_BINDING",
                "halumem_judge_binding_status")
            jcfg=judge_obj.get("judge") or {}
            err(jcfg.get("provider")=="alibaba_model_studio" and jcfg.get("model_id")=="qwen3.8-flash"
                and float(jcfg.get("temperature"))==0.0 and int(jcfg.get("max_tokens"))==16384
                and jcfg.get("enable_thinking") is False,
                "halumem_judge_reference_config_drift")
            err(jcfg.get("substitution_allowed") is False,
                "halumem_judge_substitution_must_be_false")
        cal=judge_ref.get("calibration") or {}
        cp=ROOT/str(cal.get("path") or "")
        err(cp.is_file(),"halumem_judge_calibration_missing",path=str(cp))
        if cp.is_file():
            err(sha(cp)==cal.get("sha256"),"halumem_judge_calibration_hash_drift",actual=sha(cp))
            co=load(cp)
            err(len(co.get("cases") or [])==12 and co.get("gate",{}).get("required_pass")==12,
                "halumem_judge_calibration_contract_drift")
        if not os.getenv("DASHSCOPE_API_KEY"):
            warnings.append({"id":"HALUMEM_JUDGE_RUNTIME_CREDENTIAL",
                             "reason":"DASHSCOPE_API_KEY not present; frozen Qwen judge execution remains impossible until credential is supplied. No substitution is allowed."})

    # Halu final-runner v2 contract: verify the exact promoted runtime,
    # prediction/gold boundary and non-executable final execution spec.
    hc=bindings.get("halumem_confirmatory_runner_contract") or {}
    hcp=ROOT/str(hc.get("path") or "")
    err(hcp.is_file(),"halumem_runner_contract_missing",path=str(hcp))
    if hcp.is_file():
        err(sha(hcp)==hc.get("sha256"),"halumem_runner_contract_hash_drift",actual=sha(hcp))
        hco=load(hcp)
        err(hco.get("schema")=="xiaoyu-halumem-confirmatory-runner-contract-v2"
            and hco.get("status")=="PREFREEZE_FINAL_RUNNER_BOUND_WAITING_FINAL_V2_REAUDIT",
            "halumem_runner_contract_status_drift",schema=hco.get("schema"),status=hco.get("status"))
        ss=hco.get("scientific_scope") or {}
        err(ss.get("split_sha256")==sha(split_path)
            and int(ss.get("confirmatory_users") or 0)==18
            and ss.get("confirmatory_reads_before_final_freeze_forbidden") is True,
            "halumem_runner_contract_scientific_scope_drift")
        exspec=hco.get("exact_execution_spec") or {}
        exspec_path=ROOT/str(exspec.get("path") or "")
        err(exspec_path.is_file()
            and sha(exspec_path)==exspec.get("sha256")
            and exspec.get("confirmatory_execution_allowed") is False,
            "halumem_runner_contract_execution_spec_drift",
            actual=sha(exspec_path) if exspec_path.is_file() else None)
        promoted=hco.get("promoted_runtime") or {}
        r52p=promoted.get("r52_entrypoint") or {}
        r52pp=ROOT/str(r52p.get("path") or "")
        err(promoted.get("r52_submission_id")=="sub-0cc4e587fc8a46d4"
            and promoted.get("r52_review_id")=="review-c4b018f60f754002"
            and r52pp.is_file() and sha(r52pp)==r52p.get("sha256"),
            "halumem_runner_contract_r52_promotion_guard")
        sem=promoted.get("semantic_projector") or {}
        sem_path=ROOT/str(sem.get("path") or "")
        err(sem_path.is_file(),"halumem_semantic_projector_contract_missing",path=str(sem_path))
        if sem_path.is_file():
            err(sha(sem_path)==sem.get("sha256"),
                "halumem_semantic_projector_contract_hash_drift",actual=sha(sem_path))
            import importlib.util
            spec=importlib.util.spec_from_file_location("_prefreeze_r49_v5",sem_path)
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            actual_prompt_sha=mod.prompt_sha256()
            actual_schema_sha=mod.schema_sha256()
            prefix=[{"role":"system","content":mod.SYSTEM_PROMPT}]
            actual_prefix_sha=hashlib.sha256(
                json.dumps(prefix,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
            ).hexdigest()
        else:
            actual_prompt_sha=actual_schema_sha=actual_prefix_sha=None
        err(sem.get("system_prompt_sha256")==actual_prompt_sha
            and actual_prompt_sha=="663588d26d4e7dbc46de4d98703544be06ddd90359c08e78b1b9b198fe5de048"
            and sem.get("schema_sha256")==actual_schema_sha
            and actual_schema_sha=="2ec9e15291c87750e5e421e52c915a4cc321e7be64cb8d94ee9d5a97dfaf44a8"
            and sem.get("invariant_prefix_sha256")==actual_prefix_sha
            and actual_prefix_sha=="bcbd2f5a28c7c7474d8160c9304006317f9cac8313152249d25d2020fe27279b"
            and sem.get("assistant_provider_projection_allowed") is False
            and sem.get("synthetic_fixture_projector_promotion_forbidden") is True,
            "halumem_semantic_projector_boundary_drift",
            actual_prompt_sha256=actual_prompt_sha,actual_schema_sha256=actual_schema_sha,
            actual_invariant_prefix_sha256=actual_prefix_sha)
        legacy=promoted.get("legacy_r49_provider_contract") or {}
        err(legacy.get("promoted") is False
            and (legacy.get("compatibility_audit") or {}).get("all_legacy_accepted_survive_v5") is False,
            "halumem_legacy_projector_promotion_guard_drift")
        destructive=promoted.get("destructive_transition") or {}
        err(destructive.get("explicit_caller_or_user_confirmation_required") is True
            and destructive.get("auto_confirm_allowed") is False
            and destructive.get("unconfirmed_destructive_mutates_authoritative_state") is False,
            "halumem_destructive_confirmation_guard_drift")
        pb=hco.get("prediction_boundary") or {}
        err(pb.get("stage_order")==["prediction","seal_predictions","judge_calibration","gold_scoring"]
            and int(pb.get("expected_prediction_files") or 0)==36
            and pb.get("all_predictions_sealed_before_any_gold_read") is True
            and pb.get("selective_structural_json_parser_required") is True,
            "halumem_runner_contract_stage_order_drift",stages=pb.get("stage_order"))
        forbidden=set(pb.get("forbidden_before_seal") or [])
        err({"persona_info","memory_points","questions[].answer","questions[].evidence",
             "questions[].difficulty","questions[].question_type","token_cost"}.issubset(forbidden),
            "halumem_prediction_gold_boundary_drift")
        paid=hco.get("paid_execution") or {}
        err(paid.get("prefreeze_paid_calls_forbidden") is True
            and paid.get("final_freeze_record_required") is True
            and paid.get("duplicate_paid_case_forbidden") is True
            and paid.get("reserved_or_unknown_blocks_retry_and_seal") is True,
            "halumem_runner_contract_execution_guards")

    # Exact final runners and accepted R52 closure must remain hash-bound.
    expected={
      "LME_INTEGRATED_RUNNER":GOV/"confirmatory_frozen"/"LME_CONFIRMATORY_RUNNER.py",
      "HALUMEM_CONFIRMATORY_RUNNER":GOV/"confirmatory_frozen"/"HALUMEM_CONFIRMATORY_RUNNER.py",
    }
    for bid,p in expected.items():
        if not p.is_file():
            blockers.append({"id":bid,"reason":"tracked final runner missing","path":str(p)})
        elif bid=="LME_INTEGRATED_RUNNER":
            if str(lme_runner_binding.get("path") or "")!="governance/confirmatory_frozen/LME_CONFIRMATORY_RUNNER.py":
                errors.append({"type":"lme_runner_binding_path_drift",
                               "path":lme_runner_binding.get("path")})
        else:
            hb=bindings.get("halumem_confirmatory_runner") or {}
            err(str(hb.get("path") or "")=="governance/confirmatory_frozen/HALUMEM_CONFIRMATORY_RUNNER.py",
                "halumem_runner_binding_path_drift",path=hb.get("path"))
            err(sha(p)==hb.get("sha256"),"halumem_runner_hash_drift",actual=sha(p))
            err(hb.get("provider_calls_during_prefreeze")==0
                and hb.get("confirmatory_reads_during_prefreeze")==0
                and hb.get("execution_freeze_required") is True,
                "halumem_runner_prefreeze_guard_drift")

    r52_binding=(bindings.get("components") or {}).get("R52") or {}
    for name,expected_sha in (r52_binding.get("dependency_closure") or {}).items():
        p=GOV/"confirmatory_frozen"/name
        err(p.is_file(),"r52_dependency_missing",name=name,path=str(p))
        if p.is_file():
            err(sha(p)==expected_sha,"r52_dependency_hash_drift",name=name,actual=sha(p))
    for name,expected_sha in (r52_binding.get("runtime_assets") or {}).items():
        p=GOV/"confirmatory_frozen"/name
        err(p.is_file(),"r52_runtime_asset_missing",name=name,path=str(p))
        if p.is_file():
            err(sha(p)==expected_sha,"r52_runtime_asset_hash_drift",name=name,actual=sha(p))

    # One exact non-executable manifest freezes BOTH confirmatory tracks.
    e2=policy.get("e2_transition") or {}
    em_rel=str(e2.get("confirmatory_execution_manifest") or "")
    em=ROOT/em_rel if em_rel else None
    err(em is not None and em.is_file(),"confirmatory_execution_manifest_missing",path=em_rel)
    if em is not None and em.is_file():
        em_sha=sha(em);exp_sha=e2.get("confirmatory_execution_manifest_sha256")
        err(em_sha==exp_sha,"confirmatory_execution_manifest_hash_drift",actual=em_sha,expected=exp_sha)
        emo=load(em)
        err(emo.get("schema")=="xiaoyu-e2-confirmatory-execution-manifest-v1"
            and emo.get("status")=="FROZEN_SPEC_AWAITING_FINAL_FREEZE"
            and emo.get("confirmatory_execution_allowed") is False,
            "confirmatory_execution_manifest_not_prefreeze_locked")
        tracks=emo.get("tracks") or {}
        lmt=tracks.get("longmemeval_answer") or {}
        hmt=tracks.get("halumem_semantic_projection") or {}
        err(len(lmt.get("allowed_case_ids") or [])==454
            and len(set(lmt.get("allowed_case_ids") or []))==454,
            "lme_confirmatory_membership_not_exact_454")
        err(len(hmt.get("allowed_uuid_hashes") or [])==18
            and len(set(hmt.get("allowed_uuid_hashes") or []))==18,
            "halumem_confirmatory_membership_not_exact_18")
        err(lmt.get("scope")=="proxy:xiaoyu:e2_lme_confirmatory_v1"
            and hmt.get("scope")=="proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
            "confirmatory_scope_binding_drift")
        gw=emo.get("gateway") or {}
        for key,path in (
          ("gate_sha256",GOV/"e2_confirmatory_execution.py"),
          ("research_api_sha256",GOV/"research_api.py"),
          ("research_api_proxy_sha256",GOV/"research_api_proxy.py"),
        ):
            err(path.is_file() and sha(path)==gw.get(key),
                "confirmatory_gateway_hash_drift",component=key,
                actual=sha(path) if path.is_file() else None,expected=gw.get(key))
    err(e2.get("current_stage")=="E2_CONFIRMATORY_PREFREEZE"
        and e2.get("confirmatory_calls_allowed") is False
        and not e2.get("confirmatory_freeze_record")
        and not e2.get("confirmatory_freeze_record_sha256"),
        "confirmatory_prefreeze_policy_lock_drift")

    # Deduplicate blockers by id/reason/status.
    seen=set();dedup=[]
    for b in blockers:
        key=json.dumps(b,ensure_ascii=False,sort_keys=True)
        if key not in seen:seen.add(key);dedup.append(b)
    blockers=dedup
    return {
      "schema":"xiaoyu-e2-confirmatory-prefreeze-doctor-v1",
      "candidate_sha256":sha(cand_path),
      "split_sha256":sha(split_path),
      "bindings_sha256":sha(bind_path),
      "confirmatory_paid_exposure":{"longmemeval_calls":len(touched_lme),
                                    "halumem_calls":len(touched_halu)},
      "benchmark_inflight":{"reserved":len(reserved),"unknown":len(unknown)},
      "r51":{"status":r51.get("status") if r51 else None,
             "completion_level":r51.get("completion_level") if r51 else None},
      "r52":{"status":r52.get("status") if r52 else None,
             "completion_level":r52.get("completion_level") if r52 else None},
      "auditor":auditor_state,
      "errors":errors,"warnings":warnings,"blockers":blockers,
      "healthy":not errors,
      "freeze_allowed":not errors and not blockers,
      "confirmatory_execution_allowed":False,
      "e2_claim_allowed":False,
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--require-freeze-ready",action="store_true")
    a=ap.parse_args();out=evaluate()
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if a.require_freeze_ready and not out["freeze_allowed"]:raise SystemExit(3)

if __name__=="__main__":main()
