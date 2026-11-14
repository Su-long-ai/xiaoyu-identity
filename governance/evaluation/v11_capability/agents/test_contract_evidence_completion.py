# -*- coding: utf-8 -*-
import unittest
from contract_evidence_completion import contract_queries,supplement_sources,supplement_gap_queries
class ContractEvidenceCompletionTests(unittest.TestCase):
 def test_queries_are_bounded(self):
  c={"answer_requirements":[
   {"question_span":"which person","requirement":"identify the person"},
   {"question_span":"what date","requirement":"identify the date"},
   {"question_span":"where","requirement":"identify place"}]}
  q=contract_queries("Question?",c)
  self.assertEqual(len(q),3)
 def test_gap_stop_preserves_current(self):
  def rank(q,docs):return docs,{}
  r=supplement_gap_queries({"stop":True,"search_queries":[]},[{"id":"b"}],["a"],rank)
  self.assertEqual(r["source_keys"],["a"]);self.assertFalse(r["triggered"])

 def test_existing_ids_are_not_readded(self):
  docs=[{"id":"a"},{"id":"b"},{"id":"c"},{"id":"d"}]
  def rank(q,docs):return docs,{}
  c={"answer_requirements":[{"question_span":"x","requirement":"x"}]}
  r=supplement_sources("q",c,docs,["a"],rank,max_extra=2,per_query=2)
  self.assertEqual(r["source_keys"],["a","b","c"])
  self.assertEqual(r["extra_source_keys"],["b","c"])
if __name__=="__main__":unittest.main()
