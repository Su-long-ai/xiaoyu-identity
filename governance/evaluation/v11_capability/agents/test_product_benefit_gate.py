# -*- coding: utf-8 -*-
"""Public deterministic machine-gate tests: candidate Pareto, real answer pairs,
safety hard gates, receipt bytes, exact SHA, historical rescue, no autorun release.
"""
import copy,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import product_benefit_gate as gate
import product_promotion_machine as machine
import product_promotion_loop as loop

SCHEMA="""CREATE TABLE tasks(
 id TEXT PRIMARY KEY,role TEXT NOT NULL,track TEXT NOT NULL,priority INTEGER NOT NULL,
 title TEXT NOT NULL,acceptance TEXT NOT NULL,inputs TEXT NOT NULL,status TEXT NOT NULL,
 owner TEXT,artifact TEXT,blocked_reason TEXT,updated_at REAL)"""
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class ProductPortfolioMachineGateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.d=Path(self.tmp.name)
  self.base,self.base_sha=self.manifest("baseline")
  self.candidate,self.candidate_sha=self.manifest("candidate")
  self.receipt=self.data()
  self.make_bundle(self.receipt)
 def make_bundle(self,obj):
  answers=[]
  judgments=[]
  for c in obj["cases"]:
   for arm,field,sha in (("G26","baseline_correct",self.base_sha),
                         ("G27","candidate_correct",self.candidate_sha)):
    answers.append({"id":c["id"],"arm":arm,"question":"Question "+c["id"],
       "manifest_sha256":sha,"source_history_sha256":"original-synthetic-owner-history-"+c["id"],
       "dataset_sha256":"public-synthetic-verified-input",
       "status":"ANSWERED","source_auth_checked":True,"route_observed":True,
       "response":"Actual model-output fixture","finish_reason":"stop",
       "usage":{"prompt_tokens":int(round(c[
          "baseline_cost_cny" if arm=="G26" else "candidate_cost_cny"]*500000)),
          "completion_tokens":0}})
    judgments.append({"id":c["id"],"arm":arm,"type":c["type"],"correct":c[field]})
  a=self.d/"paired_answers.json";j=self.d/"paired_judgments.json"
  a.write_text(json.dumps({"status":"COMPLETE",
        "input_sha256":"public-synthetic-verified-input","predictions":answers})+"\n","utf8")
  j.write_text(json.dumps({"answer_sha256":digest(a),"judgments":judgments})+"\n","utf8")
  obj["paired_evidence"]={"kind":"public24_real_product_answers_v1",
   "answers_path":str(a),"answers_sha256":digest(a),
   "judgments_path":str(j),"judgments_sha256":digest(j),
   "baseline_arm":"G26","candidate_arm":"G27"}
 def manifest(self,tag):
  root=self.d/(tag+"_RC");root.mkdir()
  code=root/"core.py";code.write_text(f"ROLE={tag!r}\n","utf8")
  m=self.d/(tag+"_manifest.json")
  m.write_text(json.dumps({"schema":"candidate","rc_root":str(root),
      "files_sha256":{"core.py":digest(code)}},indent=2)+"\n","utf8")
  return m,digest(m)
 def data(self):
  cases=[]
  for i in range(12):
   a=(i%3!=0); b=a
   if i in (0,3,6):b=True
   if i==1:b=False
   cases.append({"id":f"public-test-{i:02d}","type":
       ("temporal" if i%3==0 else "multi_hop" if i%3==1 else "single_hop"),
       "baseline_correct":a,"candidate_correct":b,
       "baseline_hallucinated":False,"candidate_hallucinated":False,
       "baseline_cost_cny":0.01,"candidate_cost_cny":0.009,
       "baseline_latency_ms":100,"candidate_latency_ms":105,
       **({"candidate_failure_stage":"reasoning_error"} if a and not b else {})})
  return {"schema":gate.SCHEMA,"candidate_id":"auto-d2-x901",
     "baseline_manifest_path":str(self.base),
     "candidate_manifest_path":str(self.candidate),
     "baseline_manifest_sha256":self.base_sha,
     "candidate_manifest_sha256":self.candidate_sha,
     "suite_id":"public-source-disjoint-v1",
     "scope_type":"targeted",
     "cases":cases,
     "product_path":{k:True for k in
       ("same_input_paired","raw_history_replayed","real_final_answers",
        "runtime_route_observed","scope_authority_checked","rollback_available")},
     "candidate_mechanism_trigger_count":12,
     "semantic_judge_independent":True,
     "same_sha_a1_reviewed":True,"same_sha_a1_material_p0":False,
     "observed_p0":{"unauthorized_persistent_commits":0,"no_save_violations":0,
       "cross_owner_exposures":0,"revoked_source_revivals":0,
       "false_external_send_claims":0},
     "used_protected_gold_for_tuning":False,
     "evaluation_provenance":{
       "source_role":"disjoint_validation",
       "predictions_sealed_before_gold":True,
       "same_frozen_product_sha":True,
       "all_counted_answers_integrity_checked":True,
       "suite_frozen_before_candidate_run":True,
       "suite_disjoint_from_candidate_tuning":True,
       "gold_seen_during_candidate_selection":False,
       "cases_reused_for_candidate_tuning":False,
       "contains_invalid_answer_counted_correct":False}}
 def prepared(self,**diff):
  obj=copy.deepcopy(self.receipt);obj.update(diff)
  return obj
 def test_paired_actual_answers_win_despite_one_loss(self):
  r=gate.assess_receipt(self.receipt)
  self.assertEqual((r["wins"],r["losses"]),(3,1))
  self.assertEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")
  self.assertFalse(r["automatic_release"])
  self.assertEqual(set(r["by_type"]),{"temporal","multi_hop","single_hop"})
 def test_ordinary_losses_never_absolute_veto(self):
  obj=self.prepared()
  obj["cases"][2]["candidate_correct"]=False
  obj["cases"][2]["candidate_failure_stage"]="reasoning_error"
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertGreater(r["utility"],0)
  self.assertGreater(r["losses"],0)
  self.assertEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")
 def test_neg_accuracy_with_cost_saving_is_not_destroyed(self):
  obj=self.prepared()
  for r in obj["cases"]:
   r["candidate_correct"]=r["baseline_correct"]
   r["candidate_cost_cny"]=0.004
  obj["cases"][1]["candidate_correct"]=False
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertLess(r["net_final_correct"],0)
  self.assertGreater(r["cost_saved_fraction"],0.5)
  self.assertEqual(r["verdict"],"CONDITIONAL_PARETO_RESCUE")
 def test_p0_blocks_even_if_global_correctness_grows(self):
  obj=self.prepared();obj["observed_p0"]["cross_owner_exposures"]=1
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"HOLD_MATERIAL_P0_REPAIR_NEW_SHA")
 def test_no_true_runtime_route_is_hard_block(self):
  obj=self.prepared(candidate_mechanism_trigger_count=0)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"HOLD_NO_TRUE_ACTIVE_PRODUCT_PATH")
 def test_full_history_retrieval_requires_product_reachability(self):
  obj=self.prepared(research_retrieval_scope="full_history")
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"HOLD_NO_TRUE_ACTIVE_PRODUCT_PATH")
  self.assertTrue(r["historical_reachability_required"])
  self.assertFalse(r["historical_reachability_proven"])
 def test_full_history_retrieval_passes_after_reachability_proof(self):
  obj=self.prepared(research_retrieval_scope="full_history")
  obj["product_path"]["historical_reachability_checked"]=True
  obj["product_path"]["research_candidate_pool_reproduced"]=True
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")
  self.assertTrue(r["historical_reachability_proven"])
 def test_old_dev_or_posthoc_cannot_claim_pilot_even_with_high_gain(self):
  obj=self.prepared();obj["evaluation_provenance"]["source_role"]="development"
  obj["evaluation_provenance"]["cases_reused_for_candidate_tuning"]=True
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
  self.assertGreater(r["net_final_correct"],0)
  self.assertFalse(r["pilot_provenance_verified"])
 def test_missing_eval_lineage_does_not_destroy_candidate(self):
  obj=self.prepared();obj.pop("evaluation_provenance")
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
  self.assertFalse(r["pilot_provenance_verified"])
 def test_truncated_answers_cannot_be_marked_verified(self):
  obj=self.prepared()
  obj["evaluation_provenance"]["contains_invalid_answer_counted_correct"]=True
  self.assertEqual(gate.assess_receipt(obj)["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
 def test_false_quality_checkbox_cannot_launder_truncated_raw_answer(self):
  obj=self.prepared()
  path=self.d/"paired_answers.json"
  raw=json.loads(path.read_text("utf8"))
  item=next(x for x in raw["predictions"]
            if x["arm"]=="G27" and x["id"]==obj["cases"][0]["id"])
  item["response"]='A source note says "If responses outstanding by **June 1'
  item["finish_reason"]="length"
  path.write_text(json.dumps(raw)+"\n","utf8")
  obj["paired_evidence"]["answers_sha256"]=digest(path)
  j=self.d/"paired_judgments.json"
  jr=json.loads(j.read_text("utf8"));jr["answer_sha256"]=digest(path)
  j.write_text(json.dumps(jr)+"\n","utf8")
  obj["paired_evidence"]["judgments_sha256"]=digest(j)
  r=gate.assess_receipt(obj)
  self.assertTrue(r["raw_paired_evidence_verified"])
  self.assertFalse(r["raw_output_integrity"]["verified"])
  self.assertIn(obj["cases"][0]["id"],r["invalidated_candidate_case_ids"])
  self.assertEqual(r["candidate_correct"],sum(x["candidate_correct"] for x in obj["cases"])-1)
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
 def test_missing_finish_reason_never_claims_valid_complete_response(self):
  obj=self.prepared()
  path=self.d/"paired_answers.json"
  raw=json.loads(path.read_text("utf8"))
  del raw["predictions"][0]["finish_reason"]
  path.write_text(json.dumps(raw)+"\n","utf8")
  obj["paired_evidence"]["answers_sha256"]=digest(path)
  j=self.d/"paired_judgments.json"
  jr=json.loads(j.read_text("utf8"));jr["answer_sha256"]=digest(path)
  j.write_text(json.dumps(jr)+"\n","utf8")
  obj["paired_evidence"]["judgments_sha256"]=digest(j)
  r=gate.assess_receipt(obj)
  self.assertFalse(r["raw_output_integrity"]["verified"])
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
 def test_retrieval_proxy_not_final_answer(self):
  obj=self.prepared()
  del obj["cases"][0]["baseline_correct"]
  with self.assertRaisesRegex(ValueError,"final_answer_pair"):
   gate.assess_receipt(obj)
 def test_no_model_final_answers_blocks(self):
  obj=self.prepared()
  obj["product_path"]["real_final_answers"]=False
  self.assertEqual(gate.assess_receipt(obj)["verdict"],"HOLD_NO_TRUE_ACTIVE_PRODUCT_PATH")
 def test_no_gold_leakage(self):
  with self.assertRaisesRegex(ValueError,"protected_gold"):
   gate.assess_receipt(self.prepared(used_protected_gold_for_tuning=True))
 def test_same_source_data_sha_drift_blocks(self):
  (self.d/"candidate_RC/core.py").write_text("tampered",encoding="utf8")
  with self.assertRaisesRegex(ValueError,"product_code_sha_drift"):
   gate.assess_receipt(self.receipt)
 def test_duplicate_case_fails(self):
  obj=self.prepared();obj["cases"][1]["id"]=obj["cases"][0]["id"]
  with self.assertRaisesRegex(ValueError,"duplicate"):
   gate.assess_receipt(obj)
 def test_invalid_p0_count_fails(self):
  obj=self.prepared();obj["observed_p0"]["no_save_violations"]=-1
  with self.assertRaisesRegex(ValueError,"material_p0_counts"):
   gate.assess_receipt(obj)
 def test_no_raw_answer_judge_bytes_never_auto_pilot(self):
  obj=self.prepared()
  obj.pop("paired_evidence")
  r=gate.assess_receipt(obj)
  self.assertFalse(r["raw_paired_evidence_verified"])
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
 def test_raw_judge_tamper_prevents_pilot(self):
  obj=self.prepared()
  f=self.d/"paired_judgments.json"
  f.write_text(f.read_text("utf8")+" ","utf8")
  r=gate.assess_receipt(obj)
  self.assertFalse(r["raw_paired_evidence_verified"])
  self.assertNotEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")
 def test_fake_changed_correctness_does_not_match_source_judge(self):
  obj=self.prepared()
  obj["cases"][0]["candidate_correct"]=False
  r=gate.assess_receipt(obj)
  self.assertFalse(r["raw_paired_evidence_verified"])
  self.assertNotEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")
 def test_four_targeted_pairs_keep_research_but_do_not_pilot(self):
  obj=self.prepared(scope_type="targeted",cases=self.receipt["cases"][:4])
  obj["cases"][0]["baseline_correct"]=False
  obj["cases"][0]["candidate_correct"]=True
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
  self.assertFalse(r["fresh_pair_count_sufficient"])
 def test_200_broad_can_support_overall_capability_claim(self):
  obj=self.prepared(scope_type="broad")
  obj["cases"]=[dict(self.receipt["cases"][i%12],id=f"public-{i:03d}") for i in range(200)]
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["n"],200)
  self.assertGreater(r["wins"],r["losses"])
  self.assertTrue(r["overall_capability_claim_eligible"])

 def test_broad_12_positive_is_not_enough_for_pilot(self):
  obj=self.prepared(scope_type="broad")
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
  self.assertEqual(r["min_fresh_pairs_for_pilot"],24)

 def test_legacy_scope_is_conservatively_treated_as_broad(self):
  obj=self.prepared(scope_type="legacy_scope_limited")
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["scope_type"],"broad")
  self.assertTrue(r["scope_type_inferred_from_legacy"])
  self.assertEqual(r["min_fresh_pairs_for_pilot"],24)
  self.assertNotEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")

 def test_cost_state_or_latency_cannot_replace_final_answer_gain(self):
  obj=self.prepared()
  for row in obj["cases"]:
   row["candidate_correct"]=row["baseline_correct"]
   row["candidate_cost_cny"]=0.001
   row["candidate_latency_ms"]=20
   row["candidate_legitimate_state_correct"]=True
   row["baseline_legitimate_state_correct"]=False
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["net_final_correct"],0)
  self.assertFalse(r["final_answer_gate_pass"])
  self.assertEqual(r["verdict"],"CONDITIONAL_PARETO_RESCUE")

 def test_undiagnosed_ordinary_loss_blocks_pilot_not_research(self):
  obj=self.prepared()
  for row in obj["cases"]:
   row.pop("candidate_failure_stage",None)
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertGreater(r["net_final_correct"],0)
  self.assertFalse(r["loss_diagnostics_complete"])
  self.assertEqual(r["verdict"],"PARETO_TRIAL_KEEP_COLLECT_EVIDENCE")
  self.assertEqual(r["next_research_action"],
                   "DIAGNOSE_H_R_P_W_A_BEFORE_MORE_TUNING")

 def test_verified_delivery_trace_overrides_legacy_failure_label(self):
  obj=self.prepared()
  row=obj["cases"][1]
  row["candidate_correct"]=False
  row["candidate_failure_stage"]="reasoning_error"
  row["candidate_delivery_trace"]={
    "basis":"human_verified",
    "history_sufficient":True,
    "retrieval_sufficient":True,
    "prompt_sufficient":False,
  }
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertGreaterEqual(r["failure_stage_counts"]["evidence_incomplete"],1)

 def test_answer_contract_family_hard_blocks_without_diagnostic(self):
  obj=self.prepared(candidate_family="answer_contract_executor")
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"HOLD_ANSWER_CONTRACT_DIAGNOSTIC_REQUIRED")
  self.assertTrue(r["hard_gate"])
  self.assertFalse(r["answer_contract_prerequisite"]["passed"])

 def test_answer_contract_family_can_pilot_after_diagnostic(self):
  obj=self.prepared(candidate_family="answer_contract_executor")
  obj["answer_contract_diagnostic"]={
    "case_ids_frozen_before_run":True,
    "same_question_model_prompt_mode":True,
    "manual_evidence_gold_free":True,
    "actual_model_messages_recorded":True,
    "actual_model_input_sha_bound":True,
    "manual_full_evidence_intervention_completed":True,
    "executor_consumption_gain_observed":True,
    "used_fresh_claim_credit":False,
    "n":16,
  }
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertTrue(r["answer_contract_prerequisite"]["passed"])
  self.assertEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")

 def test_overall_claim_needs_independent_or_deterministic_judging(self):
  obj=self.prepared(scope_type="broad",semantic_judge_independent=False)
  obj["cases"]=[dict(self.receipt["cases"][i%12],id=f"public-{i:03d}") for i in range(100)]
  self.make_bundle(obj)
  r=gate.assess_receipt(obj)
  self.assertEqual(r["verdict"],"PILOT_REVIEW_READY_NO_AUTO_RELEASE")
  self.assertFalse(r["overall_capability_claim_eligible"])

