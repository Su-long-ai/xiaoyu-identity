# -*- coding: utf-8 -*-
"""Smoke-exit gate regressions. No model/network calls."""
from __future__ import annotations
import hashlib,json,sqlite3,tempfile,unittest,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
import smoke_exit_doctor as sx


class SmokeExitDoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        gov=self.root/"governance"; plans=self.root/"plans"
        gov.mkdir(); plans.mkdir()
        self.db=gov/"registry.sqlite3"
        con=sqlite3.connect(self.db)
        con.executescript("""
          CREATE TABLE leases(
            lease_id TEXT PRIMARY KEY,
            agent_id TEXT,role TEXT,family TEXT,lineage TEXT,capability TEXT,
            state TEXT,claimed_at REAL
          );
          CREATE TABLE submissions(
            submission_id TEXT PRIMARY KEY,lease_id TEXT,evidence_label TEXT,
            decision TEXT,at REAL
          );
        """)
        con.close()

        self.inputs={}
        for rel in (
            "plans/matrix.md","plans/scoring.md","plans/comparator.md",
            "governance/p2.json"
        ):
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(rel+"\n",encoding="utf-8")
            self.inputs[rel]=hashlib.sha256(p.read_bytes()).hexdigest()

        self.protocol=gov/"E2.json"
        self.protocol.write_text(json.dumps({
          "schema":"xiaoyu-e2-prospective-protocol-candidate-v1",
          "status":"FROZEN_BEFORE_EXECUTION",
          "scope":{"private_identity_data":False},
          "scoring":{"required_layers":[
            "source_or_stored_state_correctness",
            "derived_or_current_state_correctness",
            "retrieved_and_admitted_context_correctness",
            "final_answer_correctness"
          ]},
          "required_tracks":[{"id":"core","ready_to_freeze":True,"blocker":None}]
        }),encoding="utf-8")

        self.contract=gov/"SMOKE.json"
        self._write_contract()
        self.p1={"integration_ready":True}
        self.p2={"p2_closeout_ready":True,"blocked_required_stages":[]}
        self.budget={
          "active_phase":"smoke","benchmark_unlocked":False,
          "phase_used_or_reserved_tokens":4500000,"phase_cap_tokens":5000000,
          "phase_remaining_tokens":500000,
          "calls_by_status":{"COMMITTED":10,"UNKNOWN":5,"RESERVED":0}
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _write_contract(self):
        c={
          "schema":"xiaoyu-smoke-exit-contract-v1",
          "pinned_inputs":{
            "matrix":{"path":"plans/matrix.md","sha256":self.inputs["plans/matrix.md"]},
            "scoring":{"path":"plans/scoring.md","sha256":self.inputs["plans/scoring.md"]},
            "comparator":{"path":"plans/comparator.md","sha256":self.inputs["plans/comparator.md"]},
            "p2":{"path":"governance/p2.json","sha256":self.inputs["governance/p2.json"]}
          },
          "e2_protocol":"governance/E2.json",
          "required_e2_protocol_status":"FROZEN_BEFORE_EXECUTION",
          "paid_phase":{
            "required_current_phase":"smoke",
            "required_benchmark_unlocked":False,
            "max_unknown_calls":5,
            "max_reserved_calls":0,
            "consume_remaining_tokens_to_exit":False
          },
          "p2_scope_lineages":["ln.p2"]
        }
        self.contract.write_text(json.dumps(c),encoding="utf-8")

    def eval(self):
        return sx.evaluate(
          self.contract,self.db,self.root,
          p1_result=self.p1,p2_result=self.p2,budget_status=self.budget)

    def insert_active(self,state="ACTIVE",pending=False):
        con=sqlite3.connect(self.db)
        con.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?)",
                    ("l1","a","research_engineer","f","ln.p2","memory_evidence",state,1.0))
        if pending:
            con.execute("INSERT INTO submissions VALUES(?,?,?,?,?)",
                        ("s1","l1","LEAD_READY","PENDING",2.0))
        con.commit();con.close()

    def test_fully_frozen_quiescent_contract_passes_without_spending_remaining_smoke(self):
        out=self.eval()
        self.assertTrue(out["smoke_exit_ready"])
        self.assertTrue(out["benchmark_phase_switch_allowed"])
        self.assertFalse(out["phase_switch_performed"])
        self.assertEqual(out["paid_phase"]["phase_remaining_tokens"],500000)

    def test_p2_blocked_prevents_exit(self):
        self.p2={"p2_closeout_ready":False,"blocked_required_stages":["x"]}
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        self.assertTrue(any(x["type"]=="p2_not_closed" for x in out["blockers"]))

    def test_protocol_must_be_frozen_and_all_required_tracks_ready(self):
        d=json.loads(self.protocol.read_text(encoding="utf-8"))
        d["status"]="DRAFT_PRE_FREEZE"
        d["required_tracks"].append({"id":"halu","ready_to_freeze":False,"blocker":"pin hash"})
        self.protocol.write_text(json.dumps(d),encoding="utf-8")
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        kinds={x["type"] for x in out["blockers"]}
        self.assertIn("e2_protocol_not_frozen",kinds)
        self.assertIn("e2_required_tracks_not_frozen",kinds)

    def test_active_or_pending_p2_scope_blocks_exit(self):
        self.insert_active(pending=True)
        out=self.eval()
        kinds={x["type"] for x in out["blockers"]}
        self.assertIn("p2_scope_not_quiescent",kinds)
        self.assertIn("p2_scope_pending_e1",kinds)

    def test_new_unknown_paid_outcome_blocks_exit(self):
        self.budget["calls_by_status"]["UNKNOWN"]=6
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        self.assertTrue(any(x["type"]=="new_unknown_paid_outcomes" for x in out["blockers"]))

    def test_reserved_paid_call_blocks_exit(self):
        self.budget["calls_by_status"]["RESERVED"]=1
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        self.assertTrue(any(x["type"]=="paid_calls_still_reserved" for x in out["blockers"]))

    def test_pinned_input_drift_is_contract_error(self):
        (self.root/"plans"/"matrix.md").write_text("mutated\n",encoding="utf-8")
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        self.assertTrue(any(x["type"]=="pinned_input_hash_drift" for x in out["errors"]))


    def test_exact_blocking_scope_ignores_optional_same_lineage(self):
        c=json.loads(self.contract.read_text(encoding="utf-8"))
        c["blocking_scopes"]=[{"family":"required.family","lineage":"ln.p2"}]
        self.contract.write_text(json.dumps(c),encoding="utf-8")
        con=sqlite3.connect(self.db)
        con.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?)",
                    ("opt1","a","research_engineer","optional.family","ln.p2",
                     "memory_evidence","ACTIVE",1.0))
        con.commit();con.close()
        out=self.eval()
        self.assertTrue(out["smoke_exit_ready"])
        self.assertEqual(out["p2_scope_state"]["mode"],"exact_scopes")

        con=sqlite3.connect(self.db)
        con.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?)",
                    ("req1","b","research_engineer","required.family","ln.p2",
                     "memory_evidence","ACTIVE",2.0))
        con.commit();con.close()
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        self.assertTrue(any(x["type"]=="p2_scope_not_quiescent"
                            for x in out["blockers"]))

    def test_required_prefreeze_evidence_must_exist_and_be_nonfailure(self):
        c=json.loads(self.contract.read_text(encoding="utf-8"))
        c["required_prefreeze_evidence"]=[{
            "id":"runner","family":"protocol.e2.execution_dryrun",
            "lineage":"evaluation.e2.runner",
            "allowed_decisions":["EVIDENCE_ONLY","ACCEPT_E1"]
        }]
        self.contract.write_text(json.dumps(c),encoding="utf-8")
        out=self.eval()
        self.assertFalse(out["smoke_exit_ready"])
        self.assertTrue(any(x["type"]=="prefreeze_evidence_incomplete"
                            for x in out["blockers"]))

        con=sqlite3.connect(self.db)
        con.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?)",
                    ("pr1","a","research_engineer","protocol.e2.execution_dryrun",
                     "evaluation.e2.runner","cost_reliability","SUBMITTED",1.0))
        con.execute("INSERT INTO submissions VALUES(?,?,?,?,?)",
                    ("ps1","pr1","EVIDENCE_ONLY","EVIDENCE_ONLY",2.0))
        con.commit();con.close()
        out=self.eval()
        self.assertTrue(out["prefreeze_evidence"]["ok"])
        self.assertFalse(any(x["type"]=="prefreeze_evidence_incomplete"
                             for x in out["blockers"]))

if __name__=="__main__":
    unittest.main(verbosity=2)
