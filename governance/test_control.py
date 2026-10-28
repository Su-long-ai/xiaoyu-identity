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
             role="research_engineer", reopen_basis=""):
        return self.g.join(agent,role,family,capability,
                           "Compare deterministic text retrieval against a short-window baseline",
                           "main_bottleneck",reopen_basis)

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
        self.assertEqual(s["paid_research_token_budget"]["active_phase"],"smoke")
        self.assertFalse(s["paid_research_token_budget"]["benchmark_unlocked"])
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

    def test_capacity_and_release(self):
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

    def test_tampering_rejected(self):
        a=self.join()
        self.manifest(a)
        out=self.g.submit(a["lease_id"],"scientist_01","result.json")
        (Path(a["workspace"])/"result.txt").write_text("tampered",encoding="utf-8")
        with self.assertRaises(GovernanceError):
            self.g.verify_receipt(out["submission_id"])

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

    def test_receipt_modification_rejected(self):
        a=self.join()
        self.manifest(a)
        result=self.g.submit(a["lease_id"],"scientist_01","result.json")
        path=Path(a["workspace"])/"receipt.json"
        receipt=json.loads(path.read_text("utf-8"))
        receipt["artifacts"][0]["sha256"]="f"*64
        path.write_text(json.dumps(receipt),encoding="utf-8")
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