class IntegrationMachineTests(ProductPortfolioMachineGateTests):
 def setUp(self):
  super().setUp()
  self.conn=sqlite3.connect(":memory:",isolation_level=None)
  self.addCleanup(self.conn.close)
  self.conn.row_factory=sqlite3.Row
  self.conn.execute(SCHEMA)
  self.art=self.d/"research_source.txt"
  self.art.write_text("frozen original candidate",encoding="utf8")
  for ident,track,artifact in (
      ("D2-X901","D2",self.art),
      ("M1-X901","M1",self.d/"m1.txt"),
      ("M2-X901","M2",self.d/"m2.txt"),
      ("A1-X901","A1",self.d/"a1.txt")):
   if ident!="D2-X901":
    artifact.write_text(
       ("- Outcome: PASS_PRODUCT_SOURCE_P0_CLOSED\n" if track=="A1" else "M1 / M2 actual result\n")+
       "NEW_RC_MANIFEST_SHA256="+self.candidate_sha+"\n","utf8")
   self.conn.execute("""INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ident,"AUDITOR" if track=="A1" else "MAINLINE",track,20,
       "actual task","criteria","source","DONE",None,str(artifact),None,10))
  out=loop.register_task(self.conn,"D2-X901","measured paired final gain",risk="read_only")
  self.assertEqual(out["candidate"],"auto-d2-x901")
  self.conn.execute("UPDATE product_candidates SET integration_task='M1-X901',answer_task='M2-X901',audit_task='A1-X901' WHERE id='auto-d2-x901'")
  self.file=self.d/"receipt.json"
  self.save()
 def save(self):
  self.file.write_text(json.dumps(self.receipt,ensure_ascii=False,indent=2)+"\n","utf8")
 def target(self):
  return self.conn.execute("SELECT * FROM product_candidates WHERE id='auto-d2-x901'").fetchone()
 def test_machine_portfolio_receipt_required_after_tasks_done(self):
  self.assertEqual(loop.stage(self.conn,self.target()),"WAIT_MACHINE_PORTFOLIO_RECEIPT")
  with self.assertRaises(ValueError):loop.decide(self.conn,"auto-d2-x901","PILOT_REVIEW","without machine evidence")
 def test_machine_bound_pilot_review_only_not_release(self):
  machine.record(self.conn,"auto-d2-x901",self.file)
  self.assertEqual(loop.stage(self.conn,self.target()),"MACHINE_PARETO_PILOT_REVIEW_READY")
  obj=loop.decide(self.conn,"auto-d2-x901","PILOT_REVIEW","same-input evidence, same SHA, independent PASS")
  self.assertFalse(obj["default_on_changed"])
  self.assertFalse(obj["automatic_release"])
 def test_changed_m2_sha_blocks(self):
  machine.record(self.conn,"auto-d2-x901",self.file)
  (self.d/"m2.txt").write_text("different product version\n","utf8")
  self.assertEqual(loop.stage(self.conn,self.target()),"WAIT_EXACT_SHA_M1_M2_A1_EVIDENCE")
 def test_a1_security_label_overrides_receipt(self):
  machine.record(self.conn,"auto-d2-x901",self.file)
  (self.d/"a1.txt").write_text(
    "Outcome: NONPASS_MATERIAL_READ_AUTHORITY_P0\nNEW_RC_MANIFEST_SHA256="+self.candidate_sha,"utf8")
  self.assertTrue(loop.stage(self.conn,self.target()).startswith("HOLD_P0"))
 def test_receipt_bytes_change_cannot_keep_pilot(self):
  machine.record(self.conn,"auto-d2-x901",self.file)
  self.file.write_text(self.file.read_text("utf8")+" ","utf8")
  self.assertTrue(loop.stage(self.conn,self.target()).startswith("HOLD_MACHINE"))
 def test_existing_default_off_exploration_is_not_stopped(self):
  obj=loop.decide(self.conn,"auto-d2-x901","TRIAL_OFF","same root rc remains opt-in for further tests")
  self.assertFalse(obj["default_on_changed"])
 def test_original_historical_rejection_is_kept(self):
  self.conn.execute("""INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      ("D2-X902","MAINLINE","D2",40,"retrieval rerank experiment",
       "measured","public","DONE",None,str(self.art),None,10))
  self.conn.execute("""INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      ("D2-X903","MAINLINE","D2",40,"retrieval source experiment",
       "measured","public","DONE",None,str(self.art),None,10))
  catalog=self.d/"historical.json"
  catalog.write_text(json.dumps([
   {"id":"D2-X902","title":"BM25 retrieval cost optimization",
    "summary":"Outcome: FAIL strict zero-loss gate. Measured saved 41% token cost; 12 valid examples 8/12 -> 9/12, gain2/loss1",
    "signals":{"reject":True,"gain":True,"cost":True,"p0":False}},
   {"id":"D2-X903","title":"retrieval no_save abuse",
    "summary":"Outcome: NONPASS_MATERIAL_PRIVACY_P0 but 40% saved tokens",
    "signals":{"reject":True,"gain":True,"cost":True,"p0":True}}],
   ensure_ascii=False,indent=2),"utf8")
  with patch.object(machine,"CATALOG",catalog):
   result=machine.rescue(self.conn,limit_new=4)
  self.assertEqual(result["total"],2)
  self.assertEqual(result["new_registered"],1)
  self.assertIsNotNone(self.conn.execute("SELECT 1 FROM product_candidates WHERE source_task='D2-X902'").fetchone())
  self.assertIsNone(self.conn.execute("SELECT 1 FROM product_candidates WHERE source_task='D2-X903'").fetchone())
  self.assertEqual(self.conn.execute("SELECT original_negative_retained FROM product_historical_rescue WHERE source_task='D2-X902'").fetchone()[0],1)
  self.assertFalse(result["default_on"])
if __name__=="__main__":
 unittest.main()
