# -*- coding: utf-8 -*-
import json, pathlib, shutil, tempfile, unittest
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from research_components.retrieval.api import authorized_documents, load_component, prepare_component, rank_component, ComponentContractError
from research_components.retrieval.run_local_e2e import answer_correct, normalize

class FastRetrievalContractTests(unittest.TestCase):
    def setUp(self):
        self.home=pathlib.Path(tempfile.mkdtemp(prefix="xy-ret-contract-"))
        self.store=IdentityStore(self.home)
        for i,text in enumerate(["Alice moved to Seattle.","Bob plays cello.","Cara likes tea."],1):
            ev=self.store.record("conversation.user","user",text,{"chat_time":f"2025-01-0{i}T00:00:00Z","source_key":f"x{i}"})
            self.store.add_memory(text,category="shared",priority=3,source_event=ev)
        self.bridge=ProductMemoryBridge(self.home,self.store);self.bridge.sync()
    def tearDown(self):
        try:self.bridge.close()
        except Exception:pass
        try:self.store.close()
        except Exception:pass
        shutil.rmtree(self.home,ignore_errors=True)
    def test_authorized_docs_only(self):
        docs=authorized_documents(self.bridge)
        self.assertEqual(3,len(docs))
        self.assertEqual({"x1","x2","x3"},{x["source_key"] for x in docs})
    def test_custom_component_cannot_invent_id(self):
        class Bad:
            component_id="bad"
            def prepare(self,docs):return docs
            def rank(self,q,*,state,limit,metadata):return ["not-authorized"]
        docs=authorized_documents(self.bridge)
        with self.assertRaises(ComponentContractError):
            rank_component(Bad(),docs,docs,"x",20,{})
    def test_formal_local_gate_120_integrity(self):
        p=pathlib.Path("research_components/retrieval/local_e2e_cases_v2_120.json")
        data=json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(data.get("shared_store"))
        self.assertEqual(20,int(data.get("context_cap")))
        self.assertEqual(120,len(data.get("cases",[])))
        expected={"multi_hop_2":30,"multi_hop_3":30,"temporal":24,"semantic_mismatch":16,"entity_collision":10,"boundary":10}
        got={}
        all_ids=[]
        for case in data["cases"]:
            got[case["family"]]=got.get(case["family"],0)+1
            mids={str(m["id"]) for m in case.get("memories",[])}
            self.assertTrue(set(map(str,case.get("required_ids",[]))).issubset(mids))
            all_ids.extend(mids)
        all_ids.extend(str(x["id"]) for x in data.get("distractors",[]))
        self.assertEqual(expected,got)
        self.assertEqual(len(all_ids),len(set(all_ids)))

    def test_local_dev_v3_shape(self):
        p=pathlib.Path("research_components/retrieval/local_dev_v3_240.json")
        obj=json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(obj["schema"],"xiaoyu-retrieval-fastlane-local-dev-v3")
        self.assertTrue(obj["shared_store"])
        self.assertEqual(obj["context_cap"],20)
        self.assertEqual(len(obj["cases"]),240)
        self.assertEqual(sum(obj["family_counts"].values()),240)
        expected={
            "single_hop_semantic":30,
            "multi_hop_2_varied":40,
            "multi_hop_3_varied":30,
            "temporal_current":30,
            "temporal_order":20,
            "alias_identity":20,
            "entity_collision":20,
            "semantic_paraphrase":20,
            "cross_language":15,
            "boundary_abstain":15,
        }
        self.assertEqual(obj["family_counts"],expected)
        ids=[d["id"] for d in obj["distractors"]]
        for c in obj["cases"]:
            mids=[m["id"] for m in c["memories"]]
            self.assertTrue(set(c["required_ids"]).issubset(set(mids)))
            ids.extend(mids)
        self.assertEqual(len(ids),len(set(ids)))

    def test_unicode_answer_normalization(self):
        self.assertEqual(normalize("\u4e0a\u6d77\u3002"),"\u4e0a\u6d77")
        self.assertTrue(answer_correct("\u73b0\u5728\u4f4f\u5728\u4e0a\u6d77\u3002",["\u4e0a\u6d77"]))
        self.assertTrue(answer_correct("I don't know.",["i don't know","unknown"]))

    def test_template_loads(self):
        c,_=load_component("research_components/retrieval/candidate_template.py")
        docs=authorized_documents(self.bridge);state=prepare_component(c,docs)
        out=rank_component(c,state,docs,"Seattle",20,{})
        self.assertTrue(out)
        self.assertLessEqual(len(out),20)

if __name__=="__main__":unittest.main()
