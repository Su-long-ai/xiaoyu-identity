# -*- coding: utf-8 -*-
"""Synthetic regression for the R45 P1 closeout finalizer."""
import json
import tempfile
import unittest
import sys
import shutil
from pathlib import Path

HERE=Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))

from control import Governance
from p1_finalize_r45 import finalize

class R45FinalizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance";gov.mkdir()
        for name in (
            "policy.json","RESEARCH_BACKLOG.json","REUSE_CATALOG.json",
            "P1_INTEGRATION_CONTRACT.json","P1_INTEGRATION_CANDIDATE.json",
        ):
            (gov/name).write_bytes((HERE/name).read_bytes())

        # Reconstruct a synthetic pre-finalize R45 state. The production files
        # are now finalized; this suite validates the transition itself.
        backlog_path=gov/"RESEARCH_BACKLOG.json"
        backlog=json.loads(backlog_path.read_text(encoding="utf-8"))
        r45=next(x for x in backlog["candidates"] if x["id"]=="R45")
        r45["status"]="active"
        for key in ("completion_submission","completion_level","completion_note"):
            r45.pop(key,None)
        phase=backlog["phase_policy"]
        phase["closeout_mode"]=True
        phase["closeout_required_backlog"]=["R45"]
        phase["p1_research_closeout_complete"]=False
        phase["closeout_reason"]="Synthetic R45 pre-finalize fixture."
        backlog_path.write_text(json.dumps(backlog),encoding="utf-8")

        contract_path=gov/"P1_INTEGRATION_CONTRACT.json"
        contract=json.loads(contract_path.read_text(encoding="utf-8"))
        erasure=next(x for x in contract["stages"] if x["id"]=="erasure_restore_reconciliation")
        erasure["status"]="blocked_no_e1"
        erasure["remediation_backlog_id"]="R45"
        for key in ("accepted_submission","audit","required_integration_e0_verified"):
            erasure.pop(key,None)
        contract_path.write_text(json.dumps(contract),encoding="utf-8")

        candidate_path=gov/"P1_INTEGRATION_CANDIDATE.json"
        candidate=json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["stage_pins"]["erasure_restore_reconciliation"]={
            "implementation":None,
            "reason":"SYNTHETIC_R45_PRE_FINALIZE",
            "required_integration_e0":next(
                ({
                  "metrics":item["metrics"],
                  "schema":item["expected_schema"],
                } for item in erasure.get("supporting_lead_e0",[])
                 if item.get("required_for_finalization")),None)
        }
        candidate_path.write_text(json.dumps(candidate),encoding="utf-8")

        # Copy only Lead-E0 metrics explicitly required by the frozen contract.
        for item in erasure.get("supporting_lead_e0",[]):
            if not item.get("required_for_finalization"):
                continue
            rel=Path(item["metrics"])
            src=HERE.parent/rel
            dst=self.root/rel
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dst)
        self.g=Governance(self.root)
        backlog=json.loads((gov/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        self.r=next(x for x in backlog["candidates"] if x["id"]=="R45")

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def submit_r45(self):
        r=self.r
        lease=self.g.join(
            "r45_test_author","research_engineer",r["family"],r["capability"],
            r["hypothesis"],r["lane"],lineage=r["lineage"],
            reuse_plan=r["reuse_plan"],backlog_id="R45")
        row=self.g.db.execute("select * from leases where lease_id=?",(lease["lease_id"],)).fetchone()
        w=Path(lease["workspace"])
        (w/"evidence.txt").write_text("fresh synthetic R45 evidence",encoding="utf-8")
        plan=json.loads(row["reuse_plan_json"])
        manifest={
          "hypothesis":r["hypothesis"],
          "falsifier":r["falsifier"],
          "baseline":"Synthetic R44 leak baseline",
          "metric":"zero sibling plaintext leaks with semantic preservation",
          "delta":1.0,
          "method":"Offline synthetic frozen comparison",
          "limitations":"Synthetic-only closeout-finalizer test",
          "evidence_label":"LEAD_READY",
          "artifacts":["evidence.txt"],
          "reuse_compliance":{
            "components_considered":plan["components"],
            "new_dependencies":[],
            "new_infrastructure":False,
            "deviation":"none",
          },
        }
        (w/"result.json").write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")
        out=self.g.submit(lease["lease_id"],"r45_test_author","result.json")
        return out["submission_id"]

    def accept(self,submission_id):
        self.g.join(
            "r45_test_auditor","auditor","audit.r45.synthetic.finalizer",
            "privacy_erasure",
            "Independent synthetic audit checks the closeout finalizer acceptance path.",
            "evaluation_data")
        return self.g.review(
            submission_id,"r45_test_auditor","ACCEPT_E1",
            "Independent synthetic audit reproduced the frozen finalizer fixture with no material finding.",
            findings=[])

    def test_pending_refuses_then_accept_finalizes(self):
        sid=self.submit_r45()
        with self.assertRaisesRegex(RuntimeError,"not independently ACCEPT_E1"):
            finalize(self.root,sid,dry_run=True)
        self.accept(sid)
        dry=finalize(self.root,sid,dry_run=True)
        self.assertEqual(dry["status"],"READY_TO_FINALIZE")
        out=finalize(self.root,sid,dry_run=False)
        self.assertEqual(out["status"],"FINALIZED")
        contract=json.loads((self.root/"governance"/"P1_INTEGRATION_CONTRACT.json").read_text(encoding="utf-8"))
        stage=next(x for x in contract["stages"] if x["id"]=="erasure_restore_reconciliation")
        self.assertEqual(stage["status"],"ready_e1")
        self.assertEqual(stage["accepted_submission"],sid)
        backlog=json.loads((self.root/"governance"/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        r45=next(x for x in backlog["candidates"] if x["id"]=="R45")
        self.assertEqual(r45["status"],"done")
        self.assertEqual(backlog["phase_policy"]["closeout_required_backlog"],[])
        self.assertTrue(backlog["phase_policy"]["p1_research_closeout_complete"])
        again=finalize(self.root,sid,dry_run=False)
        self.assertEqual(again["status"],"ALREADY_FINALIZED")

    def test_required_integration_e0_nonpass_refuses(self):
        sid=self.submit_r45()
        self.accept(sid)
        contract=json.loads((self.root/"governance"/"P1_INTEGRATION_CONTRACT.json").read_text(encoding="utf-8"))
        stage=next(x for x in contract["stages"] if x["id"]=="erasure_restore_reconciliation")
        gate=next(x for x in stage["supporting_lead_e0"] if x.get("required_for_finalization"))
        path=self.root/gate["metrics"]
        metrics=json.loads(path.read_text(encoding="utf-8"))
        metrics["pass"]=False
        path.write_text(json.dumps(metrics),encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"integration E0 is not PASS"):
            finalize(self.root,sid,dry_run=True)

    def test_material_review_tamper_refuses(self):
        sid=self.submit_r45()
        self.accept(sid)
        with self.g.tx():
            self.g.db.execute(
                "update reviews set material_count=1 where submission_id=? and decision='ACCEPT_E1'",(sid,))
        with self.assertRaisesRegex(RuntimeError,"material findings"):
            finalize(self.root,sid,dry_run=True)

if __name__=="__main__":
    unittest.main(verbosity=2)
