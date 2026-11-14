# -*- coding: utf-8 -*-
import unittest
from answer_contract_mvp import validate_contract,validate_execution,render_execution

class AnswerContractMVPTests(unittest.TestCase):
 def contract(self):
  return {"history_need":"yes","task_type":"temporal","current_turn_facts":[],
    "answer_requirements":[
      {"id":"o1","question_span":"date","requirement":"give the date",
       "value_type":"date","expected_cardinality":None,"shared_binding":"event_e"},
      {"id":"o2","question_span":"time","requirement":"give the time",
       "value_type":"time","expected_cardinality":None,"shared_binding":"event_e"}],
    "operations":[{"op":"temporal_select","purpose":"same event"}],
    "verify_presupposition":False,"exhaustive_scope":False}
 def test_contract_requires_question_spans(self):
  q="What date and time was the authorization?"
  c=validate_contract(q,self.contract())
  self.assertEqual(len(c["answer_requirements"]),2)
 def test_invented_output_span_fails(self):
  c=self.contract();c["answer_requirements"][1]["question_span"]="location"
  with self.assertRaisesRegex(ValueError,"question_span"):
   validate_contract("What date and time was the authorization?",c)
 def test_cardinality_is_machine_checked(self):
  c={"history_need":"yes","task_type":"aggregation","current_turn_facts":[],
    "answer_requirements":[{"id":"o1","question_span":"four movements",
      "requirement":"list four movements","value_type":"list",
      "expected_cardinality":4,"shared_binding":None}],
    "operations":[{"op":"enumerate","purpose":"four items"}],
    "verify_presupposition":False,"exhaustive_scope":False}
  c=validate_contract("Which four movements were used?",c)
  e={"answers":[{"id":"o1","status":"supported","value":["a","b","c"],
      "evidence_ids":["s"],"answer_text":"a, b, c"}],"material_constraints":[],"unresolved":[]}
  self.assertFalse(validate_execution(c,e)["valid"])
 def test_material_state_precondition_is_validated(self):
  c=self.contract()
  c["preconditions"]=[{"id":"p1","kind":"material_current_state",
    "description":"Check relevant current health/location/dependent-care constraints",
    "affects_output_ids":["o1","o2"],"required":True}]
  out=validate_contract("What date and time was the authorization?",c)
  self.assertEqual(out["preconditions"][0]["id"],"p1")

 def test_cardinality_one_accepts_scalar(self):
  c={"history_need":"yes","task_type":"lookup","current_turn_facts":[],
    "answer_requirements":[{"id":"o1","question_span":"which person",
      "requirement":"identify person","value_type":"person",
      "expected_cardinality":1,"shared_binding":None}],
    "operations":[{"op":"lookup","purpose":"person"}],
    "verify_presupposition":False,"exhaustive_scope":False}
  c=validate_contract("which person was there?",c)
  e={"answers":[{"id":"o1","status":"supported","value":"Alice",
      "evidence_ids":["s1"],"answer_text":"Alice."}],"material_constraints":[],"unresolved":[]}
  self.assertTrue(validate_execution(c,e)["valid"])

 def test_deterministic_render_keeps_constraints(self):
  c=validate_contract("What date and time was the authorization?",self.contract())
  e={"answers":[
    {"id":"o1","status":"supported","value":"2026-11-01","evidence_ids":["s1"],"answer_text":"??? 2026-11-01?"},
    {"id":"o2","status":"supported","value":"13:00","evidence_ids":["s1"],"answer_text":"??? 13:00?"}],
    "material_constraints":[{"status":"supported","text":"????????????","evidence_ids":["s1"]}],
    "unresolved":[]}
  ck=validate_execution(c,e);self.assertTrue(ck["valid"])
  out=render_execution(c,ck)
  self.assertIn("2026-11-01",out);self.assertIn("13:00",out);self.assertIn("???",out)

if __name__=="__main__":unittest.main()
