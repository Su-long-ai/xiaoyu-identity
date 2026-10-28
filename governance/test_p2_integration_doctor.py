# -*- coding: utf-8 -*-
"""P2 closeout doctor regressions. Local synthetic registry only."""
from __future__ import annotations
import hashlib,json,sqlite3,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
import p2_integration_doctor as p2

class P2IntegrationDoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"governance").mkdir()
        self.p1_contract=self.root/"governance"/"P1_INTEGRATION_CONTRACT.json"
        self.p1_candidate=self.root/"governance"/"P1_INTEGRATION_CANDIDATE.json"
        self.p1_contract.write_text('{"p1":"contract"}\n',encoding="utf-8")
        self.p1_candidate.write_text('{"p1":"candidate"}\n',encoding="utf-8")
        self.db=self.root/"governance"/"registry.sqlite3"
        con=sqlite3.connect(self.db)
        con.executescript("""
          CREATE TABLE leases(
            lease_id TEXT PRIMARY KEY,
            family TEXT NOT NULL,
            lineage TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            state TEXT NOT NULL,
            claimed_at REAL NOT NULL
          );
          CREATE TABLE submissions(
            submission_id TEXT PRIMARY KEY,
            lease_id TEXT NOT NULL,
            decision TEXT,
            evidence_label TEXT,
            at REAL
          );
        """)
        con.close()
        self.old_root=p2.ROOT
        p2.ROOT=self.root
        self.p1_patch=patch.object(p2.p1,"evaluate",return_value={"integration_ready":True})
        self.p1_patch.start()

    def tearDown(self):
        self.p1_patch.stop()
        p2.ROOT=self.old_root
        self.tmp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def insert(self,lease_id,family,lineage,state="SUBMITTED",
               submission_id=None,decision=None,evidence_label="LEAD_READY",at=1.0):
        con=sqlite3.connect(self.db)
        con.execute("INSERT INTO leases VALUES(?,?,?,?,?,?)",
                    (lease_id,family,lineage,"agent",state,float(at)-0.5))
        if submission_id is not None:
            con.execute("INSERT INTO submissions VALUES(?,?,?,?,?)",
                        (submission_id,lease_id,decision,evidence_label,at))
        con.commit();con.close()

    def contract(self,stages):
        data={
          "schema":"xiaoyu-p2-integration-contract-v1",
          "p1_baseline":{
            "contract":"governance/P1_INTEGRATION_CONTRACT.json",
            "contract_sha256":self.sha(self.p1_contract),
            "candidate":"governance/P1_INTEGRATION_CANDIDATE.json",
            "candidate_sha256":self.sha(self.p1_candidate),
          },
          "stages":stages
        }
        path=self.root/"governance"/"P2_INTEGRATION_CONTRACT.json"
        path.write_text(json.dumps(data),encoding="utf-8")
        return path

    def test_fixed_submission_accept_is_ready(self):
        self.insert("l1","f.core","ln.core",submission_id="s1",decision="ACCEPT_E1")
        c=self.contract([{
          "id":"core","required":True,"source":"fixed_submission",
          "submission_id":"s1","expected_family":"f.core","expected_lineage":"ln.core"
        }])
        out=p2.evaluate(c,self.db)
        self.assertTrue(out["contract_healthy"])
        self.assertTrue(out["p2_closeout_ready"])
        self.assertEqual(out["required_ready_count"],1)

    def test_accepted_family_active_then_accept(self):
        self.insert("l1","f.follow","ln.follow",state="ACTIVE")
        c=self.contract([{
          "id":"follow","required":True,"source":"accepted_family",
          "family":"f.follow","lineage":"ln.follow"
        }])
        out=p2.evaluate(c,self.db)
        self.assertFalse(out["p2_closeout_ready"])
        self.assertEqual(out["stages"][0]["status"],"ACTIVE")

        con=sqlite3.connect(self.db)
        con.execute("UPDATE leases SET state='SUBMITTED' WHERE lease_id='l1'")
        con.execute("INSERT INTO submissions VALUES(?,?,?,?,?)",
                    ("s1","l1","ACCEPT_E1","LEAD_READY",2.0))
        con.commit();con.close()
        out=p2.evaluate(c,self.db)
        self.assertTrue(out["p2_closeout_ready"])
        self.assertEqual(out["stages"][0]["status"],"ACCEPT_E1")

    def test_needs_work_original_can_close_only_via_named_remediation(self):
        self.insert("orig","f.orig","ln.shared",submission_id="s-orig",
                    decision="NEEDS_WORK",at=1.0)
        self.insert("rem","f.remediation","ln.shared",submission_id="s-rem",
                    decision="ACCEPT_E1",at=2.0)
        c=self.contract([{
          "id":"closure","required":True,"source":"fixed_or_remediation",
          "submission_id":"s-orig","expected_family":"f.orig","expected_lineage":"ln.shared",
          "remediation_family":"f.remediation","remediation_lineage":"ln.shared"
        }])
        out=p2.evaluate(c,self.db)
        row=out["stages"][0]
        self.assertTrue(row["ready"])
        self.assertEqual(row["status"],"REMEDIATED_ACCEPT_E1")
        self.assertEqual(row["original"]["decision"],"NEEDS_WORK")
        self.assertEqual(row["remediation"]["submission_id"],"s-rem")

    def test_wrong_remediation_family_does_not_close(self):
        self.insert("orig","f.orig","ln.shared",submission_id="s-orig",
                    decision="NEEDS_WORK",at=1.0)
        self.insert("wrong","f.other","ln.shared",submission_id="s-wrong",
                    decision="ACCEPT_E1",at=2.0)
        c=self.contract([{
          "id":"closure","required":True,"source":"fixed_or_remediation",
          "submission_id":"s-orig","expected_family":"f.orig","expected_lineage":"ln.shared",
          "remediation_family":"f.remediation","remediation_lineage":"ln.shared"
        }])
        out=p2.evaluate(c,self.db)
        self.assertFalse(out["p2_closeout_ready"])
        self.assertEqual(out["stages"][0]["status"],"NEEDS_WORK")

    def test_p1_hash_drift_fails_contract_health(self):
        self.insert("l1","f.core","ln.core",submission_id="s1",decision="ACCEPT_E1")
        c=self.contract([{
          "id":"core","required":True,"source":"fixed_submission",
          "submission_id":"s1","expected_family":"f.core","expected_lineage":"ln.core"
        }])
        self.p1_contract.write_text('{"p1":"mutated"}\n',encoding="utf-8")
        out=p2.evaluate(c,self.db)
        self.assertFalse(out["contract_healthy"])
        self.assertFalse(out["p2_closeout_ready"])
        self.assertTrue(any(x["type"]=="p1_baseline_hash_drift" for x in out["contract_errors"]))

if __name__=="__main__":
    unittest.main(verbosity=2)
