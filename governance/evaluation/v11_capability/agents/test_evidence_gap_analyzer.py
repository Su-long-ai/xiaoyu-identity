# -*- coding: utf-8 -*-
import unittest
from evidence_gap_analyzer import validate_gap_plan,repair_gap_plan
class GapAnalyzerTests(unittest.TestCase):
 def c(self):
  return {"answer_requirements":[{"id":"o1"},{"id":"o2"}],
          "preconditions":[{"id":"p1","required":True}]}
 def test_valid_gap(self):
  x=validate_gap_plan(self.c(),{"coverage":[
    {"node_id":"o1","status":"supported","reason":"x"},
    {"node_id":"o2","status":"missing","reason":"y"},
    {"node_id":"p1","status":"unbound","reason":"z"}],
    "search_queries":[{"node_ids":["o2","p1"],"query":"Alice meeting date","anchor_reason":"Alice visible"}],"stop":False})
  self.assertEqual(len(x["search_queries"]),1)
 def test_all_nodes_required(self):
  with self.assertRaisesRegex(ValueError,"coverage_missing"):
   validate_gap_plan(self.c(),{"coverage":[
    {"node_id":"o1","status":"missing"},
    {"node_id":"o2","status":"supported"}],"search_queries":[],"stop":False})
 def test_repair_missing_required_precondition_is_conservative(self):
  c=self.c()
  raw={"coverage":[
    {"node_id":"o1","status":"supported","reason":"x"},
    {"node_id":"o2","status":"supported","reason":"y"}],
    "search_queries":[],"stop":True}
  fixed=repair_gap_plan("question",c,raw)
  self.assertFalse(fixed["stop"])
  p1=next(x for x in fixed["coverage"] if x["node_id"]=="p1")
  self.assertEqual(p1["status"],"missing")
  self.assertTrue(fixed["_deterministic_repair"]["repaired"])

 def test_optional_precondition_may_appear_without_being_required(self):
  c={"answer_requirements":[{"id":"o1"}],
     "preconditions":[
       {"id":"p1","required":True},
       {"id":"p2","required":False}]}
  x=validate_gap_plan(c,{"coverage":[
    {"node_id":"o1","status":"supported"},
    {"node_id":"p1","status":"supported"},
    {"node_id":"p2","status":"missing"}],
    "search_queries":[],"stop":True})
  self.assertTrue(x["stop"])

 def test_stop_cannot_search(self):
  c={"answer_requirements":[{"id":"o1"}],"preconditions":[]}
  with self.assertRaisesRegex(ValueError,"stop_with"):
   validate_gap_plan(c,{"coverage":[{"node_id":"o1","status":"supported"}],
     "search_queries":[{"node_ids":["o1"],"query":"x"}],"stop":True})
if __name__=="__main__":unittest.main()
