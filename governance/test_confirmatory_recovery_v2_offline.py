#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance";CAND=GOV/"confirmatory_recovery_candidate"

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class RecoveryV2OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recovery=load_module("recovery_v2_test",CAND/"confirmatory_unknown_reconciliation_v2.py")
        cls.halu=load_module("halu_recovery_v2_test",CAND/"HALUMEM_CONFIRMATORY_RUNNER_V2.py")
        cls.manifest=json.loads((GOV/"E2_CONFIRMATORY_RECOVERY_V2_MANIFEST_CANDIDATE.json").read_text("utf-8"))

    def test_manifest_prefreeze_and_track_disposition(self):
        self.assertEqual(self.manifest["status"],"PREFREEZE_RECOVERY_V2_CANDIDATE")
        self.assertTrue(self.manifest["track_disposition"]["halumem"]["recovery_execution_candidate"])
        self.assertFalse(self.manifest["track_disposition"]["longmemeval"]["recovery_execution_candidate"])
        self.assertFalse(self.manifest["common_reconciliation"]["provider_retry"])
        self.assertFalse(self.manifest["common_reconciliation"]["durable_unknown_status_mutated"])

    def test_exact_support_and_runner_bindings_load_prefreeze(self):
        r,base=self.recovery.load_recovery("halumem",CAND/"HALUMEM_CONFIRMATORY_RUNNER_V2.py",require_authorized=False)
        self.assertEqual(r["generation_id"],"e2-confirmatory-recovery-v2-20261029")
        self.assertEqual(len((base.get("tracks") or {}).get("longmemeval_answer",{}).get("allowed_case_ids") or []),454)

    def test_authorization_reflects_current_recovery_final_freeze(self):
        r,base=self.recovery.load_recovery(
            "halumem",CAND/"HALUMEM_CONFIRMATORY_RUNNER_V2.py",require_authorized=True)
        self.assertEqual(r["generation_id"],"e2-confirmatory-recovery-v2-20261029")
        self.assertTrue((GOV/"E2_CONFIRMATORY_RECOVERY_V2_FINAL_FREEZE_RECORD.json").is_file())
        self.assertEqual(len((base.get("tracks") or {}).get("longmemeval_answer",{}).get("allowed_case_ids") or []),454)
        with self.assertRaisesRegex(Exception,"not eligible"):
            self.recovery.load_recovery("longmemeval",CAND/"LME_CONFIRMATORY_RUNNER_V2.py",require_authorized=True)

    def test_legacy_unknown_exact_and_no_response(self):
        rows=self.manifest["legacy_unknowns"]
        self.assertEqual(len(rows),1)
        x=rows[0]
        self.assertEqual(x["case_id"],"hm-c-m-8e00ab0ec2dd-s4-t24")
        db=sqlite3.connect(str(GOV/"research_api_usage.sqlite3"));db.row_factory=sqlite3.Row
        try:r=db.execute("select * from calls where case_id=?",(x["case_id"],)).fetchone()
        finally:db.close()
        self.assertEqual(r["status"],"UNKNOWN")
        self.assertEqual(r["call_id"],x["call_id"])
        self.assertEqual(r["error_class"],x["error_class"])
        self.assertIsNone(r["response_text"]);self.assertIsNone(r["response_sha256"])

    def test_sqlite_checkpoint_restore_discards_uncommitted_work(self):
        with tempfile.TemporaryDirectory(dir=str(GOV)) as td:
            d=Path(td);work=d/"work.sqlite3";cp=d/"checkpoint.sqlite3"
            con=sqlite3.connect(str(work));con.execute("create table t(v integer)");con.execute("insert into t values(1)");con.commit();con.close()
            self.halu._sqlite_backup(work,cp)
            con=sqlite3.connect(str(work));con.execute("update t set v=999");con.commit();con.close()
            self.halu._restore_checkpoint(cp,work)
            con=sqlite3.connect(str(work))
            try:v=con.execute("select v from t").fetchone()[0]
            finally:con.close()
            self.assertEqual(v,1)

    def test_checkpoint_contract_is_bound_in_manifest(self):
        c=self.manifest["halumem_recovery_seed"]["checkpoint_contract"]
        self.assertTrue(c["immutable_sqlite_checkpoint_per_completed_session"])
        self.assertTrue(c["progress_references_exact_checkpoint_sha256"])
        self.assertTrue(c["restart_restores_last_referenced_checkpoint"])
        self.assertTrue(c["unreferenced_future_checkpoint_ignored"])

    def test_legacy_committed_receipt_index_is_exact_68(self):
        spec=self.manifest["legacy_committed_receipts_index"]
        p=ROOT/spec["path"]
        self.assertTrue(p.is_file())
        self.assertEqual(spec["count"],68)
        idx=json.loads(p.read_text("utf-8"))
        self.assertEqual(idx["count"],68)
        self.assertEqual(len(idx["receipts"]),68)
        for row in idx["receipts"]:
            rp=ROOT/row["path"]
            self.assertTrue(rp.is_file())
            import hashlib
            self.assertEqual(hashlib.sha256(rp.read_bytes()).hexdigest(),row["sha256"])
            old=json.loads(rp.read_text("utf-8"))
            self.assertEqual(old["case_id"],row["case_id"])
            self.assertEqual(old["call_id"],row["call_id"])
            self.assertEqual(old["request_messages_sha256"],row["request_messages_sha256"])
            self.assertEqual(old["response_sha256"],row["response_sha256"])

    def test_legacy_committed_reuse_rejects_request_drift(self):
        row=self.manifest["legacy_committed_receipts_index"]
        idx=json.loads((ROOT/row["path"]).read_text("utf-8"))
        case_id=idx["receipts"][0]["case_id"]
        durable=self.recovery.recover_case(case_id)
        with self.assertRaisesRegex(Exception,"request_messages_sha256 drift"):
            self.halu._ensure_request_intent(case_id,[{"role":"user","content":"synthetic wrong request"}],durable)

    def test_new_request_intent_is_immutable_before_dispatch(self):
        old_runtime=self.halu.RUNTIME
        try:
            with tempfile.TemporaryDirectory(dir=str(GOV)) as td:
                self.halu.RUNTIME=Path(td)
                case_id="synthetic-recovery-v2-intent"
                msgs=[{"role":"system","content":"a"},{"role":"user","content":"b"}]
                first=self.halu._ensure_request_intent(case_id,msgs,None)
                second=self.halu._ensure_request_intent(case_id,msgs,None)
                self.assertEqual(first,second)
                with self.assertRaisesRegex(Exception,"request intent drift"):
                    self.halu._ensure_request_intent(case_id,[{"role":"user","content":"changed"}],None)
        finally:
            self.halu.RUNTIME=old_runtime

if __name__=="__main__":unittest.main()
