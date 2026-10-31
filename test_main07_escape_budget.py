# -*- coding: utf-8 -*-
import json,unittest
import companion

class SerializedBudgetTests(unittest.TestCase):
    def test_escape_heavy_records_are_atomic_and_bound_to_visible_ids(self):
        events=[
          {"event_id":i,"kind":"conversation.user" if i%2==0 else "conversation.assistant","content":"\x00"*220}
          for i in range(1,13)
        ]
        rows,ids=companion.growth_evidence_batch(events,12)
        payload=json.dumps(rows,ensure_ascii=False)
        visible=[int(x["id"]) for x in json.loads(payload)]
        self.assertLessEqual(len(payload),7500)
        self.assertEqual(ids,visible)
        self.assertEqual(ids,[1,2,3,4,5])
        self.assertTrue(all(len(x["content"])==220 for x in rows))

    def test_short_records_keep_chronological_order(self):
        events=[
          {"event_id":i,"kind":"conversation.user","content":f"event-{i}"}
          for i in range(20,26)
        ]
        rows,ids=companion.growth_evidence_batch(events,12)
        self.assertEqual(ids,list(range(20,26)))
        self.assertEqual([x["id"] for x in rows],ids)
        self.assertLessEqual(len(json.dumps(rows,ensure_ascii=False)),7500)

    def test_assistant_and_system_filtering_unchanged(self):
        events=[
          {"event_id":1,"kind":"system.synthetic","content":"ignore"},
          {"event_id":2,"kind":"conversation.user","content":"u"},
          {"event_id":3,"kind":"conversation.assistant","content":"a"},
          {"event_id":4,"kind":"pet.play","content":"play"},
        ]
        rows,ids=companion.growth_evidence_batch(events,12)
        self.assertEqual(ids,[2,3,4])
        self.assertTrue(all(x["kind"].startswith(("conversation.","pet.")) for x in rows))

if __name__=="__main__":
    unittest.main()
