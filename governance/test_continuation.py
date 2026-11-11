# -*- coding: utf-8 -*-
"""Synthetic-only regression of same-turn handoff, no ChatGPT background execution."""
import json
import tempfile
import unittest
from pathlib import Path
from control import Governance, GovernanceError

HERE=Path(__file__).parent

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.home=Path(self.temp.name)
        gov=self.home/"governance"
        gov.mkdir()
        for name in ("policy.json","RESEARCH_BACKLOG.json"):
            (gov/name).write_bytes((HERE/name).read_bytes())
        # Freeze this suite at a synthetic pre-finalize P1 closeout state.
        # The live project may move R45 active -> done; these tests exercise both
        # in-flight and completion transitions explicitly and must not inherit
        # production lifecycle changes by accident.
        backlog_path=gov/"RESEARCH_BACKLOG.json"
        backlog=json.loads(backlog_path.read_text(encoding="utf-8"))
        r45=next(r for r in backlog["candidates"] if r.get("id")=="R45")
        r45["status"]="active"
        for key in ("completion_submission","completion_level","completion_note"):
            r45.pop(key,None)
        phase=backlog["phase_policy"]
        phase["current_phase"]="P1"
        phase["auto_assign_plans"]=["P1"]
        phase["closeout_mode"]=True
        phase["closeout_required_backlog"]=["R45"]
        phase["p1_research_closeout_complete"]=False
        phase["closeout_reason"]="Synthetic pre-finalize R45 closeout fixture."
        backlog_path.write_text(json.dumps(backlog),encoding="utf-8")
        self.g=Governance(self.home,clock=lambda:1_000_000.0)
        self.assertTrue(self.g.policy["continuation"]["enabled"])
    def tearDown(self):
        self.g.close()
        self.temp.cleanup()
    def activate_backlog_for_fixture(self,*ids,closeout=False):
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        wanted=set(ids)
        for row in data.get("candidates",[]):
            if row.get("id") in wanted:
                row["status"]="active"
                row.pop("completion_submission",None)
                row.pop("completion_level",None)
                row.pop("completion_note",None)
        if not closeout:
            data["phase_policy"]["closeout_mode"]=False
            data["phase_policy"]["closeout_required_backlog"]=[]
        path.write_text(json.dumps(data),encoding="utf-8")
    def hold_all_backlog(self):
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("candidates",[]):
            row["status"]="hold"
        # Generic "backlog exhausted" tests are not P1-closeout tests.
        phase=data["phase_policy"]
        phase["closeout_mode"]=False
        phase["closeout_required_backlog"]=[]
        phase["p1_research_closeout_complete"]=False
        path.write_text(json.dumps(data),encoding="utf-8")
    def initial(self,agent="worker-a",role="research_engineer"):
        spec=dict(family="test.first",capability="memory_retrieval",lane="main_bottleneck",
                  hypothesis="A synthetic offline source test should detect unsupported claims.")
        if role=="auditor":
            spec.update(family="test.audit.first",capability="memory_evidence",
                        lane="evaluation_data")
        return self.g.join(agent,role,**spec)
    def submit(self,lease,agent,label="EVIDENCE_ONLY"):
        row=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()
        w=Path(lease["workspace"])
        (w/"evidence.txt").write_text("fixed synthetic evidence",encoding="utf-8")
        manifest=dict(hypothesis=row["hypothesis"],falsifier="Fails when the evidence is contradicted.",
                      baseline="Small synthetic V2 baseline",
                      metric="Exact answers on held-out artificial examples",
                      delta=(0.1 if label=="LEAD_READY" else None),
                      method="Offline single-pass synthetic validation",
                      limitations="Not a real model or real person's conversations",
                      evidence_label=label,artifacts=["evidence.txt"])
        (w/"result.json").write_text(json.dumps(manifest),encoding="utf-8")
        return self.g.submit(lease["lease_id"],agent,"result.json")
    def test_submit_claims_second_and_third_task_same_agent(self):
        # Live P1 closeout intentionally has one task. This regression needs a
        # temporary multi-task fixture to exercise same-turn chaining itself.
        self.activate_backlog_for_fixture("R35","R43","R45",closeout=False)
        first=self.initial()
        one=self.submit(first,"worker-a")
        self.assertTrue(one["continue_research"])
        self.assertEqual(one["next_step"],"WORK_IN_ASSIGNED_WORKSPACE")
        second=one["next_task"]
        self.assertEqual(second["agent_id"],"worker-a")
        self.assertEqual(second["role"],"research_engineer")
        self.assertNotEqual(second["lease_id"],first["lease_id"])
        self.assertNotEqual(second["workspace"],first["workspace"])
        self.assertEqual(self.g.verify_receipt(one["submission_id"])["integrity"],"PASS")
        self.assertEqual(self.g.status()["active_total"],1)
        two=self.submit(second,"worker-a")
        self.assertTrue(two["continue_research"])
        self.assertNotEqual(two["next_lease_id"],second["lease_id"])
        self.assertEqual(self.g.status()["active_total"],1)
    def test_next_idempotently_resumes_existing_and_keeps_role(self):
        a=self.initial()
        out=self.g.continue_agent("worker-a")
        self.assertTrue(out["resumed"])
        self.assertEqual(out["next_lease_id"],a["lease_id"])
        self.assertEqual(self.g.status()["active_total"],1)
    def test_auditor_continues_without_taking_research_slot(self):
        first=self.initial(agent="auditor-a",role="auditor")
        result=self.submit(first,"auditor-a")
        self.assertEqual(result["next_task"]["role"],"auditor")
        from continuation import AUDITOR_TASKS
        self.assertEqual(result["next_task"]["capability"],AUDITOR_TASKS[0]["capability"])
        research=self.initial(agent="worker-a")
        self.assertEqual(self.g.status()["active_by_role"],{"research_engineer":1,"auditor":1})
        self.assertNotEqual(research["lease_id"],result["next_lease_id"])
    def test_static_backlog_exhaustion_does_not_claim_project_saturation(self):
        from continuation import _specs
        # Generic backlog exhaustion is distinct from the live P1 closeout freeze.
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        data["phase_policy"]["closeout_mode"]=False
        data["phase_policy"]["closeout_required_backlog"]=[]
        data["phase_policy"]["p1_research_closeout_complete"]=False
        path.write_text(json.dumps(data),encoding="utf-8")
        for spec in _specs(self.g,"research_engineer"):
            x=self.g.join("worker-a","research_engineer",spec["family"],
                          spec["capability"],spec["hypothesis"],spec["lane"],
                          lineage=spec["lineage"])
            self.g.release(x["lease_id"],"worker-a")
        out=self.g.continue_agent("worker-a")
        self.assertEqual(out["next_step"],"SELF_DIRECTED_NEW_HYPOTHESIS")
        self.assertTrue(out["continue_research"])
        self.assertIsNone(out["next_task"])
    def test_retired_backlog_candidate_is_not_assignable(self):
        from continuation import _specs
        specs=_specs(self.g,"research_engineer")
        ids=[x.get("backlog_id") for x in specs]
        self.assertNotIn("R04",ids)
        self.assertNotIn("R14",ids)
        self.assertNotIn("R12",ids)  # retired after its late-rehydrate falsifier
        self.assertNotIn("R41",ids)  # superseded by R44/R45
        self.assertNotIn("R18",ids)
        self.assertNotIn("R29",ids)  # accepted/done
        self.assertNotIn("R31",ids)  # accepted/done
        self.assertIn("R45",ids)     # current direct erasure closeout successor

    def test_phase_policy_blocks_accidentally_active_later_phase_candidate(self):
        from continuation import _specs
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        target=next(r for r in data["candidates"] if r["id"]=="R23")
        target["status"]="active"  # simulate an accidental lifecycle edit
        target["priority"]=-100   # even highest priority must not bypass the phase gate
        self.assertEqual(data["phase_policy"]["auto_assign_plans"],["P1"])
        path.write_text(json.dumps(data),encoding="utf-8")
        ids=[x.get("backlog_id") for x in _specs(self.g,"research_engineer")]
        self.assertNotIn("R23",ids)
        self.assertNotIn("R12",ids)
        self.assertNotIn("R41",ids)
        self.assertNotIn("R21",ids)
        self.assertNotIn("R30",ids)  # superseded after independent same-slot swap falsifier
        self.assertNotIn("R34",ids)  # authenticated singleton is formal NONPASS/retired
        self.assertNotIn("R36",ids)  # clause fan-out is formal NONPASS/no-gain
        self.assertNotIn("R35",ids)  # final-per-slot projection is now ACCEPT_E1/done
        self.assertNotIn("R44",ids)  # independently NEEDS_WORK/superseded by R45
        self.assertIn("R45",ids)     # current direct P1 closeout successor
        self.assertNotIn("R31",ids)  # accepted/done

    def test_active_backlog_supersession_blocks_continue_heartbeat_and_submit(self):
        from continuation import _specs
        spec=next(x for x in _specs(self.g,"research_engineer") if x.get("backlog_id")=="R45")
        lease=self.g.join(
            "worker-superseded","research_engineer",spec["family"],spec["capability"],
            spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
            reuse_plan=spec.get("reuse_plan"),backlog_id="R45")
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        row=next(x for x in data["candidates"] if x["id"]=="R45")
        row["status"]="superseded"
        row["superseded_by"]="R46"
        path.write_text(json.dumps(data),encoding="utf-8")

        out=self.g.continue_agent("worker-superseded")
        self.assertFalse(out["continue_research"])
        self.assertEqual(out["next_step"],"BACKLOG_TASK_NO_LONGER_ACTIVE")
        with self.assertRaisesRegex(GovernanceError,"no longer active"):
            self.g.heartbeat(lease["lease_id"],"worker-superseded")
        with self.assertRaisesRegex(GovernanceError,"no longer active"):
            self.submit(lease,"worker-superseded")
        # Administrative release remains available so the successor can be claimed.
        released=self.g.release(lease["lease_id"],"worker-superseded")
        self.assertEqual(released["state"],"RELEASED")

    def test_needs_work_backlog_requeues_to_same_author_with_findings(self):
        from continuation import _specs
        spec=next(x for x in _specs(self.g,"research_engineer") if x.get("backlog_id")=="R45")
        first=self.g.join(
            "worker-remediate","research_engineer",spec["family"],spec["capability"],
            spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
            reuse_plan=spec.get("reuse_plan"),backlog_id="R45")
        submitted=self.submit(first,"worker-remediate",label="LEAD_READY")
        self.assertEqual(submitted["lead_decision"],"PENDING")

        # Register a distinct auditor and give the candidate a concrete P1 blocker.
        self.initial(agent="auditor-remediate",role="auditor")
        finding={
            "severity":"P1",
            "issue":"Synthetic same-target transition creates two active replacements.",
            "impact":"The current-state view becomes contradictory after one source batch.",
            "fix":"Fail closed on overlapping same-target mutations and add a regression.",
            "blocking":True,
            "observed":True,
            "reproduction":"Create A, then submit B and C that both supersede A in one source batch.",
            "evidence":"Synthetic adversarial artifact records two active replacements for the same target."
        }
        review=self.g.review(
            submitted["submission_id"],"auditor-remediate","NEEDS_WORK",
            "Independent synthetic rerun reproduces a blocking same-target state consistency failure.",
            [finding])
        self.assertEqual(review["decision"],"NEEDS_WORK")

        phase=self.g.phase_priority_status()
        row=next(x for x in phase["available_unclaimed"] if x["id"]=="R45")
        self.assertTrue(row["remediation"])
        self.assertEqual(row["previous_agent_id"],"worker-remediate")
        self.assertEqual(row["previous_lease_id"],first["lease_id"])

        out=self.g.continue_agent("worker-remediate")
        self.assertTrue(out["continue_research"])
        self.assertEqual(out["next_step"],"REMEDIATE_NEEDS_WORK")
        self.assertEqual(out["next_task"]["backlog_id"],"R45")
        self.assertNotEqual(out["next_lease_id"],first["lease_id"])
        self.assertEqual(out["previous_lease_id"],first["lease_id"])
        self.assertEqual(out["previous_submission_id"],submitted["submission_id"])
        self.assertEqual(out["previous_decision"],"NEEDS_WORK")
        self.assertEqual(len(out["remediation_findings"]),1)
        self.assertEqual(out["remediation_findings"][0]["severity"],"P1")
        self.assertEqual(out["recovery_state"],
                         "NEW_REMEDIATION_LEASE_OLD_WORKSPACE_READ_ONLY")
        old=self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",
                              (first["lease_id"],)).fetchone()
        new=self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",
                              (out["next_lease_id"],)).fetchone()
        self.assertEqual(old["state"],"SUBMITTED")
        self.assertEqual(new["state"],"ACTIVE")

    def test_backlog_next_exposes_full_task_contract(self):
        from continuation import _specs
        spec=next(x for x in _specs(self.g,"research_engineer") if x.get("backlog_id")=="R45")
        lease=self.g.join(
            "worker-contract","research_engineer",spec["family"],spec["capability"],
            spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
            reuse_plan=spec.get("reuse_plan"),backlog_id="R45")
        out=self.g.continue_agent("worker-contract")
        contract=out["next_task"]["task_contract"]
        self.assertTrue(contract["required_attacks"])
        self.assertTrue(contract["promotion_exclusions"])
        self.assertIn("Offline/synthetic only",contract["cost_rule"])
        self.g.release(lease["lease_id"],"worker-contract")

    def test_p1_closeout_complete_blocks_self_directed_and_p2_autostart(self):
        # Register a stable research identity without leaving active work.
        lease=self.initial(agent="worker-closeout")
        self.g.release(lease["lease_id"],"worker-closeout")
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("candidates",[]):
            if row.get("id")=="R45":
                row["status"]="done"
                row["completion_level"]="ACCEPT_E1"
            elif row.get("plan")=="P1" and row.get("status")=="active":
                row["status"]="done"
            # Keep P2/P3 rows exactly as the production lifecycle says; they must
            # not auto-open merely because P1 has no remaining task.
        phase=data["phase_policy"]
        phase["closeout_mode"]=True
        phase["closeout_required_backlog"]=[]
        phase["p1_research_closeout_complete"]=True
        phase["closeout_reason"]="Synthetic P1 closeout is complete."
        path.write_text(json.dumps(data),encoding="utf-8")
        self.g.clock=lambda:float(self.g.policy["phase_priority_guard"]["effective_after_epoch"])+10
        out=self.g.continue_agent("worker-closeout")
        self.assertFalse(out["continue_research"])
        self.assertEqual(out["next_step"],"P1_RESEARCH_CLOSEOUT_COMPLETE")
        self.assertEqual(out["closeout_required_backlog"],[])

    def test_phase_priority_gate_ignores_unclaimable_other_pool_backlog(self):
        self.g.policy["phase_priority_guard"]["effective_after_epoch"]=0
        self.g.policy["phase_priority_guard"]["enabled"]=True
        self.g.policy["reuse_guard"]["enabled"]=False
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("candidates",[]):
            row["status"]="hold"
        main=next(r for r in data["candidates"] if r.get("id")=="MAIN01")
        main["status"]="active"
        for key in ("completion_submission","completion_level","completion_note"):
            main.pop(key,None)
        phase=data["phase_policy"]
        phase["current_phase"]="CORE_MEMORY_PORTFOLIO_RESEARCH"
        phase["auto_assign_plans"]=["CORE_MEMORY_EXPLORATION","CORE_MEMORY_MAINLINE"]
        phase["closeout_mode"]=False
        phase["closeout_required_backlog"]=[]
        phase["agent_task_pools"]={
            "explorer-pool-test":"exploration",
            "mainline-pool-test":"mainline",
        }
        path.write_text(json.dumps(data),encoding="utf-8")

        status=self.g.phase_priority_status()
        self.assertEqual([x["id"] for x in status["available_unclaimed"]],["MAIN01"])
        self.assertEqual(status["available_unclaimed"][0]["task_pool"],"mainline")

        # Explorer cannot claim MAIN01 through continuation, so MAIN01 must not
        # globally block a fresh explorer hypothesis.
        out=self.g.join(
            "explorer-pool-test","research_engineer",
            "self.directed.explorer.pool","personalization",
            "A divergent explorer may continue a distinct cross-family hypothesis when only mainline backlog remains.",
            "alternative_architecture",
            lineage="self.directed.explorer.pool")
        self.assertEqual(out["state"],"ACTIVE")
        self.g.release(out["lease_id"],"explorer-pool-test")

        # If the same cross-pool item is elevated to an observed global
        # product blocker, a fresh explorer must also yield.
        data=json.loads(path.read_text(encoding="utf-8"))
        main=next(r for r in data["candidates"] if r.get("id")=="MAIN01")
        main["priority"]=-1
        main["observed_blocker"]="synthetic-product-correctness-blocker"
        path.write_text(json.dumps(data),encoding="utf-8")
        status=self.g.phase_priority_status()
        self.assertTrue(status["available_unclaimed"][0]["global_preempt_self_directed"])
        with self.assertRaisesRegex(GovernanceError,"global product blocker backlog"):
            self.g.join(
                "explorer-pool-urgent","research_engineer",
                "self.directed.explorer.urgent","personalization",
                "A fresh explorer must yield when a cross-pool negative-priority product blocker is waiting.",
                "alternative_architecture",
                lineage="self.directed.explorer.urgent")

        # The same backlog remains claimable for a mainline worker and therefore
        # must still block that worker's self-directed bypass.
        with self.assertRaisesRegex(GovernanceError,"global product blocker backlog"):
            self.g.join(
                "mainline-pool-test","research_engineer",
                "self.directed.mainline.pool","cost_reliability",
                "A mainline worker must not bypass an available mainline backlog item with self-directed work.",
                "main_bottleneck",
                lineage="self.directed.mainline.pool")

    def test_phase_priority_gate_respects_remediation_author_continuity(self):
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        data["phase_policy"]["agent_task_pools"]={
            "mainline-owner":"mainline",
            "mainline-peer":"mainline",
        }
        path.write_text(json.dumps(data),encoding="utf-8")
        phase_status={
            "available_unclaimed":[{
                "id":"MAIN01",
                "task_pool":"mainline",
                "remediation":True,
                "previous_agent_id":"mainline-owner",
            }]
        }
        self.assertEqual(
            [x["id"] for x in self.g._phase_claimable_for_agent(
                phase_status,"mainline-owner")],
            ["MAIN01"])
        self.assertEqual(
            self.g._phase_claimable_for_agent(phase_status,"mainline-peer"),[])

    def test_phase_priority_gate_blocks_self_directed_while_unclaimed_p1_exists(self):
        self.g.policy["phase_priority_guard"]["effective_after_epoch"]=0
        self.g.policy["phase_priority_guard"]["enabled"]=True
        status=self.g.phase_priority_status()
        self.assertTrue(status["active"])
        self.assertTrue(status["available_unclaimed"])
        with self.assertRaisesRegex(GovernanceError,"Phase-priority gate"):
            self.g.join(
                "worker-self","research_engineer",
                "self.directed.cost","cost_reliability",
                "A new self-directed cost experiment should not preempt an available P1 backlog blocker.",
                "main_bottleneck",
                lineage="self.directed.cost")

        # The same guard must not block a vetted backlog-bound claim.
        from continuation import _specs
        spec=_specs(self.g,"research_engineer")[0]
        out=self.g.join(
            "worker-backlog","research_engineer",spec["family"],spec["capability"],
            spec["hypothesis"],spec["lane"],lineage=spec["lineage"],
            reuse_plan=spec.get("reuse_plan"),backlog_id=spec.get("backlog_id") or "")
        self.assertEqual(out["state"],"ACTIVE")
        self.g.release(out["lease_id"],"worker-backlog")

    def test_phase_priority_reexposes_released_unsubmitted_backlog(self):
        self.g.policy["phase_priority_guard"]["effective_after_epoch"]=0
        self.g.policy["phase_priority_guard"]["enabled"]=True
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        row=next(r for r in data["candidates"] if r.get("id")=="R45")
        row["priority"]=-20
        data["phase_policy"]["closeout_mode"]=False
        data["phase_policy"]["closeout_required_backlog"]=[]
        path.write_text(json.dumps(data),encoding="utf-8")

        from continuation import _specs
        spec=next(x for x in _specs(self.g,"research_engineer")
                  if x.get("backlog_id")=="R45")
        lease=self.g.join(
            "released-formal-owner","research_engineer",
            spec["family"],spec["capability"],spec["hypothesis"],spec["lane"],
            lineage=spec["lineage"],reuse_plan=spec.get("reuse_plan"),
            backlog_id="R45")
        self.g.release(lease["lease_id"],"released-formal-owner")

        status=self.g.phase_priority_status()
        item=next(x for x in status["available_unclaimed"] if x["id"]=="R45")
        self.assertTrue(item["followup"])
        self.assertTrue(item["global_preempt_self_directed"])
        self.assertEqual(item["previous_lease_id"],lease["lease_id"])

        with self.assertRaisesRegex(GovernanceError,"global product blocker backlog"):
            self.g.join(
                "fresh-self-directed","research_engineer",
                "self.directed.must.yield","cost_reliability",
                "A fresh self-directed task must yield when a released unsubmitted formal blocker remains active.",
                "main_bottleneck",lineage="self.directed.must.yield",
                reuse_plan={
                    "mode":"extend",
                    "components":["xiaoyu_existing_core"],
                    "gap":"Synthetic test-only reuse plan long enough to exercise the phase-priority guard before any new work.",
                    "new_dependencies":[],
                    "no_new_infrastructure":True,
                })

    def test_phase_priority_gate_reopens_self_directed_after_backlog_exhaustion(self):
        self.g.policy["phase_priority_guard"]["effective_after_epoch"]=0
        self.g.policy["phase_priority_guard"]["enabled"]=True
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        data["phase_policy"]["closeout_mode"]=False
        path.write_text(json.dumps(data),encoding="utf-8")
        self.hold_all_backlog()
        status=self.g.phase_priority_status()
        self.assertEqual(status["available_unclaimed"],[])
        out=self.g.join(
            "worker-self-open","research_engineer",
            "self.directed.after.p1","cost_reliability",
            "After all current-phase backlog work is exhausted, a fresh self-directed falsifiable task may be opened.",
            "main_bottleneck",
            lineage="self.directed.after.p1")
        self.assertEqual(out["state"],"ACTIVE")

    def test_p1_closeout_stops_self_directed_continuation_when_gates_in_flight(self):
        seed=self.initial(agent="worker-closeout")
        self.g.release(seed["lease_id"],"worker-closeout")
        self.g.policy["phase_priority_guard"]["effective_after_epoch"]=0
        self.g.policy["phase_priority_guard"]["enabled"]=True
        self.hold_all_backlog()
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        data["phase_policy"]["closeout_mode"]=True
        data["phase_policy"]["p1_research_closeout_complete"]=False
        data["phase_policy"]["closeout_required_backlog"]=["R35","R39","R41"]
        data["phase_policy"]["closeout_reason"]="Synthetic P1 closeout gates are active/pending."
        path.write_text(json.dumps(data),encoding="utf-8")
        out=self.g.continue_agent("worker-closeout")
        self.assertFalse(out["continue_research"])
        self.assertIsNone(out["next_task"])
        self.assertEqual(out["next_step"],"P1_CLOSEOUT_GATES_IN_FLIGHT")
        self.assertEqual(out["closeout_required_backlog"],["R35","R39","R41"])
        self.assertIn("closeout",out["reason"].lower())

    def test_p1_closeout_blocks_explicit_self_directed_join_but_not_backlog_claim(self):
        self.g.policy["phase_priority_guard"]["effective_after_epoch"]=0
        self.g.policy["phase_priority_guard"]["enabled"]=True
        with self.assertRaisesRegex(GovernanceError,"phase closeout mode"):
            self.g.join(
                "worker-closeout-self","research_engineer",
                "self.directed.closeout","cost_reliability",
                "A self-directed experiment must not open while P1 closeout gates are already active or pending.",
                "main_bottleneck",lineage="self.directed.closeout")
        from continuation import _specs
        spec=_specs(self.g,"research_engineer")[0]
        out=self.g.join(
            "worker-closeout-backlog","research_engineer",
            spec["family"],spec["capability"],spec["hypothesis"],spec["lane"],
            lineage=spec["lineage"],reuse_plan=spec.get("reuse_plan"),
            backlog_id=spec.get("backlog_id") or "")
        self.assertEqual(out["state"],"ACTIVE")
        self.g.release(out["lease_id"],"worker-closeout-backlog")

    def test_phase_policy_can_explicitly_unlock_p2(self):
        from continuation import _specs
        path=self.home/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        target=next(r for r in data["candidates"] if r["id"]=="R23")
        target["status"]="active"
        data["phase_policy"]["current_phase"]="P2"
        data["phase_policy"]["auto_assign_plans"]=["P2"]
        path.write_text(json.dumps(data),encoding="utf-8")
        ids=[x.get("backlog_id") for x in _specs(self.g,"research_engineer")]
        self.assertIn("R23",ids)
        self.assertNotIn("R12",ids)
        self.assertNotIn("R38",ids)

    def test_paused_project_submission_is_not_rolled_back(self):
        a=self.initial()
        self.g.pause(True,"Dangerous researcher-side artifact was found")
        out=self.submit(a,"worker-a")
        self.assertEqual(out["next_step"],"PAUSED")
        self.assertFalse(out["continue_research"])
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")
    def test_concurrent_peer_claim_skipped(self):
        peer=self.g.join("worker-b","research_engineer","oss.audit.identity",
                         "identity_continuity","Another peer is using an already assigned topic.",
                         "evaluation_data",lineage="oss.audit")
        first=self.initial()
        out=self.submit(first,"worker-a")
        self.assertNotEqual(out["next_task"]["family"],"oss.audit.identity")
        self.assertNotEqual(peer["lease_id"],out["next_lease_id"])
        self.assertEqual(self.g.status()["active_total"],2)

    def test_active_reentry_discovers_durable_files_without_final_checkpoint(self):
        a=self.initial()
        (Path(a["workspace"])/"partial_experiment.json").write_text('{"completed_steps":3}',encoding="utf-8")
        (Path(a["workspace"])/"notes.py").write_text('print(1)',encoding="utf-8")
        result=self.g.continue_agent("worker-a")
        self.assertTrue(result["resumed"])
        self.assertEqual(result["next_lease_id"],a["lease_id"])
        self.assertEqual(result["workspace_recovery"]["file_count"],2)
        self.assertIn("partial_experiment.json",[f["path"] for f in result["workspace_recovery"]["recent_files"]])

    def test_stale_unmanaged_self_directed_yields_to_unclaimed_formal_p1(self):
        from continuation import _specs
        a=self.initial()
        old=Path(a["workspace"])
        (old/"partial.py").write_text("pass\n",encoding="utf-8")
        self.g.clock=lambda:1_005_500.0
        expected=next(spec for spec in _specs(self.g,"research_engineer")
                      if not self.g.db.execute(
                          "SELECT 1 FROM leases WHERE family=? AND capability=? LIMIT 1",
                          (spec["family"],spec["capability"])).fetchone())
        out=self.g.continue_agent("worker-a")
        self.assertEqual(out["next_step"],"WORK_IN_ASSIGNED_WORKSPACE")
        self.assertEqual(out["next_task"]["family"],expected["family"])
        self.assertEqual(out["next_task"]["backlog_id"],expected["backlog_id"])
        self.assertEqual(out["deferred_recovery"]["lease_id"],a["lease_id"])
        self.assertEqual(out["deferred_recovery"]["workspace"],str(old))
        self.assertEqual((old/"partial.py").read_text(encoding="utf-8"),"pass\n")
        self.assertEqual(
            self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",(a["lease_id"],)).fetchone()["state"],
            "STALE")

    def test_stale_reentry_preserves_files_and_claims_new_lease(self):
        self.hold_all_backlog()
        a=self.initial()
        old=Path(a["workspace"])
        (old/"partial.py").write_text("pass\n",encoding="utf-8")
        self.g.clock=lambda:1_005_500.0
        out=self.g.continue_agent("worker-a")
        self.assertEqual(out["next_step"],"RECOVER_FROM_PREVIOUS_WORKSPACE")
        self.assertEqual(out["previous_lease_id"],a["lease_id"])
        self.assertEqual(out["previous_workspace"],str(old))
        self.assertEqual(out["previous_lease_state"],"STALE")
        self.assertNotEqual(out["next_lease_id"],a["lease_id"])
        self.assertNotEqual(out["next_workspace"],str(old))
        self.assertEqual((old/"partial.py").read_text(encoding="utf-8"),"pass\n")
        self.assertEqual(self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",(a["lease_id"],)).fetchone()["state"],"STALE")
        self.assertEqual(self.g.status()["active_total"],1)
        resumed=self.g.continue_agent("worker-a")
        self.assertEqual(resumed["next_lease_id"],out["next_lease_id"])
        self.assertTrue(resumed["resumed"])

    def test_stale_formal_backlog_recovery_preserves_backlog_binding_and_contract(self):
        from continuation import _specs
        spec=next(x for x in _specs(self.g,"research_engineer") if x.get("backlog_id")=="R45")
        a=self.g.join(
            "worker-formal-recover","research_engineer",
            spec["family"],spec["capability"],spec["hypothesis"],spec["lane"],
            lineage=spec["lineage"],reuse_plan=spec.get("reuse_plan"),backlog_id="R45")
        old=Path(a["workspace"])
        (old/"partial.txt").write_text("formal-progress\n",encoding="utf-8")
        self.g.clock=lambda:1_005_500.0
        out=self.g.continue_agent("worker-formal-recover")
        self.assertEqual(out["next_step"],"RECOVER_FROM_PREVIOUS_WORKSPACE")
        self.assertEqual(out["previous_lease_id"],a["lease_id"])
        self.assertEqual(out["next_task"]["backlog_id"],"R45")
        self.assertEqual(out["next_task"]["family"],spec["family"])
        self.assertIn("task_contract",out["next_task"])
        fixture=json.loads((self.home/"governance"/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        expected_row=next(x for x in fixture["candidates"] if x.get("id")=="R45")
        self.assertEqual(out["next_task"]["task_contract"]["falsifier"],expected_row["falsifier"])
        fresh=self.g.db.execute(
            "SELECT backlog_id,reuse_guard_version,reuse_plan_json FROM leases WHERE lease_id=?",
            (out["next_lease_id"],)).fetchone()
        self.assertEqual(fresh["backlog_id"],"R45")
        self.assertGreater(int(fresh["reuse_guard_version"] or 0),0)
        self.assertTrue(fresh["reuse_plan_json"])
        self.assertEqual((old/"partial.txt").read_text(encoding="utf-8"),"formal-progress\n")

    def test_ttl_reentry_preserves_files_even_after_timeout(self):
        self.hold_all_backlog()
        a=self.initial()
        (Path(a["workspace"])/"intermediate.csv").write_text("step,value\n1,good\n",encoding="utf-8")
        self.g.clock=lambda:1_014_401.0
        out=self.g.continue_agent("worker-a")
        self.assertEqual(out["previous_lease_state"],"TTL_EXPIRED")
        self.assertEqual(out["next_step"],"RECOVER_FROM_PREVIOUS_WORKSPACE")
        self.assertIn("intermediate.csv",[f["path"] for f in out["workspace_recovery"]["recent_files"]])

    def test_reentry_never_revives_stale_lease_if_peer_took_same_family(self):
        self.hold_all_backlog()
        a=self.initial()
        self.g.clock=lambda:1_005_500.0
        peer=self.g.join("worker-b","research_engineer","test.first",
                         "memory_retrieval","A synthetic offline source test should detect unsupported claims.",
                         "main_bottleneck")
        out=self.g.continue_agent("worker-a")
        self.assertEqual(out["next_step"],"RECOVERY_CLAIM_BLOCKED")
        self.assertFalse(out["continue_research"])
        self.assertEqual(out["previous_lease_id"],a["lease_id"])
        self.assertEqual(self.g.status()["active_total"],1)
        self.assertEqual(self.g.status()["active"][0]["lease_id"],peer["lease_id"])

if __name__=="__main__":
    unittest.main(verbosity=2)
