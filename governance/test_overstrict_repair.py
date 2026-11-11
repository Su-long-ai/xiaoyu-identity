# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from control import Governance, GovernanceError
from runtime_preflight import check as runtime_check

HERE = Path(__file__).resolve().parent
POLICY = HERE / "policy.json"
CATALOG = HERE / "REUSE_CATALOG.json"


class OverstrictRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        gov = self.root / "governance"
        gov.mkdir()
        (gov / "policy.json").write_bytes(POLICY.read_bytes())
        (gov / "REUSE_CATALOG.json").write_bytes(CATALOG.read_bytes())
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.effective = float(policy["multidimensional_gate_stratification"]["effective_after_epoch"])
        self.now = self.effective + 100.0
        self.g = Governance(self.root, clock=lambda: self.now)
        self.lease = {"claimed_at": self.effective + 1.0}

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    @staticmethod
    def gate(blocker="NO_BLOCKER", implementation="PASS", safety="PASS",
             release="NOT_APPLICABLE", admin="VALID", env="READY"):
        return {
            "primary_blocker_class": blocker,
            "implementation_outcome": implementation,
            "safety_outcome": safety,
            "release_outcome": release,
            "administrative_outcome": admin,
            "environment_outcome": env,
        }

    def test_performance_nonpass_preserves_positive_science(self):
        m = {
            "evidence_label": "NONPASS",
            "scientific_outcome": "POSITIVE",
            "promotion_evidence_status": "VALID",
            "scientific_falsifier_observed": False,
            "gate_stratification": self.gate(
                blocker="IMPLEMENTATION_PERFORMANCE", implementation="FAIL"),
            "performance_gate_role": "IMPLEMENTATION_PROMOTION_GATE",
            "falsification_scope": "COST_OR_LATENCY_ONLY",
            "preserved_signal": "Functional capability gain remains valid; only the exact hot-path implementation missed latency.",
        }
        self.g._validate_scientific_evidence_separation(self.lease, m)

    def test_admin_and_environment_cannot_create_nonpass(self):
        for blocker, admin, env in [
            ("ADMINISTRATIVE", "BLOCKED", "READY"),
            ("ENVIRONMENT_DEPENDENCY", "VALID", "BLOCKED"),
        ]:
            m = {
                "evidence_label": "NONPASS",
                "scientific_outcome": "NOT_TESTED",
                "promotion_evidence_status": "INCOMPLETE",
                "scientific_falsifier_observed": False,
                "gate_stratification": self.gate(
                    blocker=blocker, implementation="NOT_TESTED",
                    safety="NOT_TESTED", admin=admin, env=env),
                "falsification_scope": "OTHER_EXPLICIT_SCOPE",
                "preserved_signal": "No scientific conclusion because execution did not occur.",
            }
            with self.assertRaisesRegex(GovernanceError, "cannot create NONPASS"):
                self.g._validate_scientific_evidence_separation(self.lease, m)

    def test_lead_ready_requires_productization_intent(self):
        base = {
            "evidence_label": "LEAD_READY",
            "scientific_outcome": "POSITIVE",
            "promotion_evidence_status": "VALID",
            "scientific_falsifier_observed": False,
            "gate_stratification": self.gate(),
        }
        with self.assertRaisesRegex(GovernanceError, "productization_intent"):
            self.g._validate_scientific_evidence_separation(self.lease, dict(base))
        base["productization_intent"] = {
            "action": "DEFER_NEXT_MINOR",
            "reason": "Capability is valid but belongs after the frozen RC-v8 release scope.",
        }
        self.g._validate_scientific_evidence_separation(self.lease, base)

    def test_lead_ready_rejects_not_tested_applicable_gates(self):
        base = {
            "evidence_label": "LEAD_READY",
            "scientific_outcome": "POSITIVE",
            "promotion_evidence_status": "VALID",
            "scientific_falsifier_observed": False,
            "productization_intent": {
                "action": "DEFER_NEXT_MINOR",
                "reason": "Synthetic validator regression; no product integration is implied.",
            },
        }
        for field in ("implementation_outcome","safety_outcome","release_outcome"):
            gate=self.gate()
            gate[field]="NOT_TESTED"
            m=dict(base)
            m["gate_stratification"]=gate
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                        GovernanceError,"requires tested/applicable promotion gates"):
                    self.g._validate_scientific_evidence_separation(self.lease,m)

        # Explicit non-applicability remains the narrow exemption and does not
        # recreate the old overstrict behavior.
        m=dict(base)
        m["gate_stratification"]=self.gate(
            implementation="PASS",safety="NOT_APPLICABLE",
            release="NOT_APPLICABLE",admin="NOT_APPLICABLE",env="NOT_APPLICABLE")
        self.g._validate_scientific_evidence_separation(self.lease,m)

    def test_invalid_backlog_is_visible_but_nonblocking(self):
        backlog = {
            "phase_policy": {
                "current_phase": "CORE_MEMORY_PORTFOLIO_RESEARCH",
                "auto_assign_plans": ["CORE_MEMORY_EXPLORATION"],
            },
            "candidates": [{
                "id": "BAD01",
                "plan": "CORE_MEMORY_EXPLORATION",
                "task_pool": "exploration",
                "priority": -99,
                "status": "active",
                "family": "portfolio.explore.invalid_contract",
                "capability": "memory_evidence",
                "lineage": "memory.invalid.contract",
                "lane": "alternative_architecture",
                "hypothesis": "A valid scientific sentence long enough for the backlog contract.",
                "reuse_plan": {
                    "mode": "not_a_real_mode",
                    "components": ["xiaoyu_existing_core"],
                    "gap": "This deliberately invalid mode should be caught before it can block the research pool.",
                    "no_new_infrastructure": True,
                    "new_dependencies": [],
                },
            }],
        }
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text(
            json.dumps(backlog, ensure_ascii=False), encoding="utf-8")
        s = self.g.phase_priority_status()
        self.assertEqual(s["available_unclaimed"], [])
        self.assertEqual(len(s["invalid_backlog"]), 1)
        self.assertFalse(s["invalid_backlog"][0]["blocking"])

    def test_lead_vetted_infrastructure_exception_is_claimable(self):
        backlog = {
            "phase_policy": {
                "current_phase": "CORE_MEMORY_PORTFOLIO_RESEARCH",
                "auto_assign_plans": ["CORE_MEMORY_EXPLORATION"],
            },
            "candidates": [{
                "id": "NEWINFRA01",
                "plan": "CORE_MEMORY_EXPLORATION",
                "task_pool": "exploration",
                "priority": 10,
                "status": "active",
                "family": "portfolio.explore.lead_vetted_new_infra",
                "capability": "memory_evidence",
                "lineage": "memory.newinfra.vetted",
                "lane": "alternative_architecture",
                "hypothesis": "Test a materially new mechanism that genuinely requires one Lead-vetted internal infrastructure exception.",
                "reuse_plan": {
                    "mode": "extend",
                    "components": ["xiaoyu_existing_core"],
                    "gap": "Existing retained components cannot express the proposed mechanism without a bounded new internal substrate.",
                    "no_new_infrastructure": False,
                    "new_dependencies": [],
                    "lead_infrastructure_exception": {
                        "approved": True,
                        "reason": "Lead explicitly approved this bounded internal substrate because existing retained components cannot represent the tested mechanism.",
                    },
                },
            }],
        }
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text(
            json.dumps(backlog, ensure_ascii=False), encoding="utf-8")
        s = self.g.phase_priority_status()
        self.assertEqual(s["invalid_backlog"], [])
        self.assertEqual([x["id"] for x in s["available_unclaimed"]], ["NEWINFRA01"])

    def test_heartbeat_slides_ttl(self):
        workspace = self.root/"governance"/"workspaces"/"fish-testlease0001"
        workspace.mkdir(parents=True)
        self.g.db.execute(
            "INSERT INTO agents(agent_id,role,joined_at,last_seen) VALUES(?,?,?,?)",
            ("agent-test0001","research_engineer",self.now-100,self.now-100))
        old_ttl = self.now + 10
        self.g.db.execute(
            """INSERT INTO leases(
                lease_id,agent_id,role,family,lineage,capability,hypothesis,lane,tier,workspace,
                claimed_at,heartbeat_at,ttl_end,state,reopen_basis,reuse_plan_json,reuse_guard_version,
                reuse_catalog_sha,reuse_decision_sha,backlog_id,worker_instance_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("fish-testlease0001","agent-test0001","research_engineer",
             "memory.test.heartbeat","memory.test.heartbeat","memory_evidence",
             "Heartbeat should renew an actively worked lease.","alternative_architecture","E0",
             str(workspace),self.now-100,self.now-20,old_ttl,"ACTIVE","",
             "{}",2,"x","x","","worker-test0001"))
        out = self.g.heartbeat("fish-testlease0001","agent-test0001","worker-test0001")
        renew = float(self.g.policy["leases"]["ttl_renew_seconds"])
        self.assertGreater(out["ttl_end"], old_ttl)
        self.assertAlmostEqual(out["ttl_end"], self.now + renew)

    def test_stop_loss_ignores_implementation_only_failures_and_exact_lineage_failures(self):
        agent="agent-stoploss01"
        self.g.db.execute(
            "INSERT INTO agents(agent_id,role,joined_at,last_seen) VALUES(?,?,?,?)",
            (agent,"research_engineer",self.now-100,self.now-100))
        family="memory.test.stoploss"
        lineage="memory.test.stoploss_lineage"

        def add(idx, manifest, delta):
            lease_id=f"fish-stoploss{idx:04d}"
            ws=self.root/"governance"/"workspaces"/lease_id
            ws.mkdir(parents=True)
            mp=ws/"result.json"
            mp.write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")
            claimed=self.effective+10+idx
            self.g.db.execute(
                """INSERT INTO leases(
                    lease_id,agent_id,role,family,lineage,capability,hypothesis,lane,tier,workspace,
                    claimed_at,heartbeat_at,ttl_end,state,reopen_basis,reuse_plan_json,reuse_guard_version,
                    reuse_catalog_sha,reuse_decision_sha,backlog_id,worker_instance_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (lease_id,agent,"research_engineer",family,lineage,"memory_evidence",
                 f"Stop-loss test hypothesis {idx} is materially distinct enough.",
                 "alternative_architecture","E0",str(ws),claimed,claimed,claimed+1000,
                 "SUBMITTED","","{}",2,"x","x","",""))
            self.g.db.execute(
                """INSERT INTO submissions(
                    submission_id,lease_id,at,evidence_label,manifest_path,manifest_sha,
                    baseline,metric,delta,decision,receipt_sha,snapshot_dir)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"sub-stoploss{idx:04d}",lease_id,claimed+1,manifest["evidence_label"],
                 str(mp),"x","b","m",delta,"PENDING","",""))

        perf={
            "evidence_label":"NONPASS","scientific_outcome":"POSITIVE",
            "promotion_evidence_status":"VALID","scientific_falsifier_observed":False,
            "falsification_scope":"COST_OR_LATENCY_ONLY",
            "preserved_signal":"Capability remains positive; only implementation performance failed.",
            "gate_stratification":self.gate(
                blocker="IMPLEMENTATION_PERFORMANCE",implementation="FAIL"),
            "performance_gate_role":"IMPLEMENTATION_PROMOTION_GATE",
        }
        for i in range(3):
            add(i,perf,0.5)
        self.assertEqual(self.g._streak(family),0)
        self.assertEqual(self.g._streak(lineage,"lineage"),0)

        exact={
            "evidence_label":"NONPASS","scientific_outcome":"NEGATIVE",
            "promotion_evidence_status":"VALID","scientific_falsifier_observed":True,
            "falsification_scope":"EXACT_HYPOTHESIS_ONLY",
            "preserved_signal":"No positive signal remains for this exact hypothesis.",
            "gate_stratification":self.gate(blocker="SCIENTIFIC"),
        }
        add(10,exact,0.0)
        self.assertEqual(self.g._streak(family),1)
        self.assertEqual(self.g._streak(lineage,"lineage"),0)

        family_level=dict(exact)
        family_level["falsification_scope"]="FAMILY_LEVEL"
        family_level["preserved_signal"]="Fresh cross-family evidence falsifies the whole tested mechanism family."
        add(11,family_level,0.0)
        self.assertEqual(self.g._streak(lineage,"lineage"),1)

    def test_runtime_preflight_blocks_missing_dependency_without_science_claim(self):
        result = runtime_check({
            "python_imports": ["json", "definitely_missing_xiaoyu_package_12345"],
            "required_files": ["definitely_missing_xiaoyu_weight.bin"],
        })
        self.assertEqual(result["status"], "BLOCKED_ENVIRONMENT_DEPENDENCY")
        self.assertEqual(result["scientific_outcome_if_blocked"], "NOT_TESTED")
        self.assertFalse(result["network_used"])


if __name__ == "__main__":
    unittest.main()
