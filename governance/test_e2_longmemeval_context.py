# -*- coding: utf-8 -*-
import copy
import json
import unittest

import e2_longmemeval_context as c
import e2_pilot_runner as r


class TestE2LongMemEvalContext(unittest.TestCase):
    def synthetic(self):
        return {
          "question_id":"synthetic-q",
          "question_type":"single-session-user",
          "question":"commute",
          "question_date":"2023/05/30 (Tue) 20:36",
          "answer":"45 minutes each way",
          "answer_session_ids":["dup"],
          "haystack_dates":["2023/05/20 (Sat) 01:00","2023/05/21 (Sun) 01:00"],
          "haystack_session_ids":["dup","dup"],
          "haystack_sessions":[
            [
              {"role":"user","content":"My daily commute takes 45 minutes each way."},
              {"role":"assistant","content":"Thanks, I will remember your commute."},
            ],
            [
              {"role":"user","content":"I listen to audiobooks during my commute."},
              {"role":"assistant","content":"Your commute is one hour each way."},
            ],
          ],
        }

    def test_duplicate_session_id_is_source_unique_and_authority_preserved(self):
        payload,diag=c.build_payload_from_record(0,self.synthetic())
        self.assertEqual(payload["id"],"lme-a-000")
        self.assertTrue(diag["docs_indexed"]>=4)
        ids=[x["id"] for x in payload["context"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(any(x["authority"]=="user_history" for x in payload["context"]))
        self.assertTrue(any(x["authority"]=="conversation_history" for x in payload["context"]))
        self.assertTrue(all(x["lifecycle"]=="active" for x in payload["context"]))

    def test_payload_is_deterministic_and_gold_never_enters_payload(self):
        a,_=c.build_payload_from_record(0,self.synthetic())
        b,_=c.build_payload_from_record(0,self.synthetic())
        self.assertEqual(c.json.dumps(a,ensure_ascii=False,sort_keys=True),
                         c.json.dumps(b,ensure_ascii=False,sort_keys=True))
        encoded=json.dumps(a,ensure_ascii=False).lower()
        self.assertNotIn('"answer"',encoded)
        self.assertNotIn("answer_session_ids",encoded)
        self.assertNotIn("45 minutes each way",a["question"].lower())
        self.assertTrue(any("45 minutes each way" in x["text"].lower()
                            for x in a["context"]))

    def test_real_frozen_case_payload_is_accepted_but_manual_context_edit_is_rejected(self):
        manifest=json.loads(r.MANIFEST.read_text(encoding="utf-8"))
        payload,_=c.build_payload(0)
        spec,messages,_prefix=r.validate_payload(
            manifest,"longmemeval_answer","lme-a-000",payload)
        self.assertEqual(spec["execution_status"],"READY")
        self.assertEqual(messages[-1]["role"],"user")
        bad=copy.deepcopy(payload)
        bad["context"][0]["text"]="MANUAL CONTEXT DRIFT"
        with self.assertRaisesRegex(r.RunnerError,"differs from frozen deterministic"):
            r.validate_payload(manifest,"longmemeval_answer","lme-a-000",bad)

    def test_halumem_tracks_are_explicitly_held(self):
        manifest=json.loads(r.MANIFEST.read_text(encoding="utf-8"))
        for track in ("halumem_extract","halumem_qa"):
            with self.assertRaisesRegex(r.RunnerError,"not executable"):
                r.track_spec(manifest,track)


if __name__=="__main__":
    unittest.main()
