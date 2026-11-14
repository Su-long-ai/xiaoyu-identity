# -*- coding: utf-8 -*-
"""Machine-enforced product benefit/Pareto gate, not a release or agent dispatcher.

M1 product RC source + M2 same-input final answers + A1 material-P0 are
separate proof types. Losses are recorded and traded off on total user
utility; an ordinary single loss is never a hard failure.
"""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
from answer_outcome_gate import evidence_eligibility, classify_delivery_trace

SCHEMA="xiaoyu-product-portfolio-e2e-v1"
POLICY="xiaoyu-final-answer-first-gate-v2"
HEX=set("0123456789abcdef")
WEIGHTS={"final_correct":1.0,"hallucination_avoided":1.5,
         "legitimate_state_improvement":1.0,"absolute_cost_cny_saved":1.0,
         "normalized_latency_saved":0.10}
P0_FIELDS=("unauthorized_persistent_commits","no_save_violations",
           "cross_owner_exposures","revoked_source_revivals",
           "false_external_send_claims")
TYPES={"single_hop","multi_hop","temporal","open_domain","correction",
       "lifecycle","privacy","document","natural_owner","cost","general"}
MIN_FRESH_PAIRS={"targeted":12,"broad":24}
OVERALL_CAPABILITY_MIN_N=100
ANSWER_CONTRACT_FAMILIES={"answer_contract_executor","answer_contract_execution",
                          "contract_driven_evidence_executor"}

def _answer_contract_prereq(r:dict)->dict:
 """Hard prerequisite for the new answer-contract direction.

 Legacy candidates are unaffected. A candidate that declares itself part of
 the answer-contract family cannot enter product pilot until the pre-registered
 manual-full-evidence diagnostic has established an independent answer-
 consumption/output benefit. This prevents another retrieval/proxy loop.
 """
 family=str(r.get("candidate_family") or "").strip().casefold()
 if family not in ANSWER_CONTRACT_FAMILIES:
  return {"required":False,"passed":True,"reasons":[]}
 d=r.get("answer_contract_diagnostic")
 if not isinstance(d,dict):
  return {"required":True,"passed":False,
          "reasons":["manual_full_evidence_diagnostic_missing"]}
 reasons=[]
 required_true=(
   "case_ids_frozen_before_run",
   "same_question_model_prompt_mode",
   "manual_evidence_gold_free",
   "actual_model_messages_recorded",
   "actual_model_input_sha_bound",
   "manual_full_evidence_intervention_completed",
   "executor_consumption_gain_observed",
 )
 for key in required_true:
  if d.get(key) is not True:
   reasons.append(key+"_not_proven")
 n=int(d.get("n") or 0)
 if n < 8:
  reasons.append("diagnostic_n_below_8")
 if d.get("used_fresh_claim_credit") is not False:
  reasons.append("diagnostic_must_not_count_as_fresh_capability_credit")
 return {"required":True,"passed":not reasons,"n":n,"reasons":reasons}

FAILURE_STAGES={"retrieval_miss","evidence_incomplete","source_conflict",
                "temporal_reasoning","general_reasoning","answer_incomplete","unknown"}
FAILURE_ALIASES={"reasoning_error":"general_reasoning",
                 "output_incomplete":"answer_incomplete"}
FAILURE_ACTIONS={
 "retrieval_miss":"FIX_RETRIEVAL_OR_QUERY_ROUTING",
 "evidence_incomplete":"FIX_EVIDENCE_PACKAGING_OR_REQUIRED_SUPPORT_DELIVERY",
 "source_conflict":"FIX_TEMPORAL_SOURCE_VERSION_RESOLUTION",
 "temporal_reasoning":"FIX_TEMPORAL_BINDING_AND_REASONING",
 "general_reasoning":"FIX_ANSWER_REASONING_OR_MODEL_ROUTE",
 "answer_incomplete":"FIX_REQUESTED_FIELD_AND_OUTPUT_PROTOCOL",
 "unknown":"DIAGNOSE_H_R_P_W_A_BEFORE_MORE_TUNING",
}
def _failure_stage(row:dict)->str:
 trace=classify_delivery_trace(row.get("candidate_delivery_trace"))
 if trace["stage"]!="unknown" and trace["verified"]:
  return trace["stage"]
 explicit=str(row.get("candidate_failure_stage") or "").strip().casefold()
 explicit=FAILURE_ALIASES.get(explicit,explicit)
 if explicit in FAILURE_STAGES:return explicit
 if row.get("candidate_output_complete") is False:return "answer_incomplete"
 if row.get("candidate_evidence_found") is False:return "retrieval_miss"
 if row.get("candidate_evidence_complete") is False:return "evidence_incomplete"
 if row.get("candidate_source_conflict") is True:return "source_conflict"
 if row.get("candidate_reasoning_correct") is False:return "general_reasoning"
 return "unknown"
