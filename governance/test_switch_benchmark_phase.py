# -*- coding: utf-8 -*-
import hashlib,json,tempfile,unittest,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
import switch_benchmark_phase as sb


class BenchmarkSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name);g=self.root/"governance";g.mkdir()
        self.policy=g/"policy.json"
        self.policy.write_text(json.dumps({"budget":{"paid_research":{
          "active_phase":"smoke","benchmark_unlocked":False}}}),encoding="utf-8")
        self.protocol=g/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
        self.protocol.write_text(json.dumps({
          "schema":"xiaoyu-e2-prospective-protocol-candidate-v1",
          "status":"FROZEN_BEFORE_EXECUTION"}),encoding="utf-8")
        psha=hashlib.sha256(self.protocol.read_bytes()).hexdigest()
        (g/"E2_PROTOCOL_FREEZE_RECORD.json").write_text(json.dumps({
          "schema":"xiaoyu-e2-protocol-freeze-record-v1",
          "protocol_sha256":psha,"phase_switch_performed":False}),encoding="utf-8")
        self.smoke={
          "smoke_exit_ready":True,"errors":[],"blockers":[],
          "paid_phase":{"phase_used_or_reserved_tokens":4500000,
                        "phase_remaining_tokens":500000,
                        "unknown_calls":5,"reserved_calls":0}
        }

    def tearDown(self):self.tmp.cleanup()

    def test_dry_preflight_allows_but_does_not_modify_policy(self):
        out=sb.preflight(self.root,smoke_result=self.smoke)
        self.assertTrue(out["switch_allowed"])
        p=json.loads(self.policy.read_text())
        self.assertEqual(p["budget"]["paid_research"]["active_phase"],"smoke")
        self.assertFalse(p["budget"]["paid_research"]["benchmark_unlocked"])

    def test_switch_changes_both_fields_and_records_nonclaim(self):
        out=sb.perform_switch(self.root,smoke_result=self.smoke)
        self.assertTrue(out["switched"])
        p=json.loads(self.policy.read_text())
        paid=p["budget"]["paid_research"]
        self.assertEqual(paid["active_phase"],"benchmark")
        self.assertTrue(paid["benchmark_unlocked"])
        self.assertFalse(paid["benchmark_unlock"]["e2_claim_allowed"])
        rec=json.loads((self.root/"governance"/"E2_PROTOCOL_FREEZE_RECORD.json").read_text())
        self.assertTrue(rec["phase_switch_performed"])
        self.assertTrue((self.root/"governance"/"BENCHMARK_PHASE_UNLOCK_RECORD.json").is_file())

    def test_hash_drift_blocks_switch(self):
        self.protocol.write_text(json.dumps({
          "schema":"xiaoyu-e2-prospective-protocol-candidate-v1",
          "status":"FROZEN_BEFORE_EXECUTION","mutated":True}),encoding="utf-8")
        out=sb.preflight(self.root,smoke_result=self.smoke)
        self.assertFalse(out["switch_allowed"])
        self.assertTrue(any(x["type"]=="freeze_record_protocol_hash_mismatch" for x in out["blockers"]))

    def test_reserved_call_blocks_switch(self):
        self.smoke["paid_phase"]["reserved_calls"]=1
        out=sb.preflight(self.root,smoke_result=self.smoke)
        self.assertFalse(out["switch_allowed"])
        self.assertTrue(any(x["type"]=="reserved_paid_calls_present" for x in out["blockers"]))


if __name__=="__main__":unittest.main(verbosity=2)
