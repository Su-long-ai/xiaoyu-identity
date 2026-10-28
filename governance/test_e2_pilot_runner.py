# -*- coding: utf-8 -*-
import json
import unittest

import e2_pilot_runner as r


class TestE2PilotRunnerPayloads(unittest.TestCase):
    def setUp(self):
        self.prefix=[{"role":"system","content":"fixed"}]
        self.prefix_sha=r.sha_bytes(r.canon(self.prefix).encode("utf-8"))
        self.manifest={"tracks":{
          "lme":{
            "case_ids":["lme-a-001"],
            "invariant_prefix_messages":self.prefix,
            "invariant_prefix_sha256":self.prefix_sha,
            "max_completion_tokens":512,
            "response_format":{"type":"json_object"},
            "dynamic_payload_contract":{
              "encoding":"r18_single_case_compact_json_v1",
              "required_keys":["id","context","question"],
              "allowed_keys":["id","context","question"],
              "user_prefix":"逐项回答以下独立案例：\n",
              "container":"single-item-json-array"
            }
          },
          "extract":{
            "case_ids":["hm-m-i-u-1-2"],
            "invariant_prefix_messages":self.prefix,
            "invariant_prefix_sha256":self.prefix_sha,
            "max_completion_tokens":512,
            "response_format":{"type":"json_object"},
            "dynamic_payload_contract":{
              "encoding":"r35_single_target_message_compact_json_v1",
              "required_keys":["current_state","context_messages","target_message","slots"],
              "allowed_keys":["current_state","context_messages","target_message","slots"],
              "target_message_required_keys":["message_index","role","text"],
              "target_message_role":"user",
              "container":"json-object"
            }
          }
        }}

    def test_r18_encoding_reuses_accepted_single_case_shape(self):
        payload={"id":"lme-a-001","context":[{"id":"m1","text":"x"}],"question":"q"}
        spec,messages,prefix=r.validate_payload(self.manifest,"lme","lme-a-001",payload)
        expected="逐项回答以下独立案例：\n"+json.dumps(
            [payload],ensure_ascii=False,separators=(",",":"))
        self.assertEqual(messages[-1],{"role":"user","content":expected})
        self.assertEqual(prefix,self.prefix_sha)
        self.assertEqual(r.request_fingerprint(spec,messages),
                         r.request_fingerprint(spec,messages))

    def test_r35_encoding_is_one_target_user_message(self):
        payload={
          "current_state":{"音乐":"爵士乐"},
          "context_messages":[],
          "target_message":{"message_index":7,"role":"user","text":"我现在喜欢古典乐"},
          "slots":["音乐"],
        }
        _,messages,_=r.validate_payload(
            self.manifest,"extract","hm-m-i-u-1-2",payload)
        body=json.loads(messages[-1]["content"])
        self.assertEqual(list(body),[
            "current_state","context_messages","target_message","slots"])
        self.assertEqual(body["target_message"]["role"],"user")

    def test_prefrozen_offline_payload_hash_is_enforced(self):
        payload={"id":"lme-a-001","context":[{"id":"m1","text":"x"}],"question":"q"}
        self.manifest["tracks"]["lme"]["offline_input_freeze"]={
            "payload_sha256_by_case":{
                "lme-a-001":r.sha_bytes(r.canon(payload).encode("utf-8"))
            }
        }
        r.validate_payload(self.manifest,"lme","lme-a-001",payload)
        bad={"id":"lme-a-001","context":[{"id":"m1","text":"changed"}],"question":"q"}
        with self.assertRaisesRegex(r.RunnerError,"differs from frozen offline input"):
            r.validate_payload(self.manifest,"lme","lme-a-001",bad)

    def test_gold_fields_fail_before_provider(self):
        payload={"id":"lme-a-001","context":[],"question":"q","answer":"gold"}
        with self.assertRaisesRegex(r.RunnerError,"gold/answer-only"):
            r.validate_payload(self.manifest,"lme","lme-a-001",payload)

    def test_nonfrozen_keys_and_wrong_case_fail(self):
        with self.assertRaisesRegex(r.RunnerError,"outside frozen"):
            r.validate_payload(
              self.manifest,"lme","confirmatory-1",
              {"id":"confirmatory-1","context":[],"question":"q"})
        with self.assertRaisesRegex(r.RunnerError,"non-frozen keys"):
            r.validate_payload(
              self.manifest,"lme","lme-a-001",
              {"id":"lme-a-001","context":[],"question":"q","meta":"x"})

    def test_extract_role_and_shape_fail_closed(self):
        base={
          "current_state":{},"context_messages":[],
          "target_message":{"message_index":0,"role":"assistant","text":"x"},
          "slots":["音乐"],
        }
        with self.assertRaisesRegex(r.RunnerError,"frozen user role"):
            r.validate_payload(self.manifest,"extract","hm-m-i-u-1-2",base)
        bad=dict(base)
        bad["target_message"]={"message_index":0,"role":"user"}
        with self.assertRaisesRegex(r.RunnerError,"missing required keys"):
            r.validate_payload(self.manifest,"extract","hm-m-i-u-1-2",bad)


if __name__=="__main__":
    unittest.main()
