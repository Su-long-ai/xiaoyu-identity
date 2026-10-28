# -*- coding: utf-8 -*-
"""Risk-tiered, nonblocking independent E1 audit regression suite.
All fixtures are disposable synthetic files; not a real companion database.
"""
import json
import tempfile
import unittest
from pathlib import Path
from control import Governance, GovernanceError

POLICY=Path(__file__).with_name("policy.json")

class TestAuditMateriality(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        (root/"governance").mkdir()
        (root/"governance"/"policy.json").write_bytes(POLICY.read_bytes())
        self.now=[1_600_000.0]
        self.g=Governance(root,clock=lambda:self.now[0])
        self.g.join("audit_agent_01","auditor","audit.evidence","memory_evidence",
                    "Independent falsification of E1 memory experiments",
                    "evaluation_data")

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    @staticmethod
    def advisory(severity="P2"):
        return {"severity":severity,
                "issue":"Sample error explanations would benefit from more examples",
                "impact":"May reduce debugging comfort; main fixed metric is unaffected",
                "fix":"Add supplemental examples in next iteration"}

    @staticmethod
    def material(severity="P1"):
        return {"severity":severity,
                "observed":True,
                "issue":"Holdout examples leaked into the retrieval index",
                "impact":"Invalidates the reported benchmark improvement and its comparison",
                "reproduction":"Run seeded_eval.py --split holdout and compare indexed source hashes",
                "evidence":"The submitted test_data.txt shows holdout IDs in source index",
                "fix":"Rebuild the index from train only and rerun held-out scoring"}

    def submit(self,agent="res_agent_01",family="retrieval.dual",capability="memory_retrieval"):
        hypo="Candidate dual retrieval beats fixed 12-turn baseline on synthetic Chinese tasks"
        claim=self.g.join(agent,"research_engineer",family,capability,
                          hypo,"main_bottleneck")
        workspace=Path(claim["workspace"])
        (workspace/"score.txt").write_text("fixed synthetic seed accuracy 0.80 baseline 0.70")
        manifest={
            "hypothesis":hypo,
            "falsifier":"Holdout accuracy lower than baseline on any fixed seed group",
            "baseline":"12-message recent-only window",
            "metric":"held-out accuracy",
            "delta":0.10,
            "method":"Fixed split and same token budget",
            "limitations":"Only synthetic data; no live user records",
            "evidence_label":"LEAD_READY",
            "artifacts":["score.txt"]}
        (workspace/"result.json").write_text(json.dumps(manifest))
        sub=self.g.submit(claim["lease_id"],agent,"result.json")
        return sub

    def test_advisories_are_nonblocking_and_kept(self):
        sid=self.submit()["submission_id"]
        self.now[0]+=72
        reviewed=self.g.review(sid,"audit_agent_01","ACCEPT_E1",
                               "Measured advantage valid; minor docs refinements remain",
                               [self.advisory("P2"),self.advisory("P3")])
        self.assertEqual(reviewed["material_blockers"],0)
        self.assertEqual(len(reviewed["released_audit_leases"]),1)
        audit_state=self.g.db.execute(
            "SELECT state FROM leases WHERE lease_id=?",
            (reviewed["released_audit_leases"][0],)).fetchone()["state"]
        self.assertEqual(audit_state,"RELEASED")
        self.assertEqual(
            self.g.db.execute("SELECT role FROM agents WHERE agent_id='audit_agent_01'").fetchone()["role"],
            "auditor")
        self.assertEqual(reviewed["nonblocking_advice"],2)
        self.assertFalse(reviewed["global_research_blocked"])
        stats=self.g.audit_stats()
        self.assertEqual(stats["reviewed"],1)
        self.assertEqual(stats["accept_e1"],1)
        self.assertEqual(stats["advisory_findings"],2)
        self.assertEqual(stats["avg_queue_wait_seconds"],72)
        actual=self.g.db.execute("SELECT findings_json FROM reviews").fetchone()[0]
        self.assertEqual(len(json.loads(actual)),2)

    def test_advice_only_cannot_reject(self):
        sid=self.submit()["submission_id"]
        with self.assertRaisesRegex(GovernanceError,"cannot REJECT"):
            self.g.review(sid,"audit_agent_01","REJECT",
                          "Style not optimal, so blocking everything would be excessive",
                          [self.advisory()])
        self.assertEqual(self.g.audit_stats()["pending"],1)
        self.g.review(sid,"audit_agent_01","ACCEPT_E1",
                      "Minor style issue is advisory only, no material impact",
                      [self.advisory("P3")])

    def test_vague_material_blocker_cannot_reject(self):
        sid=self.submit()["submission_id"]
        bad=self.material()
        for key,value in [("observed",False),("reproduction","Maybe risky"),
                          ("evidence","unknown")]:
            change=bad.copy()
            change[key]=value
            with self.assertRaises(GovernanceError):
                self.g.review(sid,"audit_agent_01","NEEDS_WORK",
                              "Concern exists but no sufficient concrete proof",
                              [change])
        self.assertEqual(self.g.audit_stats()["pending"],1)

    def test_material_blocks_only_specific_candidate(self):
        sid=self.submit()["submission_id"]
        second=self.submit(agent="res_agent_02",family="memory.time",capability="temporal_correction")
        self.assertEqual(self.g.audit_stats()["pending"],2)
        with self.assertRaisesRegex(GovernanceError,"Cannot accept"):
            self.g.review(sid,"audit_agent_01","ACCEPT_E1",
                          "Claim has actual leakage and cannot pass as written",
                          [self.material()])
        outcome=self.g.review(sid,"audit_agent_01","NEEDS_WORK",
                              "Fixed split is invalid; rerun index on train only",
                              [self.material("P0")])
        self.assertEqual(outcome["material_blockers"],1)
        self.assertEqual(outcome["scope"],"THIS_E1_CANDIDATE_ONLY")
        self.assertFalse(self.g.paused())
        self.assertEqual(self.g.audit_stats()["pending"],1)
        self.g.review(second["submission_id"],"audit_agent_01","ACCEPT_E1",
                      "Separate temporal test shows a positive unchanged fixed metric",[])
        self.assertEqual(self.g.audit_stats()["accept_e1"],1)

    def test_non_auditor_and_author_cannot_review(self):
        sid=self.submit()["submission_id"]
        with self.assertRaisesRegex(GovernanceError,"Author cannot"):
            self.g.review(sid,"res_agent_01","ACCEPT_E1",
                          "Unauthorized self-review should be rejected by control")
        with self.assertRaisesRegex(GovernanceError,"registered auditor"):
            self.g.review(sid,"random_other_01","ACCEPT_E1",
                          "Unregistered reviewer should be rejected by control")

    def test_no_duplicate_round_of_nitpicks(self):
        sid=self.submit()["submission_id"]
        self.g.review(sid,"audit_agent_01","ACCEPT_E1",
                      "All material claims consistent with cited synthetic artifacts",
                      [self.advisory()])
        with self.assertRaisesRegex(GovernanceError,"No pending"):
            self.g.review(sid,"audit_agent_01","NEEDS_WORK",
                          "Another nonmaterial preference discovered much later",
                          [self.material()])

    def test_review_findings_count_cap(self):
        sid=self.submit()["submission_id"]
        with self.assertRaisesRegex(GovernanceError,"up to 8"):
            self.g.review(sid,"audit_agent_01","ACCEPT_E1",
                          "Do not waste the entire review on minor formatting",
                          [self.advisory()]*9)

    def test_queue_nonblocking_even_if_audit_never_runs(self):
        self.submit()
        self.now[0]+=1000
        stats=self.g.audit_stats()
        self.assertEqual(stats["pending"],1)
        self.assertEqual(stats["oldest_pending_age_seconds"],1000)
        self.assertFalse(stats["queue_blocks_exploration"])
        claim=self.g.join("res_agent_02","research_engineer","alternative.search",
                          "personalization",
                          "An alternative reasoning route can be explored while audit is waiting",
                          "alternative_architecture")
        self.assertEqual(claim["state"],"ACTIVE")

if __name__=="__main__":
    unittest.main(verbosity=2)
