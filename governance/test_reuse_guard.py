# -*- coding: utf-8 -*-
"""Build-vs-reuse guard regressions. Synthetic/temp only; no APIs or private data."""
import json
import tempfile
import unittest
from pathlib import Path

from control import Governance,GovernanceError

HERE=Path(__file__).parent

class ReuseGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance"
        gov.mkdir()
        for name in ("policy.json","RESEARCH_BACKLOG.json","REUSE_CATALOG.json"):
            (gov/name).write_bytes((HERE/name).read_bytes())
        # Keep production lifecycle immutable, but give the isolated fixture one
        # current-phase vetted task so backlog-claim tests do not depend on whether
        # the real project has already closed R24.
        backlog_path=gov/"RESEARCH_BACKLOG.json"
        backlog=json.loads(backlog_path.read_text(encoding="utf-8"))
        fixture_row=next(r for r in backlog["candidates"] if r.get("id")=="R24")
        fixture_row["status"]="active"
        fixture_row.pop("completion_submission",None)
        fixture_row.pop("completion_level",None)
        fixture_row.pop("completion_note",None)
        backlog_path.write_text(json.dumps(backlog,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        policy=json.loads((gov/"policy.json").read_text(encoding="utf-8"))
        self.effective=float(policy["reuse_guard"]["effective_after_epoch"])
        self.v2_effective=float(policy["reuse_guard"].get("v2_effective_after_epoch",self.effective))
        self.now=[max(self.effective,self.v2_effective)+10]
        self.g=Governance(self.root,clock=lambda:self.now[0])

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    @staticmethod
    def plan(*components,mode="reuse",gap=None,new_dependencies=None):
        return {
            "mode":mode,
            "components":list(components),
            "gap":gap or "Reuse the listed mature mechanism and test only the XiaoYu-specific policy gap that it does not provide.",
            "no_new_infrastructure":True,
            "new_dependencies":[] if new_dependencies is None else new_dependencies,
            "prior_work":{
                "reviewed":[],
                "novelty":"This synthetic test exercises a materially distinct XiaoYu policy boundary and does not repeat an existing submitted experiment.",
                "replication_of":None,
            },
        }

    def join(self,**kwargs):
        base=dict(
            agent_id="reuse_worker_01",role="research_engineer",
            family="semantic.policy.test",capability="memory_evidence",
            hypothesis="Test a XiaoYu-specific authority rule on fixed synthetic evidence without adding infrastructure.",
            lane="main_bottleneck",lineage="semantic.policy",
            reuse_plan=self.plan("xiaoyu_existing_core",mode="custom_policy"),
        )
        base.update(kwargs)
        return self.g.join(**base)

    def manifest(self,lease):
        row=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()
        w=Path(lease["workspace"])
        (w/"evidence.txt").write_text("synthetic reuse-guard evidence",encoding="utf-8")
        data={
            "hypothesis":row["hypothesis"],
            "falsifier":"The fixed counterexample still mutates state incorrectly.",
            "baseline":"Existing XiaoYu policy behavior",
            "metric":"exact synthetic pass fraction",
            "delta":None,
            "method":"Offline deterministic synthetic probe",
            "limitations":"Synthetic only; no private identity data",
            "evidence_label":"EVIDENCE_ONLY",
            "artifacts":["evidence.txt"],
            "reuse_compliance":{
                "components_considered":json.loads(row["reuse_plan_json"])["components"],
                "new_dependencies":[],
                "new_infrastructure":False,
                "deviation":"none",
            },
        }
        (w/"result.json").write_text(json.dumps(data),encoding="utf-8")

    def test_self_directed_without_plan_rejected(self):
        with self.assertRaisesRegex(GovernanceError,"Reuse gate requires"):
            self.g.join("reuse_worker_01","research_engineer","semantic.policy.test",
                        "memory_evidence",
                        "Test a XiaoYu-specific authority rule on fixed synthetic evidence without adding infrastructure.",
                        "main_bottleneck",lineage="semantic.policy")

    def test_unknown_component_rejected(self):
        with self.assertRaisesRegex(GovernanceError,"Unknown reuse component"):
            self.join(reuse_plan=self.plan("brand_new_vector_db"))

    def test_new_dependency_requires_lead_catalog_review(self):
        with self.assertRaisesRegex(GovernanceError,"Lead catalog review"):
            self.join(reuse_plan=self.plan("xiaoyu_existing_core",
                                           mode="custom_policy",
                                           new_dependencies=["new-memory-framework"]))

    def test_handwritten_posting_requires_fts5(self):
        with self.assertRaisesRegex(GovernanceError,"SQLite FTS5"):
            self.join(
                family="retrieval.custom.index",
                lineage="retrieval.custom.index",
                capability="memory_retrieval",
                hypothesis="Implement a handwritten inverted index posting layer for long-tail evidence retrieval.",
                reuse_plan=self.plan("lancedb_cognee_local_0390",mode="extend"),
            )

    def test_custom_vector_database_blocked_even_under_renamed_family(self):
        with self.assertRaisesRegex(GovernanceError,"Custom graph/vector/ANN"):
            self.join(
                family="clever.new.route",
                lineage="clever.new.route",
                capability="memory_retrieval",
                hypothesis="Build a custom vector database to improve semantic recall on paraphrases.",
                reuse_plan=self.plan("lancedb_cognee_local_0390",mode="reuse"),
            )

    def test_zip_patch_family_is_legacy_only(self):
        with self.assertRaisesRegex(GovernanceError,"legacy migration"):
            self.join(
                family="archive.zip.morepatches",
                lineage="identity.archive.parser",
                capability="identity_continuity",
                hypothesis="Patch another ZIP parser ambiguity in the future portable identity format.",
                reuse_plan=self.plan("sqlite_backup",mode="extend"),
            )

    def test_backlog_vetted_plan_claims_and_persists_decision(self):
        rows=json.loads((self.root/"governance"/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))["candidates"]
        r=next(x for x in rows if x["id"]=="R24")
        lease=self.g.join(
            "reuse_worker_01","research_engineer",r["family"],r["capability"],
            r["hypothesis"],r["lane"],lineage=r["lineage"],
            backlog_id="R24",reuse_plan=r["reuse_plan"])
        self.assertEqual(lease["reuse_guard"]["status"],"PASS")
        self.assertEqual(lease["reuse_guard"]["source"],"backlog_vetted")
        self.assertIn("afterdeletebench_benchmark",lease["reuse_guard"]["plan"]["components"])
        decision=Path(lease["workspace"])/"REUSE_DECISION.json"
        self.assertTrue(decision.is_file())
        row=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()
        self.assertEqual(row["backlog_id"],"R24")
        self.assertEqual(row["reuse_guard_version"],2)
        self.assertTrue(row["reuse_decision_sha"])

    def test_retired_backlog_id_is_rejected_even_if_called_directly(self):
        rows=json.loads((self.root/"governance"/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))["candidates"]
        r=next(x for x in rows if x["id"]=="R04")
        with self.assertRaisesRegex(GovernanceError,"Backlog task is not active"):
            self.g.reuse_check(
                "research_engineer",r["family"],r["capability"],r["hypothesis"],r["lane"],
                lineage=r["lineage"],reuse_plan=r["reuse_plan"],backlog_id="R04")

    def test_backlog_plan_cannot_be_replaced_by_caller(self):
        rows=json.loads((self.root/"governance"/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))["candidates"]
        r=next(x for x in rows if x["id"]=="R24")
        with self.assertRaisesRegex(GovernanceError,"differs from Lead-vetted"):
            self.g.join(
                "reuse_worker_01","research_engineer",r["family"],r["capability"],
                r["hypothesis"],r["lane"],lineage=r["lineage"],
                backlog_id="R24",
                reuse_plan=self.plan("xiaoyu_existing_core",mode="custom_policy"))

    def test_guarded_submission_requires_reuse_compliance(self):
        lease=self.join(agent_id="reuse_worker_missing")
        row=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()
        w=Path(lease["workspace"])
        (w/"evidence.txt").write_text("synthetic",encoding="utf-8")
        data={
            "hypothesis":row["hypothesis"],
            "falsifier":"The fixed counterexample still fails.",
            "baseline":"Existing XiaoYu behavior",
            "metric":"exact synthetic result",
            "delta":None,
            "method":"Offline synthetic check",
            "limitations":"Synthetic only",
            "evidence_label":"EVIDENCE_ONLY",
            "artifacts":["evidence.txt"],
        }
        (w/"result.json").write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaisesRegex(GovernanceError,"reuse_compliance"):
            self.g.submit(lease["lease_id"],"reuse_worker_missing","result.json")

    def test_guarded_submission_with_exact_compliance_passes(self):
        lease=self.join(agent_id="reuse_worker_submit")
        self.manifest(lease)
        out=self.g.submit(lease["lease_id"],"reuse_worker_submit","result.json")
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")

    def test_reuse_decision_tamper_blocks_submission(self):
        lease=self.join()
        self.manifest(lease)
        p=Path(lease["workspace"])/"REUSE_DECISION.json"
        obj=json.loads(p.read_text(encoding="utf-8"))
        obj["decision"]["plan"]["components"]=["brand_new_vector_db"]
        p.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaisesRegex(GovernanceError,"Reuse decision missing or altered"):
            self.g.submit(lease["lease_id"],"reuse_worker_01","result.json")

    def test_exact_pre_guard_recovery_is_grandfathered_but_scope_change_is_not(self):
        # Claim before enforcement, then let the lease become stale after enforcement.
        self.now[0]=self.effective-100
        lease=self.g.join(
            "reuse_worker_01","research_engineer","old.safe.task","memory_retrieval",
            "A pre-guard synthetic retrieval task should preserve exact recovery semantics.",
            "main_bottleneck",lineage="old.safe.task")
        path=self.root/"governance"/"RESEARCH_BACKLOG.json"
        backlog=json.loads(path.read_text(encoding="utf-8"))
        for row in backlog.get("candidates",[]):
            row["status"]="hold"
        path.write_text(json.dumps(backlog),encoding="utf-8")
        self.now[0]=self.effective+6000
        out=self.g.continue_agent("reuse_worker_01")
        self.assertEqual(out["next_step"],"RECOVER_FROM_PREVIOUS_WORKSPACE")
        newrow=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(out["next_lease_id"],)).fetchone()
        plan=json.loads(newrow["reuse_plan_json"])
        self.assertEqual(plan["mode"],"grandfathered_recovery")
        with self.assertRaises(GovernanceError):
            self.g.reuse_check(
                "research_engineer","changed.scope","memory_retrieval",
                "A different hypothesis attempts to ride an old recovery lease.",
                "main_bottleneck",lineage="changed.scope",recovery_of=lease["lease_id"])

    def test_post_epoch_unguarded_gap_is_detected_blocked_and_retrofittable(self):
        # Simulate a lease created by an old control.py process during deployment.
        self.now[0]=self.effective-100
        lease=self.g.join(
            "reuse_gap_worker","research_engineer","semantic.gap.sim","memory_retrieval",
            "Use the existing governed semantic classifier to test a bounded routing policy.",
            "main_bottleneck",lineage="semantic.gap.sim")
        w=Path(lease["workspace"])
        (w/"REUSE_DECISION.json").unlink()
        with self.g.tx():
            self.g.db.execute(
                "UPDATE leases SET claimed_at=?,reuse_decision_sha='',reuse_plan_json='{}',"
                "reuse_guard_version=0,reuse_catalog_sha='' WHERE lease_id=?",
                (self.effective+1,lease["lease_id"]))
        self.now[0]=self.effective+10
        coverage=self.g.reuse_coverage()
        self.assertIn(lease["lease_id"],coverage["active_unguarded"])
        self.assertFalse(coverage["enforcement_clean"])
        resume=self.g.continue_agent("reuse_gap_worker")
        self.assertEqual(resume["next_step"],"REUSE_RETROFIT_REQUIRED")
        self.assertFalse(resume["continue_research"])
        with self.assertRaisesRegex(GovernanceError,"heartbeat refused"):
            self.g.heartbeat(lease["lease_id"],"reuse_gap_worker")

        (w/"evidence.txt").write_text("synthetic",encoding="utf-8")
        data={
            "hypothesis":"Use the existing governed semantic classifier to test a bounded routing policy.",
            "falsifier":"The bounded routing policy fails the fixed synthetic cases.",
            "baseline":"Existing single-label semantic classifier",
            "metric":"exact synthetic result",
            "delta":None,
            "method":"Offline and governed synthetic comparison",
            "limitations":"Synthetic only",
            "evidence_label":"EVIDENCE_ONLY",
            "artifacts":["evidence.txt"],
        }
        (w/"result.json").write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaisesRegex(GovernanceError,"Lead retrofit required"):
            self.g.submit(lease["lease_id"],"reuse_gap_worker","result.json")

        plan=self.plan(
            "deepseek_semantic_projector","research_api_gateway",mode="extend",
            gap="Reuse the existing governed semantic classifier; only test bounded routing policy behavior and add no storage, vector, graph, or model infrastructure.")
        fixed=self.g.retrofit_reuse(
            lease["lease_id"],plan,
            "Repair a synthetic post-epoch lease created by an intentionally simulated old control process.")
        self.assertEqual(fixed["status"],"RETROFIT_PASS")
        self.assertEqual(self.g.reuse_coverage()["active_unguarded"],[])

        row=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()
        data["reuse_compliance"]={
            "components_considered":json.loads(row["reuse_plan_json"])["components"],
            "new_dependencies":[],
            "new_infrastructure":False,
            "deviation":"none",
        }
        (w/"result.json").write_text(json.dumps(data),encoding="utf-8")
        out=self.g.submit(lease["lease_id"],"reuse_gap_worker","result.json")
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")

    def test_post_epoch_unguarded_pending_e1_cannot_be_accepted(self):
        self.g.policy["continuation"]["enabled"]=False
        self.now[0]=self.effective-100
        lease=self.g.join(
            "unguarded_author","research_engineer","semantic.old.process","memory_evidence",
            "A synthetic evidence-policy improvement beats the fixed baseline without new infrastructure.",
            "main_bottleneck",lineage="semantic.old.process")
        w=Path(lease["workspace"])
        (w/"evidence.txt").write_text("synthetic score +1",encoding="utf-8")
        manifest={
            "hypothesis":"A synthetic evidence-policy improvement beats the fixed baseline without new infrastructure.",
            "falsifier":"The fixed holdout does not improve over baseline.",
            "baseline":"Existing evidence policy",
            "metric":"fixed held-out exact accuracy",
            "delta":0.1,
            "method":"Deterministic synthetic comparison",
            "limitations":"Synthetic only",
            "evidence_label":"LEAD_READY",
            "artifacts":["evidence.txt"],
        }
        (w/"result.json").write_text(json.dumps(manifest),encoding="utf-8")
        sub=self.g.submit(lease["lease_id"],"unguarded_author","result.json")
        with self.g.tx():
            self.g.db.execute(
                "UPDATE leases SET claimed_at=?,reuse_guard_version=0 WHERE lease_id=?",
                (self.effective+1,lease["lease_id"]))
        self.now[0]=self.effective+10
        self.g.join(
            "reuse_auditor_02","auditor","audit.unguarded","memory_evidence",
            "Independently audit a synthetic post-epoch reuse-guard boundary.",
            "evaluation_data")
        with self.assertRaisesRegex(GovernanceError,"cannot be ACCEPT_E1"):
            self.g.review(
                sub["submission_id"],"reuse_auditor_02","ACCEPT_E1",
                "Synthetic evidence is otherwise reproducible but the reuse guard is mandatory.")

    def test_deprecated_generic_vector_alias_is_blocked(self):
        with self.assertRaisesRegex(GovernanceError,"lifecycle blocks"):
            self.join(
                family="retrieval.alias.loophole",
                lineage="retrieval.alias.loophole",
                capability="memory_retrieval",
                hypothesis="Reuse a generic existing vector backend alias for semantic retrieval without naming the implementation.",
                reuse_plan=self.plan("existing_vector_backend",mode="reuse"),
            )

    def test_prior_work_exact_submitted_hypothesis_requires_replication_or_falsification(self):
        self.g.policy["continuation"]["enabled"]=False
        first=self.join(agent_id="prior_worker_01")
        self.manifest(first)
        self.g.submit(first["lease_id"],"prior_worker_01","result.json")
        reviewed=self.plan("xiaoyu_existing_core",mode="custom_policy")
        reviewed["prior_work"]["reviewed"]=[first["lease_id"]]
        reviewed["prior_work"]["novelty"]=(
            "This request intentionally repeats the exact prior hypothesis, so without an explicit "
            "replication or falsification purpose it must not consume another research lease.")
        with self.assertRaisesRegex(GovernanceError,"Exact prior submitted hypothesis"):
            self.join(agent_id="prior_worker_02",reuse_plan=reviewed)

        falsify=self.plan("xiaoyu_existing_core",mode="falsification")
        falsify["prior_work"]["reviewed"]=[first["lease_id"]]
        falsify["prior_work"]["novelty"]=(
            "Independent falsification repeats the same hypothesis deliberately using a fresh "
            "negative-control design, so duplication is scientifically intentional and explicit.")
        out=self.join(agent_id="prior_worker_03",reuse_plan=falsify)
        self.assertEqual(out["reuse_guard"]["status"],"PASS")

    def test_prior_work_same_lineage_requires_review_even_when_wording_changes(self):
        self.g.policy["continuation"]["enabled"]=False
        first=self.join(
            agent_id="lineage_worker_01",
            family="semantic.lineage.first",
            lineage="semantic.shared.lineage",
            hypothesis="A deterministic source authority policy should quarantine unsupported assistant guesses before current-state mutation.")
        self.g.release(first["lease_id"],"lineage_worker_01")
        plan=self.plan("xiaoyu_existing_core",mode="custom_policy")
        with self.assertRaisesRegex(GovernanceError,"Prior-work review missing"):
            self.join(
                agent_id="lineage_worker_02",
                family="semantic.lineage.second",
                lineage="semantic.shared.lineage",
                hypothesis="Reassigning ambiguous evidence after later corrections must remain replay-safe across restore and unrelated state transitions.",
                reuse_plan=plan)

    def test_prior_work_similar_lease_must_be_reviewed(self):
        self.g.policy["continuation"]["enabled"]=False
        first=self.join(agent_id="near_worker_01")
        self.g.release(first["lease_id"],"near_worker_01")
        plan=self.plan("xiaoyu_existing_core",mode="custom_policy")
        with self.assertRaisesRegex(GovernanceError,"Prior-work review missing"):
            self.join(agent_id="near_worker_02",reuse_plan=plan)

    def test_reuse_doctor_v2_catalog_is_healthy_in_clean_fixture(self):
        report=self.g.reuse_doctor()
        self.assertEqual(report["catalog_version"],2)
        self.assertEqual(report["error_count"],0)
        self.assertTrue(report["healthy"])
        self.assertFalse(any(x["type"]=="backlog_blocked_component" for x in report["issues"]))

    def test_reuse_doctor_rejects_active_candidate_outside_current_phase(self):
        path=self.root/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        row=next(x for x in data["candidates"] if x["id"]=="R31")
        row["status"]="active"
        row.pop("completion_submission",None)
        row.pop("completion_level",None)
        row.pop("completion_note",None)
        path.write_text(json.dumps(data),encoding="utf-8")
        report=self.g.reuse_doctor()
        self.assertFalse(report["healthy"])
        self.assertTrue(any(x["type"]=="active_backlog_outside_phase"
                            and x["backlog_id"]=="R31"
                            for x in report["issues"]))

    def test_auditor_is_exempt_from_build_gate(self):
        out=self.g.join(
            "reuse_auditor_01","auditor","audit.reuse.guard","memory_evidence",
            "Independently verify a submitted reuse decision and its evidence.",
            "evaluation_data")
        self.assertEqual(out["reuse_guard"]["status"],"NOT_REQUIRED")

if __name__=="__main__":
    unittest.main(verbosity=2)
