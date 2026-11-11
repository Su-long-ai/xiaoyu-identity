# -*- coding: utf-8 -*-
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
RUNNER=HERE/"confirmatory_frozen"/"LME_CONFIRMATORY_RUNNER.py"

spec=importlib.util.spec_from_file_location("_lme_confirmatory_runner_test",RUNNER)
runner=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=runner
spec.loader.exec_module(runner)


def rec(si,mi,text,*,eid,when,role="user",authority="user_history",
        admissible_current=True,session_id=None,**extra):
    x={
      "session_index":si,"message_index":mi,
      "session_id":session_id or f"s{si}",
      "source_role":role,"authority":authority,
      "text":text,"admissible_current":admissible_current,
      "temporal_status":"current" if admissible_current else "historical",
      "evidence_id":eid,"effective_at":when,
    }
    x.update(extra)
    return x


class TestLMEConfirmatoryRunner(unittest.TestCase):
    def test_exact_components_verify(self):
        b,r48,r51,r50=runner.verify_and_load_components()
        self.assertEqual(b["components"]["R51"]["review"]["decision"],"ACCEPT_E1")
        self.assertTrue(hasattr(r48,"FTS5SessionRetriever"))
        self.assertTrue(hasattr(r51,"bind"))
        self.assertTrue(hasattr(r50,"consume"))

    def test_typed_latest_state_resolves_through_r50(self):
        case={
          "case_id":"synthetic-current-city",
          "question":"What is my current city?",
          "question_time":"2026-10-29T00:00:00+00:00",
          "records":[
            rec(0,0,"My city is Boston.",eid="e-old",
                when="2026-01-01T12:00:00+00:00"),
            rec(1,0,"My city is Seattle.",eid="e-new",
                when="2026-02-01T12:00:00+00:00"),
          ],
        }
        out=runner.plan_case(case)
        self.assertEqual(out["route"],"typed_r50")
        self.assertEqual(out["prediction"]["status"],"resolved")
        self.assertEqual(out["prediction"]["answer"],"Seattle")
        self.assertEqual(out["prediction"]["evidence_ids"],["e-new"])
        self.assertIsNone(out["model_messages"])

    def test_general_memory_lookup_routes_strict_model(self):
        case={
          "case_id":"synthetic-degree",
          "question":"What degree did I graduate with?",
          "records":[
            rec(0,0,"I graduated with a Business Administration degree.",
                eid="e1",when="2026-01-01T12:00:00+00:00")
          ],
        }
        out=runner.plan_case(case)
        self.assertEqual(out["route"],"strict_context_answer_model")
        self.assertIsNone(out["prediction"])
        self.assertEqual(out["model_messages"][-1]["role"],"user")
        raw=json.dumps(out["model_messages"],ensure_ascii=False)
        self.assertNotIn("question_type",raw)
        self.assertNotIn("answer_session_ids",raw)

    def test_missing_trusted_time_for_recognized_current_state_fails_closed(self):
        case={
          "case_id":"synthetic-current-no-time",
          "question":"What is my current city?",
          "records":[{
            "session_index":0,"message_index":0,"session_id":"s0",
            "source_role":"user","authority":"user_history",
            "text":"My city is Boston.","admissible_current":True,
            "temporal_status":"current","evidence_id":"e1"
          }],
        }
        out=runner.plan_case(case)
        self.assertEqual(out["route"],"fail_closed")
        self.assertEqual(out["prediction"]["status"],"unknown")
        self.assertIsNone(out["model_messages"])

    def test_assistant_cannot_satisfy_current_user_state(self):
        case={
          "case_id":"synthetic-assistant-current",
          "question":"What is my current city?",
          "records":[
            rec(0,0,"My city is Paris.",eid="a1",
                when="2026-01-01T12:00:00+00:00",
                role="assistant",authority="conversation_history")
          ],
        }
        out=runner.plan_case(case)
        self.assertEqual(out["route"],"fail_closed")
        self.assertEqual(out["prediction"]["status"],"unknown")

    def test_forbidden_evaluator_metadata_rejected_anywhere(self):
        case={
          "case_id":"bad",
          "question":"What degree did I graduate with?",
          "records":[
            rec(0,0,"I graduated with a Business Administration degree.",
                eid="e1",when="2026-01-01T12:00:00+00:00",
                answer="Business Administration")
          ],
        }
        with self.assertRaisesRegex(runner.RunnerError,"forbidden evaluator"):
            runner.plan_case(case)

    def test_timezone_less_time_rejected_at_boundary(self):
        case={
          "case_id":"bad-time",
          "question":"What degree did I graduate with?",
          "records":[
            rec(0,0,"I graduated with a Business Administration degree.",
                eid="e1",when="2026-01-01T12:00:00")
          ],
        }
        with self.assertRaisesRegex(runner.RunnerError,"timezone-aware"):
            runner.plan_case(case)

    def test_execute_is_hard_blocked_in_prefreeze_before_provider(self):
        case={
          "case_id":"lme-c-020",
          "question":"What degree did I graduate with?",
          "records":[
            rec(0,0,"I graduated with a Business Administration degree.",
                eid="e1",when="2026-01-01T12:00:00+00:00")
          ],
        }
        with self.assertRaises(Exception):
            runner.execute_case(case)


    def test_local_provider_receipt_must_match_durable_gateway(self):
        messages=[{"role":"system","content":"s"},{"role":"user","content":"u"}]
        msha=__import__("hashlib").sha256(runner.canonical(messages).encode("utf-8")).hexdigest()
        durable={
          "status":"COMMITTED","budget_scope":"proxy:xiaoyu:e2_lme_confirmatory_v1",
          "call_id":"api-durable","response_text":"{\"results\":[]}",
          "response_sha256":__import__("hashlib").sha256(b'{"results":[]}').hexdigest(),
        }
        old_recover=runner._recover_budget_case
        try:
            runner._recover_budget_case=lambda case_id:dict(durable)
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/"provider.json"
                valid={
                  "schema":"xiaoyu-e2-lme-confirmatory-provider-receipt-v2",
                  "case_id":"lme-c-020","messages_sha256":msha,
                  "runner_sha256":runner.sha256(Path(runner.__file__)),
                  "budget_scope":"proxy:xiaoyu:e2_lme_confirmatory_v1",
                  "call_id":"api-durable","response_text":durable["response_text"],
                  "response_sha256":durable["response_sha256"],
                }
                p.write_text(json.dumps(valid),encoding="utf-8")
                self.assertEqual(
                    runner._validate_durable_provider_receipt("lme-c-020",msha,p)["response_text"],
                    durable["response_text"])
                tampered=dict(valid);tampered["response_text"]='{"results":[{"id":"evil"}]}'
                tampered["response_sha256"]=__import__("hashlib").sha256(tampered["response_text"].encode()).hexdigest()
                p.write_text(json.dumps(tampered),encoding="utf-8")
                with self.assertRaisesRegex(runner.RunnerError,"binding drift|durable gateway"):
                    runner._validate_durable_provider_receipt("lme-c-020",msha,p)
        finally:
            runner._recover_budget_case=old_recover

    def test_divergent_duplicate_evidence_id_rejected(self):
        case={
          "case_id":"dup",
          "question":"What degree did I graduate with?",
          "records":[
            rec(0,0,"alpha",eid="same",when="2026-01-01T00:00:00+00:00"),
            rec(1,0,"beta",eid="same",when="2026-01-02T00:00:00+00:00"),
          ],
        }
        with self.assertRaisesRegex(runner.RunnerError,"divergent duplicate evidence_id"):
            runner.plan_case(case)


if __name__=="__main__":
    unittest.main()
