# -*- coding: utf-8 -*-
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(r"D:\dsh-fish")
RUNNER_PATH=ROOT/"governance"/"confirmatory_frozen"/"HALUMEM_CONFIRMATORY_RUNNER.py"
JUDGE_PATH=ROOT/"governance"/"confirmatory_frozen"/"HALUMEM_CONFIRMATORY_JUDGE_LEDGER.py"

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
r=load("halu_confirm_runner_offline",RUNNER_PATH)
j=load("halu_confirm_judge_offline",JUDGE_PATH)

class HaluConfirmatoryRunnerOfflineTests(unittest.TestCase):
    def test_selective_parser_never_materializes_gold(self):
        u="00000000-0000-0000-0000-000000000001"
        row={
          "uuid":u,
          "persona_info":"SECRET_PERSONA_SENTINEL",
          "token_cost":"SECRET_COST_SENTINEL",
          "sessions":[{
            "memory_points":[{"memory_content":"SECRET_MEMORY_SENTINEL","is_update":"True"}],
            "dialogue":[
              {"role":"user","content":"I like tea.","timestamp":"SECRET_TS","dialogue_turn":9},
              {"role":"assistant","content":"Thanks.","timestamp":"SECRET_TS2","dialogue_turn":10}
            ],
            "questions":[{
              "question":"What do I like?",
              "answer":"SECRET_ANSWER_SENTINEL",
              "evidence":[{"memory_content":"SECRET_EVIDENCE_SENTINEL"}],
              "difficulty":"SECRET_DIFFICULTY",
              "question_type":"SECRET_QTYPE"
            }]
          }]
        }
        safe=r.safe_project_line(json.dumps(row,separators=(",",":")), {u})
        self.assertEqual(safe,{"uuid":u,"sessions":[{
          "dialogue":[{"role":"user","content":"I like tea."},{"role":"assistant","content":"Thanks."}],
          "questions":[{"question":"What do I like?"}]
        }]})
        blob=json.dumps(safe,ensure_ascii=False)
        for secret in ("SECRET_PERSONA_SENTINEL","SECRET_COST_SENTINEL","SECRET_MEMORY_SENTINEL",
                       "SECRET_ANSWER_SENTINEL","SECRET_EVIDENCE_SENTINEL","SECRET_DIFFICULTY",
                       "SECRET_QTYPE","SECRET_TS"):
            self.assertNotIn(secret,blob)
        for key in r.FORBIDDEN_PREDICTION_KEYS:
            self.assertNotIn('"'+key+'"',blob)

    def test_unselected_record_skips_sessions(self):
        row='{"uuid":"u0","sessions":[{"memory_points":["SECRET"],"dialogue":[],"questions":[]}]}'
        self.assertIsNone(r.safe_project_line(row,{"other"}))

    def test_sessions_before_uuid_fails_closed(self):
        row='{"sessions":[],"uuid":"u0"}'
        with self.assertRaises(r.RunnerError):
            r.safe_project_line(row,{"u0"})

    def test_exact_r52_closure(self):
        got=r.verify_r52_closure()
        self.assertEqual(got["r52_composition_candidate_v8.py"],r.EXPECTED_R52["r52_composition_candidate_v8.py"])
        self.assertEqual(r.structural.prompt_sha256(),r.EXPECTED_V5_PROMPT)
        self.assertEqual(r.structural.schema_sha256(),r.EXPECTED_V5_SCHEMA)

    def test_promotion_path_has_no_fixture_or_auto_confirm_call(self):
        src=RUNNER_PATH.read_text("utf-8")
        self.assertNotIn("._fixture_projection(",src)
        self.assertNotIn("comp.confirm(",src)
        self.assertIn("destructive_pending_actions",src)

    def test_dynamic_case_requires_frozen_uuid_prefix(self):
        full="a"*64
        m={"tracks":{"halumem_semantic_projection":{
          "scope":"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
          "allowed_uuid_hashes":[full],"variants":["m","l"],
          "max_session_index":999,"max_turn_index":999
        }}}
        meta=r.gate.validate_semantic_case(m,"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
                                           "hm-c-m-aaaaaaaaaaaa-s2-t7")
        self.assertEqual(meta["uuid_hash"],full)
        with self.assertRaises(Exception):
            r.gate.validate_semantic_case(m,"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
                                          "hm-c-m-bbbbbbbbbbbb-s2-t7")


    def test_semantic_receipt_coordinated_tamper_rejected_by_durable_gateway(self):
        manifest={"tracks":{"halumem_semantic_projection":{
          "scope":"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1"
        }}}
        messages=[{"role":"system","content":"s"},{"role":"user","content":"u"}]
        durable_text='{"outputs":[]}'
        durable={
          "status":"COMMITTED","budget_scope":"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
          "call_id":"api-durable","response_text":durable_text,
          "response_sha256":__import__("hashlib").sha256(durable_text.encode()).hexdigest(),
        }
        old_recover=r._recover_budget_case
        try:
            r._recover_budget_case=lambda case_id:dict(durable)
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/"receipt.json"
                req_sha=r.stable(messages);msha=r.sha_file(r.MANIFEST)
                valid={
                  "schema":"xiaoyu-e2-halumem-confirmatory-semantic-receipt-v2",
                  "case_id":"hm-c-m-aaaaaaaaaaaa-s0-t0","call_id":"api-durable",
                  "budget_scope":"proxy:xiaoyu:e2_halumem_confirmatory_semantic_v1",
                  "response_text":durable_text,"response_sha256":durable["response_sha256"],
                  "request_messages_sha256":req_sha,"manifest_sha256":msha,
                }
                p.write_text(json.dumps(valid),encoding="utf-8")
                self.assertEqual(r._validate_local_semantic_receipt(
                    manifest,valid["case_id"],messages,p)["response_text"],durable_text)
                bad=dict(valid);bad["response_text"]='{"outputs":[{"status":"evil"}]}'
                bad["response_sha256"]=__import__("hashlib").sha256(bad["response_text"].encode()).hexdigest()
                p.write_text(json.dumps(bad),encoding="utf-8")
                with self.assertRaisesRegex(r.RunnerError,"binding drift|durable gateway"):
                    r._validate_local_semantic_receipt(manifest,bad["case_id"],messages,p)
        finally:
            r._recover_budget_case=old_recover

    def test_existing_prediction_seal_revalidates_transitive_bindings(self):
        old_seal=r.SEAL;old_material=r._current_prediction_seal_material
        try:
            with tempfile.TemporaryDirectory() as td:
                r.SEAL=Path(td)/"PREDICTION_SEAL.json"
                files=[{"path":"x.json","sha256":"a"*64}]
                health={"COMMITTED":3}
                r._current_prediction_seal_material=lambda:(files,health)
                valid={
                  "schema":"xiaoyu-halumem-confirmatory-prediction-seal-v1",
                  "stage":"seal_predictions","sealed":True,
                  "runner_sha256":r.sha_file(Path(r.__file__)),
                  "manifest_sha256":r.sha_file(r.MANIFEST),
                  "r52_entrypoint_sha256":r.EXPECTED_R52["r52_composition_candidate_v8.py"],
                  "split_manifest_sha256":r.sha_file(r.SPLIT),
                  "prediction_files":files,"prediction_count":36,
                  "semantic_ledger_status":health,"gold_fields_read_before_seal":0,
                  "confirmatory_gold_scoring_allowed":False,"sealed_at_epoch":1.0,
                }
                r.SEAL.write_text(json.dumps(valid),encoding="utf-8")
                self.assertTrue(r._validate_prediction_seal({})["sealed"])
                bad=dict(valid);bad["prediction_files"]=[]
                r.SEAL.write_text(json.dumps(bad),encoding="utf-8")
                with self.assertRaisesRegex(r.RunnerError,"prediction seal transitive"):
                    r._validate_prediction_seal({})
        finally:
            r.SEAL=old_seal;r._current_prediction_seal_material=old_material

    def test_existing_calibration_requires_current_seal_and_durable_judge_receipts(self):
        old_result=r.CALIBRATION_RESULT;old_seal=r.SEAL;old_judge=r._judge_receipt
        try:
            with tempfile.TemporaryDirectory() as td:
                r.CALIBRATION_RESULT=Path(td)/"JUDGE_CALIBRATION_RESULT.json"
                r.SEAL=Path(td)/"PREDICTION_SEAL.json";r.SEAL.write_text("seal",encoding="utf-8")
                cal=json.loads((r.FROZEN/"HALUMEM_JUDGE_CALIBRATION_V1.json").read_text("utf-8"))
                receipts=[]
                for i in range(12):
                    receipts.append({"prompt_sha256":f"{i:064x}",
                                     "binding_sha256":r.sha_file(r.FROZEN/"HALUMEM_JUDGE_BINDING.json"),
                                     "model":"gpt-4o","response_json_sha256":f"{100+i:064x}"})
                r._judge_receipt=lambda p:next(dict(x) for x in receipts if x["prompt_sha256"]==p)
                rows=[{"id":x["id"],"metric":x["metric"],"ok":True,
                       "expected":x["expected"],"got":dict(x["expected"])} for x in cal["cases"]]
                valid={
                  "schema":"xiaoyu-halumem-judge-calibration-result-v2",
                  "binding_sha256":r.sha_file(r.FROZEN/"HALUMEM_JUDGE_BINDING.json"),
                  "calibration_sha256":r.sha_file(r.FROZEN/"HALUMEM_JUDGE_CALIBRATION_V1.json"),
                  "prediction_seal_sha256":r.sha_file(r.SEAL),
                  "passed":12,"total":12,"required":12,"rows":rows,"judge_receipts":receipts,
                }
                r.CALIBRATION_RESULT.write_text(json.dumps(valid),encoding="utf-8")
                self.assertEqual(r._validate_calibration_result(cal)["passed"],12)
                bad=dict(valid);bad["prediction_seal_sha256"]="0"*64
                r.CALIBRATION_RESULT.write_text(json.dumps(bad),encoding="utf-8")
                with self.assertRaisesRegex(r.RunnerError,"prediction_seal_sha256"):
                    r._validate_calibration_result(cal)
        finally:
            r.CALIBRATION_RESULT=old_result;r.SEAL=old_seal;r._judge_receipt=old_judge

    def test_snapshot_search_is_session_snapshot_only(self):
        snap=[{"text":"Favorite drink is tea."},{"text":"Lives in Seattle."}]
        got=r._snapshot_search("favorite drink coffee",snap,10)
        self.assertEqual(got[0],"Favorite drink is tea.")
        self.assertNotIn("future memory",got)

    def test_official_json_block_parser(self):
        obj=j._parse_json_block("prefix\n```json\n{\"score\":\"2\"}\n```\n")
        self.assertEqual(obj,{"score":"2"})
        with self.assertRaises(Exception):
            j._parse_json_block('{"score":"2"}')

if __name__=="__main__":
    unittest.main()
