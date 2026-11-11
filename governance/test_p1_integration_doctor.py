# -*- coding: utf-8 -*-
"""Synthetic regressions for P1 integration assembly discipline."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from p1_integration_doctor import evaluate
except ModuleNotFoundError:
    from governance.p1_integration_doctor import evaluate


class P1IntegrationDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.gov=self.root/"governance"
        self.gov.mkdir()
        (self.gov/"lead_workspaces"/"ctx").mkdir(parents=True)
        self.contract=self.gov/"P1_INTEGRATION_CONTRACT.json"
        self.candidate=self.gov/"P1_INTEGRATION_CANDIDATE.json"
        self.db=self.gov/"registry.sqlite3"
        sqlite3.connect(self.db).close()

        self.metrics=self.gov/"lead_workspaces"/"ctx"/"metrics.json"
        self.metrics.write_text(json.dumps({
            "schema":"test-lead-e0","pass":True
        }),encoding="utf-8")
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({
            "candidates":[{"id":"RTEST","status":"active","reuse_plan":{"components":[]}}]
        }),encoding="utf-8")

        self.base_contract={
            "schema":"xiaoyu-p1-integration-contract-v1",
            "stages":[{
                "id":"context_packing",
                "required":True,
                "status":"blocked_no_e1",
                "lead_e0":{
                    "metrics":"governance/lead_workspaces/ctx/metrics.json",
                    "expected_schema":"test-lead-e0",
                    "replication_backlog_id":"RTEST",
                    "replication_required":True,
                },
            }],
        }
        self.base_candidate={
            "schema":"xiaoyu-p1-integration-candidate-v1",
            "stage_pins":{"context_packing":{"implementation":None}},
        }
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        self.contract.write_text(json.dumps(self.base_contract),encoding="utf-8")
        self.candidate.write_text(json.dumps(self.base_candidate),encoding="utf-8")

    def run_doctor(self):
        return evaluate(self.contract,self.candidate,self.db)

    def test_lead_e0_pass_is_verified_but_does_not_auto_promote(self):
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        self.assertFalse(out["integration_ready"])
        self.assertEqual(out["blocked_required_stages"],["context_packing"])
        checks=out["stages"][0]["checks"]
        self.assertTrue(next(x for x in checks if x["type"]=="lead_e0_pass")["ok"])
        self.assertTrue(next(x for x in checks if x["type"]=="replication_path")["ok"])

    def test_nonpass_lead_e0_breaks_contract_health(self):
        self.metrics.write_text(json.dumps({"schema":"test-lead-e0","pass":False}),encoding="utf-8")
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="lead_e0_missing_or_nonpass" for x in out["contract_errors"]))

    def test_retired_replication_backlog_breaks_contract_health(self):
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({
            "candidates":[{"id":"RTEST","status":"retired","reuse_plan":{"components":[]}}]
        }),encoding="utf-8")
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="replication_path_unavailable" for x in out["contract_errors"]))

    def test_missing_active_remediation_backlog_breaks_contract_health(self):
        self.base_contract["stages"]=[{
            "id":"ci_integrity",
            "required":True,
            "status":"ready_e1_runtime_hardening_blocked",
            "remediation_backlog_id":"RFIX",
        }]
        self.base_candidate["stage_pins"]={"ci_integrity":{"implementation":None}}
        self.write()
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="remediation_path_unavailable" for x in out["contract_errors"]))
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({
            "candidates":[{"id":"RFIX","status":"active","reuse_plan":{"components":[]}}]
        }),encoding="utf-8")
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        self.assertFalse(out["integration_ready"])

    def test_local_falsifier_must_remain_present_and_true(self):
        metric=self.gov/"lead_workspaces"/"ctx"/"falsifier.json"
        metric.write_text(json.dumps({"falsified":True}),encoding="utf-8")
        self.base_contract["stages"]=[{
            "id":"source_identity",
            "required":True,
            "status":"blocked_replacement_required",
            "local_falsifiers":[{
                "metrics":"governance/lead_workspaces/ctx/falsifier.json",
                "truth_key":"falsified","expected":True,
                "blocks":["bad.py"]
            }],
        }]
        self.base_candidate["stage_pins"]={"source_identity":{"implementation":None}}
        self.write()
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        metric.write_text(json.dumps({"falsified":False}),encoding="utf-8")
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="local_falsifier_missing_or_unmatched"
                            for x in out["contract_errors"]))

    def test_blocked_implementation_pin_is_rejected(self):
        self.base_contract["stages"]=[{
            "id":"source_identity_and_event_ledger",
            "required":True,
            "status":"blocked_replacement_required",
            "blocked_implementations":["stable_event_envelope_v5.py"],
        }]
        self.base_candidate["stage_pins"]={
            "source_identity_and_event_ledger":{
                "implementation":"stable_event_envelope_v5.py"
            }
        }
        self.write()
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="blocked_implementation_pinned" for x in out["contract_errors"]))


    def test_ready_stage_is_blocked_by_unready_dependency(self):
        self.base_contract["stages"]=[
            {
                "id":"upstream",
                "required":True,
                "status":"blocked_no_e1",
            },
            {
                "id":"downstream",
                "required":True,
                "status":"ready_e1",
                "depends_on_stage":"upstream",
            },
        ]
        self.base_candidate["stage_pins"]={
            "upstream":{"implementation":None},
            "downstream":{"implementation":"synthetic-ready"},
        }
        self.write()
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        rows={x["id"]:x for x in out["stages"]}
        self.assertFalse(rows["upstream"]["ready"])
        self.assertFalse(rows["upstream"]["intrinsic_ready"])
        self.assertFalse(rows["downstream"]["ready"])
        self.assertTrue(rows["downstream"]["intrinsic_ready"])
        self.assertEqual(out["direct_blocked_required_stages"],["upstream"])
        self.assertEqual(out["dependency_only_blocked_required_stages"],["downstream"])
        dep=next(x for x in rows["downstream"]["checks"]
                 if x["type"]=="stage_dependency")
        self.assertFalse(dep["ok"])
        self.assertEqual(dep["actual"],"BLOCKED")

    def test_supporting_lead_e0_is_verified_and_can_break_contract_health(self):
        support=self.gov/"lead_workspaces"/"ctx"/"support.json"
        support.write_text(json.dumps({
            "schema":"test-supporting-e0","pass":True
        }),encoding="utf-8")
        self.base_contract["stages"]=[{
            "id":"context_packing",
            "required":True,
            "status":"ready_semantics_e1_integration_e0",
            "lead_e0":{
                "metrics":"governance/lead_workspaces/ctx/metrics.json",
                "expected_schema":"test-lead-e0",
            },
            "supporting_lead_e0":[{
                "name":"cross_layer",
                "metrics":"governance/lead_workspaces/ctx/support.json",
                "expected_schema":"test-supporting-e0",
            }],
        }]
        self.base_candidate["stage_pins"]={
            "context_packing":{"implementation":"synthetic"}
        }
        self.write()
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        check=next(x for x in out["stages"][0]["checks"]
                   if x["type"]=="supporting_lead_e0_pass")
        self.assertTrue(check["ok"])
        support.write_text(json.dumps({
            "schema":"test-supporting-e0","pass":False
        }),encoding="utf-8")
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="supporting_lead_e0_missing_or_nonpass"
                            for x in out["contract_errors"]))

    def _install_backlog_lease_tables(self):
        con=sqlite3.connect(self.db)
        con.executescript("""
        CREATE TABLE IF NOT EXISTS leases(
          lease_id TEXT PRIMARY KEY,
          state TEXT,
          backlog_id TEXT,
          claimed_at REAL,
          family TEXT,
          lineage TEXT,
          hypothesis TEXT
        );
        CREATE TABLE IF NOT EXISTS submissions(
          submission_id TEXT PRIMARY KEY,
          lease_id TEXT,
          evidence_label TEXT,
          decision TEXT,
          at REAL
        );
        """)
        con.commit()
        return con

    def test_ttl_expired_unsubmitted_replication_is_recoverable(self):
        row={
            "id":"RTEST","status":"active","family":"f","lineage":"l",
            "hypothesis":"h","reuse_plan":{"components":[]}
        }
        (self.gov/"RESEARCH_BACKLOG.json").write_text(
            json.dumps({"candidates":[row]}),encoding="utf-8")
        con=self._install_backlog_lease_tables()
        con.execute("""INSERT INTO leases
          (lease_id,state,backlog_id,claimed_at,family,lineage,hypothesis)
          VALUES(?,?,?,?,?,?,?)""",
          ("old","TTL_EXPIRED","RTEST",1.0,"f","l","h"))
        con.commit();con.close()
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        check=next(x for x in out["stages"][0]["checks"]
                   if x["type"]=="replication_path")
        self.assertTrue(check["ok"])
        self.assertEqual(check["actual"]["status"],"RECOVERABLE_INTERRUPTED")
        self.assertEqual(check["actual"]["recoverable_leases"],["old"])

    def test_adopt_scope_match_sees_active_recovery(self):
        row={
            "id":"RTEST","status":"active","family":"f","lineage":"l",
            "hypothesis":"h","reuse_plan":{"components":[]},
            "adopted_lease_id":"old","adopt_scope_match":True
        }
        (self.gov/"RESEARCH_BACKLOG.json").write_text(
            json.dumps({"candidates":[row]}),encoding="utf-8")
        con=self._install_backlog_lease_tables()
        con.execute("""INSERT INTO leases
          (lease_id,state,backlog_id,claimed_at,family,lineage,hypothesis)
          VALUES(?,?,?,?,?,?,?)""",
          ("old","TTL_EXPIRED","",1.0,"f","l","h"))
        con.execute("""INSERT INTO leases
          (lease_id,state,backlog_id,claimed_at,family,lineage,hypothesis)
          VALUES(?,?,?,?,?,?,?)""",
          ("new","ACTIVE","",2.0,"f","l","h"))
        con.commit();con.close()
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        check=next(x for x in out["stages"][0]["checks"]
                   if x["type"]=="replication_path")
        self.assertEqual(check["actual"]["status"],"IN_PROGRESS")
        self.assertTrue(any(x["lease_id"]=="new" and x["state"]=="ACTIVE"
                            for x in check["actual"]["leases"]))

    def test_closeout_backlog_must_match_direct_blocker_remediation(self):
        self.base_contract["stages"]=[{
            "id":"blocked_stage",
            "required":True,
            "status":"blocked_no_e1",
            "remediation_backlog_id":"RNEW",
        }]
        self.base_candidate["stage_pins"]={"blocked_stage":{"implementation":None}}
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps({
            "candidates":[
                {"id":"RNEW","status":"active","reuse_plan":{"components":[]}},
                {"id":"ROLD","status":"retired","reuse_plan":{"components":[]}},
            ],
            "phase_policy":{
                "closeout_mode":True,
                "closeout_required_backlog":["ROLD"]
            }
        }),encoding="utf-8")
        self.write()
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertFalse(out["closeout_sync"]["ok"])
        self.assertEqual(out["closeout_sync"]["expected"],["RNEW"])
        self.assertEqual(out["closeout_sync"]["actual"],["ROLD"])
        self.assertTrue(any(x["type"]=="closeout_backlog_drift"
                            for x in out["contract_errors"]))

        data=json.loads((self.gov/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        data["phase_policy"]["closeout_required_backlog"]=["RNEW"]
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps(data),encoding="utf-8")
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        self.assertTrue(out["closeout_sync"]["ok"])

    def test_later_phase_closeout_backlog_does_not_reopen_p1(self):
        data=json.loads((self.gov/"RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        data["phase_policy"]={
            "closeout_mode":True,
            "current_phase":"E2_PILOT",
            "closeout_required_backlog":["R48","R49"],
        }
        (self.gov/"RESEARCH_BACKLOG.json").write_text(json.dumps(data),encoding="utf-8")
        out=self.run_doctor()
        self.assertTrue(out["contract_healthy"])
        self.assertTrue(out["closeout_sync"]["ok"])
        self.assertFalse(out["closeout_sync"]["checked"])
        self.assertTrue(out["closeout_sync"]["ignored_later_phase_backlog"])
        self.assertEqual(out["closeout_sync"]["scope"],"LATER_PHASE_BACKLOG_IGNORED_FOR_P1")
        self.assertEqual(out["closeout_sync"]["actual"],["R48","R49"])
        self.assertFalse(any(x.get("type")=="closeout_backlog_drift"
                             for x in out["contract_errors"]))

    def test_dependency_cycle_breaks_contract_health(self):
        self.base_contract["stages"]=[
            {"id":"a","required":True,"status":"ready_e1","depends_on_stage":"b"},
            {"id":"b","required":True,"status":"ready_e1","depends_on_stage":"a"},
        ]
        self.base_candidate["stage_pins"]={
            "a":{"implementation":"a"},
            "b":{"implementation":"b"},
        }
        self.write()
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        cycles=[x for x in out["contract_errors"] if x["type"]=="dependency_cycle"]
        self.assertTrue(cycles)
        self.assertEqual(cycles[0]["cycle"][0],cycles[0]["cycle"][-1])

    def test_missing_dependency_breaks_contract_health(self):
        self.base_contract["stages"]=[{
            "id":"downstream",
            "required":True,
            "status":"ready_e1",
            "depends_on_stage":"does_not_exist",
        }]
        self.base_candidate["stage_pins"]={
            "downstream":{"implementation":"synthetic-ready"}
        }
        self.write()
        out=self.run_doctor()
        self.assertFalse(out["contract_healthy"])
        self.assertTrue(any(x["type"]=="dependency_stage_missing"
                            for x in out["contract_errors"]))


if __name__=="__main__":
    unittest.main(verbosity=2)
