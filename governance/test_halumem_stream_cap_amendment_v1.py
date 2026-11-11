#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import copy,hashlib,importlib.util,json,sqlite3,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];GOV=ROOT/"governance"
if str(GOV) not in sys.path:sys.path.insert(0,str(GOV))
AMEND=GOV/"E2_CONFIRMATORY_HALUMEM_STREAM_CAP_AMENDMENT_V1.json"
SAFE=GOV/"lead_workspaces"/"halumem_stream_shape_20261029"/"HALUMEM_SAFE_STREAM_COUNTS.json"
GW=GOV/"confirmatory_stream_cap_gateway_v1.py"
BASE=GOV/"E2_CONFIRMATORY_EXECUTION_MANIFEST_CANDIDATE.json"

def load_mod(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class StreamCapAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a=json.loads(AMEND.read_text("utf-8"))
        cls.safe=json.loads(SAFE.read_text("utf-8"))
        cls.base=json.loads(BASE.read_text("utf-8"))
        cls.gw=load_mod("stream_cap_gateway_test",GW)

    def test_safe_count_control_and_exact_caps(self):
        self.assertTrue(self.safe["controls"]["pilot_control_pass"])
        self.assertEqual(self.safe["controls"]["pilot_user_turns_observed"],7900)
        c=self.safe["confirmatory"]
        self.assertEqual(c["streams"],36);self.assertEqual(c["total_semantic_calls_required"],75691)
        self.assertEqual(c["max_semantic_calls_per_stream"],2917)
        self.assertEqual(c["streams_over_old_768_cap"],36)
        d=self.a["cap_delta"]
        self.assertEqual((d["old_max_case_calls"],d["old_max_calls_per_stream"]),(10000,768))
        self.assertEqual((d["new_max_case_calls"],d["new_max_calls_per_stream"]),(75691,2917))

    def test_amended_meta_changes_only_two_numeric_caps(self):
        track=copy.deepcopy(self.base["tracks"]["halumem_semantic_projection"])
        meta={"track_name":"halumem_semantic_projection","case_id":"synthetic","stream_key":"m:abc","track":track}
        out=self.gw.amended_case_meta(meta,self.a)
        before=copy.deepcopy(track);after=copy.deepcopy(out["track"])
        before.pop("max_case_calls");before.pop("max_calls_per_stream")
        after.pop("max_case_calls");after.pop("max_calls_per_stream")
        self.assertEqual(before,after)
        self.assertEqual(out["track"]["max_case_calls"],75691)
        self.assertEqual(out["track"]["max_calls_per_stream"],2917)

    def test_non_halu_meta_is_byte_semantically_unchanged(self):
        meta={"track_name":"longmemeval_answer","case_id":"lme-c-000","stream_key":"lme","track":{"max_case_calls":454}}
        self.assertEqual(self.gw.amended_case_meta(meta,self.a),meta)

    def test_authorization_is_exact_or_fails_closed_on_live_gateway_drift(self):
        f=json.loads((GOV/"E2_CONFIRMATORY_FINAL_FREEZE_RECORD.json").read_text("utf-8"))
        binds=f["bindings"]
        live_api=hashlib.sha256((GOV/"research_api.py").read_bytes()).hexdigest()
        if live_api==binds["research_api_sha256"]:
            self.gw.load_authorized_amendment()
        else:
            with self.assertRaisesRegex(Exception,"base research_api drift"):
                self.gw.load_authorized_amendment()

    def test_frozen_cap_hit_boundary_records_no_next_ambiguous_call_at_freeze_time(self):
        b=self.a["cap_hit_boundary"]
        self.assertEqual(b["durable_status_counts"],{"COMMITTED":767,"UNKNOWN":1})
        self.assertFalse(b["next_case_request_intent"]["durable_row_exists"])
        self.assertFalse(b["next_case_request_intent"]["local_response_receipt_exists"])
        self.assertTrue(b["next_case_request_intent"]["case_id"])

    def test_parent_freeze_is_immutable_and_live_drift_is_fail_closed(self):
        f=json.loads((GOV/"E2_CONFIRMATORY_FINAL_FREEZE_RECORD.json").read_text("utf-8"))
        binds=f["bindings"]
        live_api=hashlib.sha256((GOV/"research_api.py").read_bytes()).hexdigest()
        live_proxy=hashlib.sha256((GOV/"research_api_proxy.py").read_bytes()).hexdigest()
        self.assertEqual(live_proxy,binds["research_api_proxy_sha256"])
        if live_api!=binds["research_api_sha256"]:
            with self.assertRaisesRegex(Exception,"base research_api drift"):
                self.gw.load_authorized_amendment()
        else:
            self.assertEqual(live_api,binds["research_api_sha256"])

if __name__=="__main__":unittest.main()
