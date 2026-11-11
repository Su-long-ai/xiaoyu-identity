# -*- coding: utf-8 -*-
"""Offline tests for governance control plane. No APIs or production identity writes."""
import json
import tempfile
import unittest
from pathlib import Path

from control import Governance,GovernanceError

SOURCE=Path(__file__).with_name("policy.json")

class TestGovernance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance"
        gov.mkdir()
        (gov/"policy.json").write_bytes(SOURCE.read_bytes())
        self.tick=[1000000.0]
        self.g=Governance(self.root,clock=lambda:self.tick[0])
    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def join(self, agent="scientist_01", family="baseline.retrieval", capability="memory_retrieval",
             role="research_engineer", reopen_basis="", worker_instance_id=""):
        return self.g.join(agent,role,family,capability,
                           "Compare deterministic text retrieval against a short-window baseline",
                           "main_bottleneck",reopen_basis,worker_instance_id=worker_instance_id)

    def manifest(self, lease, label="LEAD_READY", delta=0.1):
        workspace=Path(lease["workspace"])
        (workspace/"result.txt").write_text("synthetic test evidence only",encoding="utf-8")
        data={"hypothesis":"Compare deterministic text retrieval against a short-window baseline",
              "falsifier":"Fails when retrieval drops below baseline in fixed holdout",
              "baseline":"short window with 12 context messages",
              "metric":"fraction correct on synthetic tests",
              "delta":delta,
              "method":"fixed split, seeded deterministic test",
              "limitations":"synthetic only; no human production data",
              "evidence_label":label,"artifacts":["result.txt"]}
        (workspace/"result.json").write_text(json.dumps(data),encoding="utf-8")

    def test_empty_pool_and_capped_paid_research(self):
        s=self.g.status()
        self.assertEqual(s["active_total"],0)
        self.assertFalse(s["formal_claim_enabled"])
        self.assertIsNone(s["declared_paid_budget_usd_per_day"])
        self.assertTrue(s["runtime_api_gateway_enabled"])
        self.assertEqual(s["paid_research_token_budget"]["max_total_tokens"],100_000_000)
        self.assertEqual(s["paid_research_token_budget"]["smoke_max_tokens"],5_000_000)
        self.assertEqual(s["paid_research_token_budget"]["benchmark_max_tokens"],95_000_000)
        expected=self.g.policy["budget"]["paid_research"]
        self.assertEqual(s["paid_research_token_budget"]["active_phase"],expected["active_phase"])
        self.assertEqual(s["paid_research_token_budget"]["benchmark_unlocked"],bool(expected["benchmark_unlocked"]))
        self.assertFalse(s["identity_data_access"])

    def test_duplicate_and_unique_agent_claim(self):
        a=self.join()
        b=self.join(agent="scientist_01")
        self.assertTrue(b["resumed"])
        self.assertEqual(a["lease_id"],b["lease_id"])
        with self.assertRaises(GovernanceError):
            self.join(agent="scientist_02")
        with self.assertRaises(GovernanceError):
            self.join(agent="scientist_01",family="other.family")


    def test_backlog_current_lease_incomplete_boundary_blocks_only_lead_ready(self):
        gov=self.root/"governance"
        hypothesis="Backlog-bound synthetic evidence boundary remains supporting until successor."
        data={
            "candidates":[{
                "id":"TBOUND","status":"active","plan":"CORE_MEMORY_MAINLINE",
                "task_pool":"mainline","priority":0,"single_pass":False,
                "family":"test.boundary","lineage":"test.boundary",
                "capability":"memory_retrieval","lane":"main_bottleneck",
                "hypothesis":hypothesis,
            }],
            "phase_policy":{"auto_assign_plans":["CORE_MEMORY_MAINLINE"]}
        }
        (gov/"RESEARCH_BACKLOG.json").write_text(json.dumps(data),encoding="utf-8")
        lease=self.g.join(
            "boundary_owner","research_engineer","test.boundary","memory_retrieval",
            hypothesis,"main_bottleneck",lineage="test.boundary",backlog_id="TBOUND")
        data["candidates"][0]["current_active_lease"]=lease["lease_id"]
        data["candidates"][0]["current_active_lease_evidence_boundary"]={
            "promotion_evidence_status":"INCOMPLETE",
            "allowed_current_closeout":"EVIDENCE_ONLY/supporting; no LEAD_READY",
        }
        (gov/"RESEARCH_BACKLOG.json").write_text(json.dumps(data),encoding="utf-8")
        self.manifest(lease,label="LEAD_READY")
        rp=Path(lease["workspace"])/"result.json"
        rm=json.loads(rp.read_text(encoding="utf-8"))
        rm["hypothesis"]=hypothesis
        rp.write_text(json.dumps(rm),encoding="utf-8")
        with self.assertRaisesRegex(GovernanceError,"explicitly non-promotable"):
            self.g.submit(lease["lease_id"],"boundary_owner","result.json")
        self.manifest(lease,label="EVIDENCE_ONLY")
        rm=json.loads(rp.read_text(encoding="utf-8"))
        rm["hypothesis"]=hypothesis
        rp.write_text(json.dumps(rm),encoding="utf-8")
        out=self.g.submit(lease["lease_id"],"boundary_owner","result.json")
        self.assertEqual(out["evidence_label"],"EVIDENCE_ONLY")
        self.assertEqual(out["lead_decision"],"EVIDENCE_ONLY")

    def test_current_root_rc_freeze_blocks_only_new_self_directed_mainline(self):
        routing={
            "current_routing":{
                "product_root":{
                    "release_candidate":{
                        "status":"FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_AUDIT",
                        "freeze_record":"governance/CURRENT_PRODUCT_RC_FREEZE_20261031.json",
                    }
                }
            }
        }
        (self.root/"governance"/"CORE_MEMORY_PORTFOLIO_OPERATING_MODEL_20261031.json").write_text(
            json.dumps(routing),encoding="utf-8"
        )
        for idx,status in enumerate((
            "FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_AUDIT",
            "FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_REAUDIT",
        )):
            routing["current_routing"]["product_root"]["release_candidate"]["status"]=status
            (self.root/"governance"/"CORE_MEMORY_PORTFOLIO_OPERATING_MODEL_20261031.json").write_text(
                json.dumps(routing),encoding="utf-8"
            )
            with self.subTest(status=status):
                with self.assertRaisesRegex(GovernanceError,"Current-root mainline freeze"):
                    self.g.join(
                        f"mainline_self_{idx}","research_engineer",
                        f"portfolio.mainline.new_product_layer_{idx}","cost_reliability",
                        "A new self-directed product-layer experiment must wait for independent RC closure.",
                        "main_bottleneck",lineage="portfolio.mainline.product_boundary"
                    )

        explorer=self.g.join(
            "explorer_self","research_engineer",
            "portfolio.explore.new_mechanism","memory_retrieval",
            "A materially different exploratory mechanism remains allowed while product bytes are frozen.",
            "alternative_architecture",lineage="portfolio.exploration"
        )
        self.assertEqual(explorer["state"],"ACTIVE")
        self.g.release(explorer["lease_id"],"explorer_self")

        backlog=self.g.join(
            "mainline_backlog","research_engineer",
            "portfolio.mainline.vetted_backlog","cost_reliability",
            "A Lead-vetted backlog-bound mainline claim is not reclassified as self-directed work.",
            "main_bottleneck",lineage="portfolio.mainline.product_boundary",
            backlog_id="TEST_RC_BACKLOG"
        )
        self.assertEqual(backlog["state"],"ACTIVE")

    def test_pending_current_root_rc_does_not_preempt_active_auditor(self):
        routing={
            "current_routing":{
                "product_root":{
                    "release_candidate":{
                        "status":"FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_AUDIT",
                        "freeze_record":"governance/CURRENT_PRODUCT_RC_V99_FREEZE.json",
                        "bundle":"governance/lead_workspaces/current_product_rc_v99_test",
                        "audit_handoff":"governance/CURRENT_PRODUCT_RC_V99_AUDIT_HANDOFF.json",
                    }
                }
            }
        }
        (self.root/"governance"/"CORE_MEMORY_PORTFOLIO_OPERATING_MODEL_20261031.json").write_text(
            json.dumps(routing),encoding="utf-8"
        )
        lease=self.g.join(
            "auditor_busy","auditor","audit.existing.independent_task",
            "cost_reliability",
            "Finish the already-active independent audit before taking a later routing priority.",
            "evaluation_data",lineage="audit.existing"
        )
        out=self.g.continue_agent("auditor_busy")
        self.assertTrue(out["continue_research"])
        self.assertTrue(out["resumed"])
        self.assertEqual(out["next_lease_id"],lease["lease_id"])
        self.assertEqual(out["next_task"]["family"],"audit.existing.independent_task")

    def test_pending_current_root_rc_auto_assigns_unique_auditor_task(self):
        with self.g.tx():
            self.g.db.execute(
                "INSERT INTO agents(agent_id,role,joined_at,last_seen) VALUES(?,?,?,?)",
                ("auditor_rc","auditor",self.tick[0],self.tick[0])
            )
        routing={
            "current_routing":{
                "product_root":{
                    "release_candidate":{
                        "status":"FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_AUDIT",
                        "freeze_record":"governance/CURRENT_PRODUCT_RC_V99_FREEZE.json",
                        "bundle":"governance/lead_workspaces/current_product_rc_v99_test",
                        "audit_handoff":"governance/CURRENT_PRODUCT_RC_V99_AUDIT_HANDOFF.json",
                    }
                }
            }
        }
        (self.root/"governance"/"CORE_MEMORY_PORTFOLIO_OPERATING_MODEL_20261031.json").write_text(
            json.dumps(routing),encoding="utf-8"
        )
        status=self.g.status()
        self.assertTrue(status["capacity_reason"]["pending_current_root_rc_audit"])
        self.assertEqual(
            status["current_root_rc_audit_pending"]["bundle"],
            "governance/lead_workspaces/current_product_rc_v99_test",
        )
        out=self.g.continue_agent("auditor_rc")
        self.assertTrue(out["continue_research"])
        self.assertEqual(out["next_task"]["role"],"auditor")
        self.assertEqual(
            out["next_task"]["family"],
            "audit.current_root.release_candidate.current_product_rc_v99_test",
        )
        self.assertEqual(
            out["next_task"]["lineage"],
            "audit.current_root.release_candidate",
        )
        self.assertIn("CURRENT_PRODUCT_RC_V99_FREEZE.json",out["next_task"]["hypothesis"])
        self.assertIn("current_product_rc_v99_test",out["next_task"]["hypothesis"])
        self.assertIn("CURRENT_PRODUCT_RC_V99_AUDIT_HANDOFF.json",out["next_task"]["hypothesis"])

    def test_current_root_rc_freeze_continuation_waits_for_mapped_mainline(self):
        with self.g.tx():
            self.g.db.execute(
                "INSERT INTO agents(agent_id,role,joined_at,last_seen) VALUES(?,?,?,?)",
                ("mapped_mainline","research_engineer",self.tick[0],self.tick[0])
            )
        backlog={
            "phase_policy":{
                "current_phase":"CORE_MEMORY_PORTFOLIO_RESEARCH",
                "auto_assign_plans":[],
                "agent_task_pools":{"mapped_mainline":"mainline"},
            },
            "candidates":[],
        }
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text(
            json.dumps(backlog),encoding="utf-8"
        )
        routing={
            "current_routing":{
                "product_root":{
                    "release_candidate":{
                        "status":"FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_AUDIT",
                        "freeze_record":"governance/CURRENT_PRODUCT_RC_V7_2_FREEZE_20261031.json",
                        "bundle":"governance/lead_workspaces/current_product_rc_v7_2",
                    }
                }
            }
        }
        (self.root/"governance"/"CORE_MEMORY_PORTFOLIO_OPERATING_MODEL_20261031.json").write_text(
            json.dumps(routing),encoding="utf-8"
        )
        out=self.g.continue_agent("mapped_mainline")
        self.assertFalse(out["continue_research"])
        self.assertEqual(out["next_step"],"CURRENT_ROOT_RC_AUDIT_PENDING")
        self.assertEqual(
            out["current_root_rc"]["status"],
            "FROZEN_PENDING_INDEPENDENT_CURRENT_ROOT_AUDIT",
        )

    def test_long_hypothesis_allowed_only_for_backlog_bound_claim(self):
        long_hypothesis="Lead-vetted backlog hypothesis " + ("x" * 650)
        with self.assertRaisesRegex(GovernanceError,"Self-directed hypothesis must be at most 600 chars"):
            self.g.join(
                "long_self_directed","research_engineer","long.self.directed",
                "memory_retrieval",long_hypothesis,"main_bottleneck",
            )
        lease=self.g.join(
            "long_backlog_bound","research_engineer","long.backlog.bound",
            "memory_retrieval",long_hypothesis,"main_bottleneck",
            backlog_id="TEST_LONG_BACKLOG",
        )
        self.assertEqual(lease["state"],"ACTIVE")

    def test_parallel_chat_worker_instance_conflict_fails_closed(self):
        self.g.policy["worker_instance_guard"]["enabled"]=True
        self.g.policy["worker_instance_guard"]["effective_after_epoch"]=0
        a=self.join(worker_instance_id="chat-instance-A001")
        conflict=self.g.continue_agent("scientist_01","chat-instance-B002")
        self.assertFalse(conflict["continue_research"])
        self.assertEqual(conflict["next_step"],"WORKER_INSTANCE_CONFLICT")
        self.assertIsNone(conflict["next_workspace"])
        with self.assertRaisesRegex(GovernanceError,"WORKER_INSTANCE_CONFLICT"):
            self.g.heartbeat(a["lease_id"],"scientist_01")
        hb=self.g.heartbeat(a["lease_id"],"scientist_01","chat-instance-A001")
        self.assertEqual(hb["lease_id"],a["lease_id"])

    def test_capability_ceiling_lanes_block_only_new_self_directed_exploration(self):
        self.tick[0]=float(
            self.g.policy["phase_priority_guard"]["effective_after_epoch"]
        )+10
        self.g.policy["reuse_guard"]["enabled"]=False
        cr=self.g.policy["phase_priority_guard"]["continuous_research_exception"]
        cr["enabled"]=True
        cr["allowed_phases"]=["CORE_MEMORY_PORTFOLIO_RESEARCH"]
        cr["allowed_lanes"]=["main_bottleneck","alternative_architecture"]
        backlog={
            "phase_policy":{
                "current_phase":"CORE_MEMORY_PORTFOLIO_RESEARCH",
                "auto_assign_plans":[],
                "closeout_mode":False,
                "closeout_required_backlog":[],
                "p1_research_closeout_complete":True,
            },
            "candidates":[],
        }
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text(
            json.dumps(backlog),encoding="utf-8"
        )
        with self.assertRaisesRegex(GovernanceError,"self-directed lane is not allowed"):
            self.g.join(
                "perf_explorer","research_engineer",
                "memory.micro_performance_probe","cost_reliability",
                "A self-directed micro-performance task should not consume capability-ceiling exploration slots.",
                "performance_cost",lineage="memory.performance"
            )

        explorer=self.g.join(
            "cap_explorer","research_engineer",
            "memory.new_capability_probe","memory_retrieval",
            "A capability-ceiling explorer in an allowed lane remains claimable.",
            "alternative_architecture",lineage="memory.capability"
        )
        self.assertEqual(explorer["state"],"ACTIVE")
        self.g.release(explorer["lease_id"],"cap_explorer")

        # Product mainline is explicitly exempt from research-lane quota.
        mainline=self.g.join(
            "product_mainline","research_engineer",
            "portfolio.mainline.real_product_blocker","cost_reliability",
            "A concrete product mainline task may preempt the research quota even in a performance lane.",
            "performance_cost",lineage="portfolio.mainline.product_boundary"
        )
        self.assertEqual(mainline["state"],"ACTIVE")
        self.g.release(mainline["lease_id"],"product_mainline")

        # Lead-vetted backlog work is not self-directed and remains exempt.
        vetted=self.g.join(
            "vetted_perf","research_engineer",
            "memory.vetted_performance_blocker","cost_reliability",
            "A Lead-vetted backlog-bound performance blocker remains claimable.",
            "performance_cost",lineage="memory.performance",
            backlog_id="TEST_PERF_BLOCKER"
        )
        self.assertEqual(vetted["state"],"ACTIVE")

    def test_normal_portfolio_enforces_research_quota_but_exempts_product_mainline(self):
        self.tick[0]=float(
            self.g.policy["phase_priority_guard"]["effective_after_epoch"]
        )+10
        self.g.policy["reuse_guard"]["enabled"]=False
        cr=self.g.policy["phase_priority_guard"]["continuous_research_exception"]
        cr["enabled"]=True
        cr["allowed_phases"]=["CORE_MEMORY_PORTFOLIO_RESEARCH"]
        cr["allowed_lanes"]=["alternative_architecture","main_bottleneck"]
        cr["max_active_self_directed"]=2
        cr["product_mainline_never_blocked_by_research_quota"]=True
        backlog={
            "phase_policy":{
                "current_phase":"CORE_MEMORY_PORTFOLIO_RESEARCH",
                "auto_assign_plans":[],
                "closeout_mode":False,
                "closeout_required_backlog":[],
                "p1_research_closeout_complete":True,
            },
            "candidates":[],
        }
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text(
            json.dumps(backlog),encoding="utf-8"
        )
        e1=self.g.join(
            "quota_exp_1","research_engineer","memory.quota_probe_one",
            "memory_retrieval","First allowed capability explorer.",
            "alternative_architecture",lineage="memory.quota.one"
        )
        e2=self.g.join(
            "quota_exp_2","research_engineer","memory.quota_probe_two",
            "memory_evidence","Second allowed capability explorer.",
            "alternative_architecture",lineage="memory.quota.two"
        )
        status=self.g.phase_priority_status()["continuous_research"]
        self.assertEqual(status["active_count"],2)
        self.assertEqual(status["active_total_count"],2)
        self.assertEqual(status["product_mainline_active_count"],0)
        self.assertEqual(status["slots_available"],0)
        with self.assertRaisesRegex(GovernanceError,"continuous-research capacity reached"):
            self.g.join(
                "quota_exp_3","research_engineer","memory.quota_probe_three",
                "memory_retrieval","Third explorer must wait for a research quota slot.",
                "alternative_architecture",lineage="memory.quota.three"
            )
        pm=self.g.join(
            "quota_product","research_engineer",
            "portfolio.mainline.quota_product_blocker","cost_reliability",
            "Product mainline remains exempt from the capability research quota.",
            "main_bottleneck",lineage="portfolio.mainline.product_boundary"
        )
        self.assertEqual(pm["state"],"ACTIVE")
        status=self.g.phase_priority_status()["continuous_research"]
        self.assertEqual(status["active_count"],2)
        self.assertEqual(status["active_total_count"],3)
        self.assertEqual(status["product_mainline_active_count"],1)
        self.assertEqual(status["slots_available"],0)

    def test_v1_closeout_blocks_self_directed_research_but_allows_auditor(self):
        self.tick[0]=float(
            self.g.policy["phase_priority_guard"]["effective_after_epoch"]
        )+10
        self.g.policy["reuse_guard"]["enabled"]=False
        cr=self.g.policy["phase_priority_guard"]["continuous_research_exception"]
        cr["enabled"]=False
        cr["allowed_phases"]=["V1_PRODUCT_CLOSEOUT"]
        cr["max_active_self_directed"]=0
        backlog={
            "phase_policy":{
                "current_phase":"V1_PRODUCT_CLOSEOUT",
                "auto_assign_plans":["V1_PRODUCT_CLOSEOUT"],
                "closeout_mode":True,
                "closeout_required_backlog":[],
                "p1_research_closeout_complete":False,
            },
            "candidates":[],
        }
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text(
            json.dumps(backlog),encoding="utf-8"
        )
        with self.assertRaisesRegex(
            GovernanceError,"phase closeout mode is active"
        ):
            self.join(agent="continuous_01")
        out=self.g.join(
            "closeout_auditor","auditor","audit.closeout.synthetic",
            "memory_evidence",
            "Independently review a release milestone during v1 closeout.",
            "evaluation_data"
        )
        self.assertEqual(out["state"],"ACTIVE")

    def test_capacity_and_release(self):
        # This test covers the explicit legacy fixed-capacity fallback.
        self.g.policy["startup"]["dynamic_capacity"]["enabled"]=False
        self.g.policy["startup"]["research_engineers"]=2
        self.g.policy["startup"]["max_total"]=3
        a=self.join()
        self.join(agent="scientist_02",family="temporal.correct",capability="temporal_correction")
        with self.assertRaises(GovernanceError):
            self.join(agent="scientist_03",family="private.erase",capability="privacy_erasure")
        self.g.release(a["lease_id"],"scientist_01")
        c=self.join(agent="scientist_03",family="private.erase",capability="privacy_erasure")
        self.assertEqual(c["state"],"ACTIVE")

    def test_stale_and_hard_ttl(self):
        a=self.join()
        self.tick[0]+=5400
        self.g.reap()
        row=self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",(a["lease_id"],)).fetchone()
        self.assertEqual(row["state"],"STALE")
        b=self.join(agent="scientist_01",family="baseline.retrieval")
        self.assertNotEqual(a["lease_id"],b["lease_id"])
        self.tick[0]+=14400
        self.g.reap()
        self.assertEqual(self.g.status()["active_total"],0)

    def test_submit_and_distinct_auditor(self):
        a=self.join()
        self.manifest(a)
        self.g.join("auditor_01","auditor","independent.audit","memory_evidence",
                    "Independently verify candidate integrity and falsifier availability",
                    "evaluation_data")
        out=self.g.submit(a["lease_id"],"scientist_01","result.json")
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")
        with self.assertRaises(GovernanceError):
            self.g.review(out["submission_id"],"scientist_01","ACCEPT_E1",
                          "Specific checksum and method look valid")
        reviewed=self.g.review(out["submission_id"],"auditor_01","ACCEPT_E1",
                               "Independent checksum verified; candidate only, not formal scientific proof")
        self.assertEqual(reviewed["scientific_claim"],"NOT_GRANTED")
        with self.assertRaises(GovernanceError):
            self.g.review(out["submission_id"],"auditor_01","ACCEPT_E1",
                          "Duplicate review must be forbidden")

    def test_workspace_tampering_does_not_change_committed_snapshot(self):
        a=self.join()
        self.manifest(a)
        out=self.g.submit(a["lease_id"],"scientist_01","result.json")
        (Path(a["workspace"])/"result.txt").write_text("tampered",encoding="utf-8")
        (Path(a["workspace"])/"result.json").write_text("{\"tampered\":true}",encoding="utf-8")
        verified=self.g.verify_receipt(out["submission_id"])
        self.assertEqual(verified["integrity"],"PASS")
        self.assertEqual(verified["integrity_source"],"IMMUTABLE_SUBMISSION_SNAPSHOT")

    def test_path_escape_refused(self):
        a=self.join()
        self.manifest(a)
        manifest=json.loads((Path(a["workspace"])/"result.json").read_text())
        manifest["artifacts"]=["..\\outside.txt","../../identity/identity.sqlite3"]
        (Path(a["workspace"])/"result.json").write_text(json.dumps(manifest))
        with self.assertRaises((GovernanceError,FileNotFoundError)):
            self.g.submit(a["lease_id"],"scientist_01","result.json")
        self.assertEqual(self.g.status()["active_total"],1)

    def test_stop_loss_requires_actual_reopen_basis(self):
        for idx in range(3):
            lease=self.join(agent="scientist_0"+str(idx+1))
            self.manifest(lease,label="NONPASS",delta=-0.1)
            self.g.submit(lease["lease_id"],"scientist_0"+str(idx+1),"result.json")
        self.assertEqual(self.g._streak("baseline.retrieval"),3)
        with self.assertRaises(GovernanceError):
            self.join(agent="scientist_04")
        reopened=self.join(
            agent="scientist_04",
            reopen_basis="New contrastive representation with independent holdout and testable falsifier")
        self.assertEqual(reopened["state"],"ACTIVE")

    def test_pause_and_resume(self):
        self.g.pause(True,"Observed private memory leak in proposed candidate")
        with self.assertRaises(GovernanceError):
            self.join()
        self.g.pause(False,"Privacy issue isolated, explicit sandbox approved")
        self.assertEqual(self.join()["state"],"ACTIVE")

    def test_bad_manifest_no_submission(self):
        a=self.join()
        self.manifest(a,delta=float("nan"))
        with self.assertRaises(GovernanceError):
            self.g.submit(a["lease_id"],"scientist_01","result.json")
        self.assertEqual(len(self.g.queue()),0)

    def test_snapshot_modification_rejected(self):
        a=self.join()
        self.manifest(a)
        result=self.g.submit(a["lease_id"],"scientist_01","result.json")
        # Worker receipt drift is irrelevant after commit; immutable snapshot is authoritative.
        worker_receipt=Path(a["workspace"])/"receipt.json"
        worker_receipt.write_text("{}",encoding="utf-8")
        self.assertEqual(self.g.verify_receipt(result["submission_id"])["integrity"],"PASS")
        snapshot_receipt=Path(result["immutable_snapshot"])/"receipt.json"
        snapshot_receipt.chmod(0o666)
        receipt=json.loads(snapshot_receipt.read_text("utf-8"))
        receipt["artifacts"][0]["sha256"]="f"*64
        snapshot_receipt.write_text(json.dumps(receipt),encoding="utf-8")
        with self.assertRaises(GovernanceError):
            self.g.verify_receipt(result["submission_id"])

    def test_family_rename_cannot_reset_lineage_stoploss(self):
        for i in range(3):
            aid=f"worker_{i:02d}"
            lease=self.g.join(aid,"research_engineer",f"variant_{i:02d}",
                "memory_retrieval",
                "Compare deterministic text retrieval against a short-window baseline",
                "main_bottleneck",lineage="shared.architecture")
            self.manifest(lease,label="NONPASS",delta=-0.2)
            self.g.submit(lease["lease_id"],aid,"result.json")
        self.assertEqual(self.g._streak("shared.architecture","lineage"),3)
        with self.assertRaises(GovernanceError):
            self.g.join("worker_next","research_engineer","another_family","memory_retrieval",
                "Compare deterministic text retrieval against a short-window baseline",
                "main_bottleneck",lineage="shared.architecture")

    def test_credential_manifest_rejected(self):
        a=self.join()
        self.manifest(a)
        manifest_path=Path(a["workspace"])/"result.json"
        v=json.loads(manifest_path.read_text("utf-8"))
        v["limitations"]="test only; api_key=sk-synthetic-secret-only-for-test-123456"
        manifest_path.write_text(json.dumps(v))
        with self.assertRaises(GovernanceError):
            self.g.submit(a["lease_id"],"scientist_01","result.json")

if __name__=="__main__":unittest.main(verbosity=2)