def _next_research_action(counts:dict)->str:
 ranked=sorted(((v,k) for k,v in counts.items() if v>0),
               key=lambda z:(z[0],z[1]),reverse=True)
 return FAILURE_ACTIONS[ranked[0][1]] if ranked else "COLLECT_FRESH_FINAL_ANSWER_PAIRS"
def _sha(path:Path)->str:
 return hashlib.sha256(path.read_bytes()).hexdigest()
def _sha256(s):
 return isinstance(s,str) and len(s)==64 and all(c in HEX for c in s.lower())
def _check_manifest(path:str,expected:str)->dict:
 if not _sha256(expected):raise ValueError("manifest_sha256_required")
 p=Path(path)
 if not p.is_file() or _sha(p)!=expected:raise ValueError("manifest_sha_mismatch")
 m=json.loads(p.read_text("utf8"))
 root=Path(m.get("rc_root") or p.parent/("G"+p.name.split("G")[-1].split("_")[0]+"_RC"))
 if not root.is_dir():
  dirs=[x for x in p.parent.iterdir() if x.is_dir() and x.name.endswith("_RC")]
  if len(dirs)==1:root=dirs[0]
 if not root.is_dir():raise ValueError("manifest_product_root_missing")
 files=m.get("files_sha256") or {}
 if not isinstance(files,dict) or not files:raise ValueError("manifest_files_missing")
 for rel,digest in files.items():
  f=(root/rel).resolve()
  if not f.is_relative_to(root.resolve()) or not f.is_file() or _sha(f)!=digest:
   raise ValueError("product_code_sha_drift:"+str(rel))
 return {"manifest_sha256":expected,"members":len(files),"root":str(root)}
