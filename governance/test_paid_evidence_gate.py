# -*- coding: utf-8 -*-
"""Paid-model E1 provenance gate regressions. Synthetic local SQLite only."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from control import Governance, GovernanceError

HERE=Path(__file__).parent

class PaidEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance"
        gov.mkdir()
        for name in ("policy.json","RESEARCH_BACKLOG.json","REUSE_CATALOG.json"):
            (gov/name).write_bytes((HERE/name).read_bytes())
        # R29/R35 are completed in the live project, but this suite tests their
        # frozen paid-evidence contracts. Activate only the temporary fixture copies.
        backlog_path=gov/"RESEARCH_BACKLOG.json"
        backlog=json.loads(backlog_path.read_text(encoding="utf-8"))
        for row in backlog["candidates"]:
            if row.get("id") in {"R29","R35"}:
                row["status"]="active"
                row.pop("completion_submission",None)
                row.pop("completion_level",None)
                row.pop("completion_note",None)
        backlog_path.write_text(json.dumps(backlog),encoding="utf-8")
        policy=json.loads((gov/"policy.json").read_text(encoding="utf-8"))
        self.now=[max(float(policy["reuse_guard"].get("v2_effective_after_epoch",0)),
                      float(policy["budget"]["paid_research"]["runtime_guard"]["effective_after_epoch"]))+100]
        self.g=Governance(self.root,clock=lambda:self.now[0])
        self.usage=gov/"research_api_usage.sqlite3"
        con=sqlite3.connect(self.usage)
        con.execute("""CREATE TABLE calls(
            call_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            finished_at REAL,
            phase TEXT NOT NULL,
            purpose TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            actual_tokens INTEGER,
            budget_scope TEXT,
            gateway_origin TEXT
        )""")
        con.commit();con.close()

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def backlog(self, rid="R29"):
        rows=json.loads((self.root/"governance"/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))["candidates"]
        return next(x for x in rows if x["id"]==rid)

    def claim(self, agent="paid_worker_01", rid="R29"):
        r=self.backlog(rid)
        lease=self.g.join(
            agent,"research_engineer",r["family"],r["capability"],r["hypothesis"],
            r["lane"],lineage=r["lineage"],reuse_plan=r["reuse_plan"],backlog_id=r["id"])
        return lease,r

    def add_call(self,lease,cid,scope="proxy:xiaoyu",status="COMMITTED",
                 created_offset=1,actual=1000,phase="smoke",gateway_origin="http_proxy"):
        con=sqlite3.connect(self.usage)
        created=float(self.now[0])+created_offset
        con.execute("""INSERT INTO calls(call_id,created_at,finished_at,phase,purpose,provider,
                     model,status,actual_tokens,budget_scope,gateway_origin)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid,created,created+0.5,phase,scope,"deepseek",
                     "DeepSeek-V4.1-Flash-1017",status,actual,scope,gateway_origin))
        con.commit();con.close()
        self.now[0]=max(self.now[0],created+1)

    def write_manifest(self,lease,row,paid_evidence=None,label="LEAD_READY"):
        dbrow=self.g.db.execute("SELECT * FROM leases WHERE lease_id=?",(lease["lease_id"],)).fetchone()
        w=Path(lease["workspace"])
        (w/"evidence.txt").write_text("synthetic paid-evidence result",encoding="utf-8")
        data={
            "hypothesis":row["hypothesis"],
            "falsifier":"The compliant proxy replay fails the frozen synthetic comparison.",
            "baseline":"Frozen synthetic baseline.",
            "metric":"exact frozen synthetic behavior",
            "delta":1.0 if label=="LEAD_READY" else None,
            "method":"Synthetic local test of paid-evidence provenance.",
            "limitations":"Synthetic only.",
            "evidence_label":label,
            "artifacts":["evidence.txt"],
            "reuse_compliance":{
                "components_considered":json.loads(dbrow["reuse_plan_json"])["components"],
                "new_dependencies":[],
                "new_infrastructure":False,
                "deviation":"none",
            },
        }
        if paid_evidence is not None:
            data["paid_evidence"]=paid_evidence
        (w/"result.json").write_text(json.dumps(data),encoding="utf-8")

    def valid_paid(self,cid):
        return {
            "call_ids":[cid],
            "budget_scope":"proxy:xiaoyu",
            "phase":"smoke",
            "max_raw_tokens":100000,
        }

    def test_lead_ready_gateway_claim_requires_paid_evidence(self):
        lease,row=self.claim()
        self.write_manifest(lease,row)
        with self.assertRaisesRegex(GovernanceError,"requires paid_evidence"):
            self.g.submit(lease["lease_id"],"paid_worker_01","result.json")

    def test_direct_scope_cannot_be_declared_as_paid_evidence(self):
        lease,row=self.claim()
        cid="api-"+"a"*32
        self.add_call(lease,cid,scope="direct:forbidden")
        pe=self.valid_paid(cid);pe["budget_scope"]="direct:forbidden"
        self.write_manifest(lease,row,pe)
        with self.assertRaisesRegex(GovernanceError,"must be an explicit proxy"):
            self.g.submit(lease["lease_id"],"paid_worker_01","result.json")

    def test_proxy_named_row_without_http_proxy_origin_is_rejected(self):
        lease,row=self.claim()
        cid="api-"+"e"*32
        self.add_call(lease,cid,scope="proxy:xiaoyu",gateway_origin="direct")
        pe=self.valid_paid(cid)
        self.write_manifest(lease,row,pe)
        with self.assertRaisesRegex(GovernanceError,"lacks authenticated HTTP proxy provenance"):
            self.g.submit(lease["lease_id"],"paid_worker_01","result.json")

    def test_allowlisted_base_tag_accepts_unique_run_suffix_without_prefrozen_scope(self):
        hypothesis="A self-directed governed DeepSeek smoke can use an allowlisted proxy run suffix when no formal backlog contract pre-freezes an exact scope."
        plan={
            "mode":"falsification",
            "components":["deepseek_semantic_projector","strict_response_validator",
                          "research_api_gateway","xiaoyu_existing_core"],
            "gap":"Reuse the governed model gateway and accepted validator; this synthetic governance test checks only proxy-suffix provenance behavior and adds no infrastructure.",
            "no_new_infrastructure":True,
            "new_dependencies":[],
            "prior_work":{
                "reviewed":[],
                "novelty":"This synthetic governance-only claim exercises paid-evidence scope handling for a self-directed task without a formal backlog scope contract.",
                "replication_of":None,
            },
        }
        lease=self.g.join(
            "paid_worker_suffix","research_engineer","test.paid.suffix","memory_evidence",
            hypothesis,"main_bottleneck",lineage="test.paid.suffix",reuse_plan=plan)
        row={"hypothesis":hypothesis}
        cid="api-"+"f"*32
        scope="proxy:xiaoyu:r29_replay_v1"
        self.add_call(lease,cid,scope=scope)
        pe=self.valid_paid(cid);pe["budget_scope"]=scope
        self.write_manifest(lease,row,pe)
        out=self.g.submit(lease["lease_id"],"paid_worker_suffix","result.json")
        receipt=json.loads((Path(lease["workspace"])/"receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["paid_evidence_verified"]["budget_scope"],scope)
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")

    def test_scope_mismatch_is_rejected(self):
        lease,row=self.claim()
        cid="api-"+"b"*32
        self.add_call(lease,cid,scope="proxy:xiaoyu")
        pe=self.valid_paid(cid);pe["budget_scope"]="proxy:cognee"
        self.write_manifest(lease,row,pe)
        with self.assertRaisesRegex(GovernanceError,"differs from pre-frozen backlog requirement"):
            self.g.submit(lease["lease_id"],"paid_worker_01","result.json")

    def test_valid_proxy_call_is_bound_into_receipt(self):
        lease,row=self.claim()
        cid="api-"+"c"*32
        self.add_call(lease,cid)
        self.write_manifest(lease,row,self.valid_paid(cid))
        out=self.g.submit(lease["lease_id"],"paid_worker_01","result.json")
        receipt=json.loads((Path(lease["workspace"])/"receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["paid_evidence_verified"]["calls"],1)
        self.assertEqual(receipt["paid_evidence_verified"]["raw_tokens"],1000)
        self.assertEqual(receipt["paid_evidence_verified"]["budget_scope"],"proxy:xiaoyu")
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")

    def test_prefrozen_backlog_scope_cannot_be_rewritten_after_calls(self):
        lease,row=self.claim(agent="paid_r35_scope",rid="R35")
        cid="api-"+"1"*32
        actual_scope="proxy:xiaoyu:r37_whole_r1"
        self.add_call(lease,cid,scope=actual_scope,actual=1000)
        pe={
            "call_ids":[cid],
            "budget_scope":actual_scope,
            "phase":"smoke",
            "max_raw_tokens":40000,
        }
        self.write_manifest(lease,row,pe)
        with self.assertRaisesRegex(GovernanceError,"differs from pre-frozen backlog requirement"):
            self.g.submit(lease["lease_id"],"paid_r35_scope","result.json")

    def test_prefrozen_backlog_raw_cap_cannot_be_raised_posthoc(self):
        lease,row=self.claim(agent="paid_r35_cap",rid="R35")
        cid="api-"+"2"*32
        scope="proxy:xiaoyu:r35_final_projection_v1"
        self.add_call(lease,cid,scope=scope,actual=1000)
        pe={
            "call_ids":[cid],
            "budget_scope":scope,
            "phase":"smoke",
            "max_raw_tokens":50000,
        }
        self.write_manifest(lease,row,pe)
        with self.assertRaisesRegex(GovernanceError,"max_raw_tokens differs from pre-frozen"):
            self.g.submit(lease["lease_id"],"paid_r35_cap","result.json")

    def test_prefrozen_backlog_paid_contract_passes_when_exact(self):
        lease,row=self.claim(agent="paid_r35_exact",rid="R35")
        cid="api-"+"3"*32
        scope="proxy:xiaoyu:r35_final_projection_v1"
        self.add_call(lease,cid,scope=scope,actual=1000)
        pe={
            "call_ids":[cid],
            "budget_scope":scope,
            "phase":"smoke",
            "max_raw_tokens":40000,
        }
        self.write_manifest(lease,row,pe)
        out=self.g.submit(lease["lease_id"],"paid_r35_exact","result.json")
        receipt=json.loads((Path(lease["workspace"])/"receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["paid_evidence_verified"]["budget_scope"],scope)
        self.assertEqual(receipt["paid_evidence_verified"]["raw_tokens"],1000)
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")

    def test_auditor_rechecks_ledger_before_accept_e1(self):
        lease,row=self.claim()
        cid="api-"+"d"*32
        self.add_call(lease,cid)
        self.write_manifest(lease,row,self.valid_paid(cid))
        out=self.g.submit(lease["lease_id"],"paid_worker_01","result.json")
        con=sqlite3.connect(self.usage)
        con.execute("UPDATE calls SET status='UNKNOWN' WHERE call_id=?",(cid,))
        con.commit();con.close()
        self.g.join(
            "paid_auditor_01","auditor","audit.paid.evidence","cost_reliability",
            "Independently verify paid E1 provenance against the durable local usage ledger.",
            "evaluation_data")
        with self.assertRaisesRegex(GovernanceError,"not COMMITTED"):
            self.g.review(
                out["submission_id"],"paid_auditor_01","ACCEPT_E1",
                "Semantic evidence is otherwise reproducible; paid provenance is rechecked.")

    def test_evidence_only_is_not_forced_to_claim_paid_calls(self):
        lease,row=self.claim()
        self.write_manifest(lease,row,paid_evidence=None,label="EVIDENCE_ONLY")
        out=self.g.submit(lease["lease_id"],"paid_worker_01","result.json")
        self.assertEqual(self.g.verify_receipt(out["submission_id"])["integrity"],"PASS")

if __name__=="__main__":
    unittest.main(verbosity=2)
