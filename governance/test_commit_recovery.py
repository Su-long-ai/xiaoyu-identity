# -*- coding: utf-8 -*-
"""Commit-first delivery reliability: no duplicate work after handoff errors."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from control import Governance

HERE=Path(__file__).parent
class CommitRecovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        folder=self.root/"governance"
        folder.mkdir()
        for filename in ("policy.json","RESEARCH_BACKLOG.json"):
            (folder/filename).write_bytes((HERE/filename).read_bytes())
        self.g=Governance(self.root,clock=lambda:10000.0)
    def tearDown(self):
        self.g.close()
        self.temp.cleanup()
    def hold_all_backlog(self):
        path=self.root/"governance"/"RESEARCH_BACKLOG.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("candidates",[]):
            row["status"]="hold"
        path.write_text(json.dumps(data),encoding="utf-8")
    def lease(self):
        return self.g.join("worker-recovery","research_engineer",
                           "test.commit.recovery","memory_retrieval",
                           "Synthetic task that validates evidence commit before continuation",
                           "main_bottleneck")
    def payload(self,lease):
        w=Path(lease["workspace"])
        (w/"file.txt").write_text("synthetic evidence",encoding="utf-8")
        (w/"result.json").write_text(json.dumps(dict(
            hypothesis="Synthetic task that validates evidence commit before continuation",
            falsifier="Unrecoverable answer cannot be accepted",
            baseline="Existing context slice implementation",
            metric="Committed valid receipts",
            delta=None,method="Deterministic temp-dir synthetic test",
            limitations="Synthetic only no model or private data",
            evidence_label="EVIDENCE_ONLY",artifacts=["file.txt"]
        )),encoding="utf-8")
    def test_delivery_returns_success_if_next_claim_fails(self):
        lease=self.lease()
        self.payload(lease)
        with patch.object(self.g,"continue_agent",side_effect=ValueError("Simulated malformed next task")):
            response=self.g.submit(lease["lease_id"],"worker-recovery","result.json")
        self.assertIn("submission_id",response)
        self.assertEqual(response["next_step"],"RETRY_NEXT")
        self.assertFalse(response["continue_research"])
        self.assertEqual(self.g.verify_receipt(response["submission_id"])["integrity"],"PASS")
        state=self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()["state"]
        self.assertEqual(state,"SUBMITTED")
        later=self.g.continue_agent("worker-recovery")
        self.assertNotEqual(later.get("next_lease_id"),lease["lease_id"])
        self.assertEqual(self.g.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],1)
    def test_corrupt_backlog_does_not_break_commit(self):
        lease=self.lease()
        self.payload(lease)
        (self.root/"governance"/"RESEARCH_BACKLOG.json").write_text("{broken",encoding="utf-8")
        response=self.g.submit(lease["lease_id"],"worker-recovery","result.json")
        self.assertEqual(response["next_step"],"RETRY_NEXT")
        self.assertEqual(self.g.verify_receipt(response["submission_id"])["integrity"],"PASS")
        self.assertEqual(self.g.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],1)

    def test_receipt_orphan_after_rolled_back_insert_is_recoverable(self):
        lease=self.lease()
        self.payload(lease)
        self.g.db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON submissions BEGIN SELECT RAISE(ABORT,'synthetic sqlite failure'); END")
        with self.assertRaises(Exception):
            self.g.submit(lease["lease_id"],"worker-recovery","result.json")
        path=Path(lease["workspace"])/"receipt.json"
        self.assertTrue(path.exists())
        self.assertEqual(self.g.db.execute("SELECT count(*) FROM submissions").fetchone()[0],0)
        self.assertEqual(self.g.db.execute("SELECT state FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()["state"],"ACTIVE")
        self.g.db.execute("DROP TRIGGER synthetic_failure")
        result=self.g.submit(lease["lease_id"],"worker-recovery","result.json")
        self.assertEqual(self.g.verify_receipt(result["submission_id"])["integrity"],"PASS")
        self.assertEqual(self.g.db.execute("SELECT count(*) FROM submissions").fetchone()[0],1)

    def test_orphan_receipt_modified_does_not_get_silently_reused(self):
        lease=self.lease()
        self.payload(lease)
        self.g.db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON submissions BEGIN SELECT RAISE(ABORT,'synthetic sqlite failure'); END")
        with self.assertRaises(Exception):
            self.g.submit(lease["lease_id"],"worker-recovery","result.json")
        self.g.db.execute("DROP TRIGGER synthetic_failure")
        path=Path(lease["workspace"])/"receipt.json"
        obj=json.loads(path.read_text(encoding="utf-8"))
        obj["artifacts"][0]["sha256"]="0"*64
        path.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaises(Exception):
            self.g.submit(lease["lease_id"],"worker-recovery","result.json")
        self.assertEqual(self.g.db.execute("SELECT count(*) FROM submissions").fetchone()[0],0)

    def test_expired_orphan_receipt_can_resume_in_new_workspace(self):
        self.hold_all_backlog()
        lease=self.lease()
        self.payload(lease)
        previous=Path(lease["workspace"])
        (previous/"receipt.json").write_text('{"partial":"not a DB submission"}',encoding="utf-8")
        self.g.clock=lambda:10000.0 + 14500
        result=self.g.continue_agent("worker-recovery")
        self.assertEqual(result["next_step"],"RECOVER_FROM_PREVIOUS_WORKSPACE")
        self.assertEqual(result["previous_workspace"],str(previous))
        self.assertNotEqual(result["next_workspace"],str(previous))
        self.assertEqual(result["previous_lease_state"],"TTL_EXPIRED")
        self.assertIn("receipt.json",[v["path"] for v in result["workspace_recovery"]["recent_files"]])
        self.assertTrue((previous/"receipt.json").exists())
        self.assertFalse((Path(result["next_workspace"])/"receipt.json").exists())

if __name__=="__main__":
    unittest.main()
