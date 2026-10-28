# -*- coding: utf-8 -*-
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path

import e2_runtime_efficiency as m


class TestE2RuntimeEfficiency(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        g=self.root/"governance";g.mkdir()
        rp={
          "schema":"xiaoyu-e2-runtime-efficiency-policy-v1",
          "status":"ACTIVE_POSTLAUNCH_AMENDMENT",
          "legacy_cache_target":{"status_for_longmemeval":"NOT_APPLICABLE_AS_RUNTIME_GATE"},
          "primary_runtime_metrics":["cache_miss_tokens_per_committed_case"],
          "longmemeval_cache_geometry":{"classification":"STRUCTURALLY_LOW_CACHE_REUSE"},
          "rules":{
            "current_pilot_prompt_mutation_for_cache_forbidden":True,
            "batching_in_current_pilot_forbidden":True
          }
        }
        rpp=g/"E2_RUNTIME_EFFICIENCY_POLICY.json"
        rpp.write_text(json.dumps(rp),encoding="utf-8")
        sha=hashlib.sha256(rpp.read_bytes()).hexdigest()
        policy={
          "e2_transition":{"runtime_efficiency_policy_sha256":sha},
          "budget":{"paid_research":{"pricing_cny_per_million":{
            "cache_hit":{"off_peak":0.02,"peak":0.04},
            "cache_miss":{"off_peak":1.0,"peak":2.0},
            "output":{"off_peak":4.0,"peak":8.0}
          }}}
        }
        (g/"policy.json").write_text(json.dumps(policy),encoding="utf-8")
        con=sqlite3.connect(g/"research_api_usage.sqlite3")
        con.execute("""create table calls(
          created_at real,phase text,status text,budget_scope text,case_id text,
          prompt_tokens integer,completion_tokens integer,actual_tokens integer,
          cache_hit_tokens integer,cache_miss_tokens integer)""")
        scope="proxy:xiaoyu:e2_lme_answer_pilot"
        con.executemany("insert into calls values(?,?,?,?,?,?,?,?,?,?)",[
          (1.0,"benchmark","COMMITTED",scope,"a",100,20,120,0,100),
          (2.0,"benchmark","COMMITTED",scope,"b",200,30,230,0,200),
          (3.0,"smoke","COMMITTED",scope,"ignored",999,99,1098,0,999),
        ])
        con.commit();con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_reports_per_case_miss_total_and_cost(self):
        out=m.evaluate(self.root)
        l=out["longmemeval"]
        self.assertEqual(l["committed_cases"],2)
        self.assertEqual(l["cache_miss_tokens_per_case"],150.0)
        self.assertEqual(l["total_tokens_per_case"],175.0)
        self.assertEqual(l["whole_prompt_cache_hit_rate_observational"],0.0)
        self.assertAlmostEqual(l["off_peak_cny_per_case"],0.00025,9)
        self.assertFalse(out["scientific_protocol_changed"])
        self.assertEqual(out["legacy_95pct_cache_target_for_longmemeval"],
                         "NOT_APPLICABLE_AS_RUNTIME_GATE")

    def test_runtime_policy_hash_drift_fails_closed(self):
        p=self.root/"governance"/"E2_RUNTIME_EFFICIENCY_POLICY.json"
        p.write_text(p.read_text()+"\n",encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"policy hash drift"):
            m.evaluate(self.root)


if __name__=="__main__":
    unittest.main()