def assess_receipt(r:dict,*,verify_files=True)->dict:
 if r.get("schema")!=SCHEMA:raise ValueError("unsupported_portfolio_schema")
 cid=str(r.get("candidate_id") or "").strip()
 if not cid:raise ValueError("candidate_id_required")
 csha=r.get("candidate_manifest_sha256")
 bsha=r.get("baseline_manifest_sha256")
 if not _sha256(csha) or not _sha256(bsha):raise ValueError("both_manifest_sha_required")
 if verify_files:
  candidate=_check_manifest(r.get("candidate_manifest_path") or "",csha)
  baseline=_check_manifest(r.get("baseline_manifest_path") or "",bsha)
 else:
  candidate={"manifest_sha256":csha};baseline={"manifest_sha256":bsha}
 source=str(r.get("suite_id") or "")
 if not source:raise ValueError("suite_id_required")
 if bool(r.get("used_protected_gold_for_tuning")):raise ValueError("protected_gold_leakage")
 paths=r.get("product_path") or {}
 if not isinstance(paths,dict):raise ValueError("product_path_invalid")
 required=("same_input_paired","raw_history_replayed","real_final_answers",
           "runtime_route_observed","scope_authority_checked","rollback_available")
 source_ok=all(paths.get(x) is True for x in required)
 # Research that measured retrieval over the full authorized history must
 # prove the product can actually reach that history. This is opt-in and
 # backward-compatible: old/recent-bounded candidates are unchanged.
 full_history_retrieval=(str(r.get("research_retrieval_scope") or "").strip().casefold()
                         =="full_history")
 reachability_proven=(paths.get("historical_reachability_checked") is True
                      and paths.get("research_candidate_pool_reproduced") is True)
 if full_history_retrieval:
  source_ok=source_ok and reachability_proven
 rows=r.get("cases") or []
 if not isinstance(rows,list):raise ValueError("cases_must_be_list")
 from product_pair_evidence import check_output_integrity
 raw_output_quality=check_output_integrity(r.get("paired_evidence"),rows)
 invalid_baseline=set(raw_output_quality.get("invalid_baseline_ids",[]))
 invalid_candidate=set(raw_output_quality.get("invalid_candidate_ids",[]))
 by_type={};seen=set();wins=losses=both=neither=0;hgain=0;state_gain=0;delta_money=0.;delta_time=0.
 total_base_cost=total_base_ms=0.
 failures=[];loss_unknown=[];candidate_incorrect=0
 diagnostic_counts={k:0 for k in FAILURE_STAGES}
 for x in rows:
  if not isinstance(x,dict):raise ValueError("invalid_case")
  ident=str(x.get("id") or "").strip()
  if not ident or ident in seen:raise ValueError("missing_or_duplicate_case_id")
  seen.add(ident)
  cat=str(x.get("type") or "general")
  if cat not in TYPES:raise ValueError("unrecognized_case_type:"+cat)
  a=x.get("baseline_correct");b=x.get("candidate_correct")
  if ident in invalid_baseline:a=False
  if ident in invalid_candidate:b=False
  if type(a) is not bool or type(b) is not bool:
   raise ValueError("final_answer_pair_must_be_boolean")
  if a and b:both+=1
  elif a and not b:losses+=1;failures.append(ident)
  elif b and not a:wins+=1
  else:neither+=1
  if not b:
   stage=_failure_stage(x)
   diagnostic_counts[stage]+=1;candidate_incorrect+=1
   if a and stage=="unknown":loss_unknown.append(ident)
  t=by_type.setdefault(cat,{"n":0,"wins":0,"losses":0})
  t["n"]+=1;t["wins"]+=int(b and not a);t["losses"]+=int(a and not b)
  ha=x.get("baseline_hallucinated");hb=x.get("candidate_hallucinated")
  if ha is not None or hb is not None:
   if type(ha) is not bool or type(hb) is not bool:raise ValueError("hallucination_pair_invalid")
   hgain+=int(ha)-int(hb)
  sa=x.get("baseline_legitimate_state_correct");sb=x.get("candidate_legitimate_state_correct")
  if sa is not None or sb is not None:
   if type(sa) is not bool or type(sb) is not bool:raise ValueError("legitimate_state_pair_invalid")
   state_gain+=int(sb)-int(sa)
  for field in ("baseline_cost_cny","candidate_cost_cny",
                "baseline_latency_ms","candidate_latency_ms"):
   if field in x and (type(x[field]) not in (int,float) or not math.isfinite(x[field]) or x[field]<0):
    raise ValueError("invalid_numeric_"+field)
  if "baseline_cost_cny" in x and "candidate_cost_cny" in x:
   delta_money+=x["baseline_cost_cny"]-x["candidate_cost_cny"]
   total_base_cost+=x["baseline_cost_cny"]
  if "baseline_latency_ms" in x and "candidate_latency_ms" in x:
   delta_time+=x["baseline_latency_ms"]-x["candidate_latency_ms"]
   total_base_ms+=x["baseline_latency_ms"]
 p0=r.get("observed_p0") or {}
 if not isinstance(p0,dict):raise ValueError("material_p0_invalid")
 if any(type(p0.get(k,0)) is not int or p0.get(k,0)<0 for k in P0_FIELDS):
  raise ValueError("material_p0_counts_invalid")
 material=sum(p0.get(k,0) for k in P0_FIELDS)
 audited=bool(r.get("same_sha_a1_reviewed") is True and r.get("same_sha_a1_material_p0") is False)
 from product_pair_evidence import check as verify_raw_paired
 actual_pairs_verified=verify_raw_paired(r.get("paired_evidence"),rows,bsha,csha)
 quality=evidence_eligibility(r.get("evaluation_provenance"))
 answer_contract_prereq=_answer_contract_prereq(r)
 n=len(rows)
 raw_scope=str(r.get("scope_type") or "broad").strip().casefold()
 scope=raw_scope if raw_scope in MIN_FRESH_PAIRS else "broad"
 scope_inferred_from_legacy=raw_scope not in MIN_FRESH_PAIRS
 min_fresh_pairs=MIN_FRESH_PAIRS[scope]
 net_final_correct=wins-losses
 loss_diagnostics_complete=not loss_unknown
 judge_independent=bool(
  r.get("semantic_judge_independent") is True or
  str(r.get("judging_mode") or "").strip().casefold() in ("independent","deterministic_gold"))
 next_research_action=_next_research_action(diagnostic_counts)
 # Savings are bounded to avoid one noisy millisecond or token case dominating.
 cost_fraction=max(-1.,min(1.,delta_money/total_base_cost)) if total_base_cost>0 else 0
 time_fraction=max(-1.,min(1.,delta_time/total_base_ms)) if total_base_ms>0 else 0
 utility=(wins-losses)+WEIGHTS["hallucination_avoided"]*hgain+WEIGHTS["legitimate_state_improvement"]*state_gain
 # Small CNY differences must not dominate correct-answer gains merely
 # because a suite has many questions. Keep the fractional price signal
 # for Pareto reporting, but utility charges actual absolute CNY proxy.
 utility+=WEIGHTS["absolute_cost_cny_saved"]*delta_money+n*WEIGHTS["normalized_latency_saved"]*time_fraction
 route_count=int(r.get("candidate_mechanism_trigger_count",0))
 if route_count<0:raise ValueError("negative_trigger_count")
 pilot_ready=bool(
  net_final_correct>0 and n>=min_fresh_pairs and audited and
  actual_pairs_verified and raw_output_quality["verified"] and
  quality["pilot_eligible"] and loss_diagnostics_complete and
  answer_contract_prereq["passed"])
 overall_capability_claim_eligible=bool(
  pilot_ready and scope=="broad" and n>=OVERALL_CAPABILITY_MIN_N and
  len(by_type)>=3 and judge_independent)
 if material or r.get("known_material_p0") is True:
  verdict="HOLD_MATERIAL_P0_REPAIR_NEW_SHA"
 elif not answer_contract_prereq["passed"]:
  verdict="HOLD_ANSWER_CONTRACT_DIAGNOSTIC_REQUIRED"
 elif not source_ok or route_count==0:
  verdict="HOLD_NO_TRUE_ACTIVE_PRODUCT_PATH"
 elif n==0:
  verdict="NEED_REAL_FINAL_ANSWER_PAIRS"
 elif n<4:
  verdict="SMALL_TRIAL_MORE_EVIDENCE"
 elif net_final_correct>0:
  verdict=("PILOT_REVIEW_READY_NO_AUTO_RELEASE" if pilot_ready
           else "PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
 elif (hgain>0 or state_gain>0 or cost_fraction>=0.10 or
       time_fraction>=0.20 or wins>0):
  verdict="CONDITIONAL_PARETO_RESCUE"
 elif net_final_correct==0:
  verdict="NEUTRAL_OPTIONAL_TRIAL"
 else:
  verdict="REVISE_OR_SCOPED_RETEST"
 return {"schema":"xiaoyu-product-benefit-gate-result-v1","policy":POLICY,
   "candidate_id":cid,"candidate":candidate,"baseline":baseline,
   "suite_id":source,"n":n,"by_type":by_type,
   "baseline_correct":both+losses,"candidate_correct":both+wins,
   "wins":wins,"losses":losses,"both_correct":both,"both_wrong":neither,
   "net_final_correct":net_final_correct,"ordinary_loss_case_ids":failures,
   "final_answer_gate_pass":net_final_correct>0,
   "scope_type":scope,"scope_type_original":raw_scope,
   "scope_type_inferred_from_legacy":scope_inferred_from_legacy,
   "min_fresh_pairs_for_pilot":min_fresh_pairs,
   "fresh_pair_count_sufficient":n>=min_fresh_pairs,
   "loss_diagnostics_complete":loss_diagnostics_complete,
   "undiagnosed_loss_case_ids":loss_unknown,
   "candidate_incorrect_count":candidate_incorrect,
   "failure_stage_counts":diagnostic_counts,
   "next_research_action":next_research_action,
   "hallucination_net_avoided":hgain,"legitimate_state_net":state_gain,
   "cost_saved_cny":round(delta_money,6),"cost_saved_fraction":round(cost_fraction,5),
   "latency_saved_fraction":round(time_fraction,5),
   "utility":round(utility,5),"weights":WEIGHTS,
   "material_p0":material,"source_and_route_proven":source_ok,
   "historical_reachability_required":full_history_retrieval,
   "historical_reachability_proven":(reachability_proven if full_history_retrieval else None),
   "mechanism_trigger_count":route_count,"same_sha_a1_pass":audited,
   "raw_paired_evidence_verified":actual_pairs_verified,
   "evaluation_evidence":quality,
   "pilot_provenance_verified":quality["pilot_eligible"],
   "semantic_judge_independent":judge_independent,
   "overall_capability_claim_min_n":OVERALL_CAPABILITY_MIN_N,
   "overall_capability_claim_eligible":overall_capability_claim_eligible,
   "answer_contract_prerequisite":answer_contract_prereq,
   "raw_output_integrity":raw_output_quality,
   "invalidated_baseline_case_ids":sorted(invalid_baseline),
   "invalidated_candidate_case_ids":sorted(invalid_candidate),
   "verdict":verdict,"hard_gate":verdict.startswith(
      ("HOLD_MATERIAL","HOLD_NO_TRUE","HOLD_ANSWER_CONTRACT")),
   "default_on":False,"automatic_release":False,
   "evaluation_note":"FINAL-ANSWER-FIRST: retrieval/state/cost gains diagnose or rescue research only. Product pilot requires fresh/disjoint paired real final answers with net_final_correct > 0; overall capability claims require >=100 broad fresh pairs and independent/deterministic judging."}
def load_and_assess(path):
 p=Path(path);out=assess_receipt(json.loads(p.read_text("utf8")))
 return dict(out,receipt_sha256=_sha(p),receipt_path=str(p.resolve()))
def main():
 p=argparse.ArgumentParser();p.add_argument("--receipt",required=True)
 args=p.parse_args()
 print(json.dumps(load_and_assess(args.receipt),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
