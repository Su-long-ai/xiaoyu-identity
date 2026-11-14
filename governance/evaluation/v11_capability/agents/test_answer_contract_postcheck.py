# -*- coding: utf-8 -*-
import unittest
from answer_contract_postcheck import postcheck_execution,supported_numeric_from_reason

class PostcheckTests(unittest.TestCase):
    def base(self):
        return {
          "answer_requirements":[{"id":"o1","value_type":"text"}],
          "preconditions":[],
        }

    def test_unresolved_event_binding_blocks_supported_override(self):
        c=self.base()
        c["preconditions"]=[{"id":"p1","kind":"event_binding","required":True,
                              "affects_output_ids":["o1"]}]
        gap={"coverage":[{"node_id":"p1","status":"unbound","reason":"not linked"}]}
        checked={"answers":{"o1":{"status":"supported","value":"Ethiopian"}},
                 "unresolved":["event link not confirmed"]}
        self.assertEqual(
          postcheck_execution(c,gap,checked),
          ["unresolved_required_event_binding:p1:unbound"])

    def test_material_current_state_does_not_block_useful_constraint(self):
        c=self.base()
        c["preconditions"]=[{"id":"p1","kind":"material_current_state","required":True,
                              "affects_output_ids":["o1"]}]
        gap={"coverage":[{"node_id":"p1","status":"unbound","reason":"current pain unknown"}]}
        checked={"answers":{"o1":{"status":"supported","value":"draft"}},
                 "unresolved":["current pain unknown"]}
        self.assertEqual(postcheck_execution(c,gap,checked),[])

    def test_supported_numeric_conflict_blocks(self):
        c={"answer_requirements":[{"id":"o1","value_type":"number"}],"preconditions":[]}
        gap={"coverage":[{"node_id":"o1","status":"supported",
          "reason":"Counting the columns yields a total of 8 columns."}]}
        checked={"answers":{"o1":{"status":"supported","value":9}},"unresolved":[]}
        self.assertEqual(postcheck_execution(c,gap,checked),
                         ["numeric_coverage_conflict:o1:9!=8"])

    def test_supported_numeric_match_passes(self):
        c={"answer_requirements":[{"id":"o1","value_type":"number"}],"preconditions":[]}
        gap={"coverage":[{"node_id":"o1","status":"supported",
          "reason":"The table contains 8 columns."}]}
        checked={"answers":{"o1":{"status":"supported","value":8}},"unresolved":[]}
        self.assertEqual(postcheck_execution(c,gap,checked),[])

    def test_ambiguous_numbers_do_not_create_a_veto(self):
        self.assertIsNone(supported_numeric_from_reason(
          "The old table has 7 columns and the revised table has 8 columns."))
        c={"answer_requirements":[{"id":"o1","value_type":"number"}],"preconditions":[]}
        gap={"coverage":[{"node_id":"o1","status":"supported",
          "reason":"The old table has 7 columns and the revised table has 8 columns."}]}
        checked={"answers":{"o1":{"status":"supported","value":8}},"unresolved":[]}
        self.assertEqual(postcheck_execution(c,gap,checked),[])

if __name__=="__main__": unittest.main()
