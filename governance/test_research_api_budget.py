# -*- coding: utf-8 -*-
"""Offline tests for the capped XiaoYu paid-research API gateway."""
import json
import tempfile
import unittest
from pathlib import Path

from research_api import ResearchApiBudget,ResearchBudgetError,normalize_budget_scope,_PROXY_AUTH_SENTINEL

class TestResearchApiBudget(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"governance").mkdir()
        policy={
          "budget":{"max_paid_api_calls_per_day":2,"paid_research":{
            "enabled":True,"provider":"deepseek","active_phase":"smoke",
            "benchmark_unlocked":False,"max_total_tokens":10000,
            "smoke_max_tokens":5000,"benchmark_max_tokens":5000
          }}
        }
        (self.root/"governance"/"policy.json").write_text(json.dumps(policy),encoding="utf-8")
        (self.root/"provider.json").write_text(json.dumps({
          "provider":"deepseek","model":"deepseek-flash",
          "url":"https://api.deepseek.com/chat/completions","key_env":"DEEPSEEK_API_KEY"
        }),encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_uses_actual_provider_usage(self):
        def fake(config,messages,max_tokens,timeout):
            return "OK",{"prompt_tokens":20,"completion_tokens":3,"total_tokens":23}
        b=ResearchApiBudget(self.root,transport=fake)
        try:
            out,usage,cid=b.chat([{"role":"user","content":"hello"}],max_tokens=8,purpose="test")
            s=b.status()
            self.assertEqual(out,"OK")
            self.assertEqual(s["total_used_or_reserved_tokens"],23)
            self.assertEqual(s["calls_by_status"]["COMMITTED"],1)
        finally:b.close()

    def test_reservation_blocks_phase_overrun(self):
        b=ResearchApiBudget(self.root,transport=lambda *a,**k:("OK",{"total_tokens":1}))
        try:
            huge="x"*4500
            with self.assertRaises(ResearchBudgetError):
                b.reserve([{"role":"user","content":huge}],8,"too-large")
            self.assertEqual(b.status()["total_used_or_reserved_tokens"],0)
        finally:b.close()

    def test_unknown_failure_keeps_reservation_charged(self):
        def broken(*args,**kwargs):
            raise TimeoutError("synthetic")
        b=ResearchApiBudget(self.root,transport=broken)
        try:
            msgs=[{"role":"user","content":"hello"}]
            reserved=b.conservative_reservation(msgs,8)
            with self.assertRaises(TimeoutError):
                b.chat(msgs,max_tokens=8,purpose="failure")
            s=b.status()
            self.assertEqual(s["total_used_or_reserved_tokens"],reserved)
            self.assertEqual(s["calls_by_status"]["UNKNOWN"],1)
        finally:b.close()

    def test_rolling_daily_call_cap(self):
        def fake(config,messages,max_tokens,timeout):
            return "OK",{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}
        b=ResearchApiBudget(self.root,transport=fake)
        try:
            b.chat([{"role":"user","content":"a"}],max_tokens=2,purpose="one")
            b.chat([{"role":"user","content":"b"}],max_tokens=2,purpose="two")
            with self.assertRaises(ResearchBudgetError):
                b.chat([{"role":"user","content":"c"}],max_tokens=2,purpose="three")
        finally:b.close()

    def test_json_object_response_format_reaches_transport(self):
        seen={}
        def fake(config,messages,max_tokens,timeout):
            seen.update(config)
            return '{"ok":true}',{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}
        b=ResearchApiBudget(self.root,transport=fake)
        try:
            out,usage,cid=b.chat(
                [{"role":"user","content":"return json"}],
                max_tokens=16,purpose="json-test",
                response_format={"type":"json_object"})
            self.assertEqual(out,'{"ok":true}')
            self.assertEqual(seen.get("response_format"),{"type":"json_object"})
            self.assertEqual(b.status()["total_used_or_reserved_tokens"],5)
        finally:b.close()

    def test_unsupported_response_format_rejected_before_transport(self):
        called=[]
        def fake(*args,**kwargs):
            called.append(True)
            return "bad",{"total_tokens":1}
        b=ResearchApiBudget(self.root,transport=fake)
        try:
            with self.assertRaises(ResearchBudgetError):
                b.chat(
                    [{"role":"user","content":"x"}],
                    max_tokens=16,purpose="bad-json",
                    response_format={"type":"json_schema"})
            self.assertFalse(called)
            self.assertEqual(b.status()["total_used_or_reserved_tokens"],0)
        finally:b.close()

    def test_benchmark_phase_locked(self):
        b=ResearchApiBudget(self.root)
        try:
            with self.assertRaises(ResearchBudgetError):
                b.reserve([{"role":"user","content":"x"}],8,"bench",phase="benchmark")
        finally:b.close()

    def test_provider_mismatch_rejected_before_network(self):
        p=self.root/"provider.json"
        data=json.loads(p.read_text())
        data["provider"]="ollama";data["model"]="qwen3:8b"
        data["url"]="http://127.0.0.1:11434/v1/chat/completions";data["key_env"]=""
        p.write_text(json.dumps(data),encoding="utf-8")
        b=ResearchApiBudget(self.root)
        try:
            with self.assertRaises(ResearchBudgetError):
                b.reserve([{"role":"user","content":"x"}],8,"bad-provider")
        finally:b.close()


class TestRuntimeCostGuard(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"governance").mkdir()
        self.policy={
          "budget":{"max_paid_api_calls_per_day":1000,"paid_research":{
            "enabled":True,"provider":"deepseek","active_phase":"smoke",
            "benchmark_unlocked":False,"max_total_tokens":1000000,
            "smoke_max_tokens":500000,"benchmark_max_tokens":500000,
            "runtime_guard":{
              "enabled":True,"effective_after_epoch":0,
              "rolling_window_seconds":900,
              "scope_raw_token_cap":100000,
              "scope_cache_miss_cap":100000,
              "scope_output_token_cap":100000,
              "scope_call_cap":100,
              "max_single_reservation_tokens":100000,
              "block_benchmark_weekday_peak":False
            },
            "pricing_cny_per_million":{
              "cache_hit":{"off_peak":0.02,"peak":0.04},
              "cache_miss":{"off_peak":1.0,"peak":2.0},
              "output":{"off_peak":4.0,"peak":8.0}
            }
          }}
        }
        (self.root/"governance"/"policy.json").write_text(
            json.dumps(self.policy),encoding="utf-8")
        (self.root/"provider.json").write_text(json.dumps({
          "provider":"deepseek","model":"deepseek-flash",
          "url":"https://api.deepseek.com/chat/completions","key_env":"DEEPSEEK_API_KEY"
        }),encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_policy(self):
        (self.root/"governance"/"policy.json").write_text(
            json.dumps(self.policy),encoding="utf-8")

    @staticmethod
    def _fake(config,messages,max_tokens,timeout):
        return "OK",{
            "prompt_tokens":10,"completion_tokens":2,"total_tokens":12,
            "prompt_cache_hit_tokens":8,"prompt_cache_miss_tokens":2,
        }

    def test_numeric_case_purposes_share_scope(self):
        self.policy["budget"]["paid_research"]["runtime_guard"]["scope_call_cap"]=1
        self._write_policy()
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=self._fake)
        try:
            b.chat([{"role":"user","content":"a"}],max_tokens=2,purpose="HaluMem case 1")
            with self.assertRaisesRegex(ResearchBudgetError,"rolling call guard"):
                b.chat([{"role":"user","content":"b"}],max_tokens=2,purpose="HaluMem case 2")
            scopes=[r[0] for r in b.conn.execute("select budget_scope from calls")]
            self.assertEqual(scopes,["direct:halumem_case_#"])
        finally:b.close()

    def test_cache_miss_guard_blocks_next_call(self):
        self.policy["budget"]["paid_research"]["runtime_guard"]["scope_cache_miss_cap"]=2
        self._write_policy()
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=self._fake)
        try:
            b.chat([{"role":"user","content":"a"}],max_tokens=2,purpose="family 1")
            with self.assertRaisesRegex(ResearchBudgetError,"cache-miss guard"):
                b.chat([{"role":"user","content":"b"}],max_tokens=2,purpose="family 2")
        finally:b.close()

    def test_single_reservation_cap(self):
        self.policy["budget"]["paid_research"]["runtime_guard"]["max_single_reservation_tokens"]=1100
        self._write_policy()
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=self._fake)
        try:
            with self.assertRaisesRegex(ResearchBudgetError,"Single request reservation"):
                b.reserve([{"role":"user","content":"x"*100}],200,"oversized")
        finally:b.close()

    def test_report_has_cache_and_cost(self):
        self._write_policy()
        def fake(config,messages,max_tokens,timeout):
            return "OK",{
              "prompt_tokens":100,"completion_tokens":10,"total_tokens":110,
              "prompt_cache_hit_tokens":80,"prompt_cache_miss_tokens":20,
            }
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=fake)
        try:
            b.chat([{"role":"user","content":"a"}],max_tokens=10,purpose="report case 1")
            rep=b.report(since_hours=1,limit=10)
            self.assertEqual(rep["totals"]["hit"],80)
            self.assertEqual(rep["totals"]["miss"],20)
            self.assertAlmostEqual(rep["totals"]["cache_hit_rate"],0.8)
            self.assertTrue(rep["totals"]["cost_estimate"]["available"])
            self.assertEqual(rep["groups"][0]["scope"],"direct:report_case_#")
        finally:b.close()

    def test_benchmark_weekday_peak_block(self):
        from datetime import datetime,timezone,timedelta
        paid=self.policy["budget"]["paid_research"]
        paid["active_phase"]="benchmark"
        paid["benchmark_unlocked"]=True
        paid["runtime_guard"]["block_benchmark_weekday_peak"]=True
        self._write_policy()
        ts=datetime(2026,10,27,15,0,tzinfo=timezone(timedelta(hours=8))).timestamp()
        b=ResearchApiBudget(self.root,clock=lambda:ts,transport=self._fake)
        try:
            with self.assertRaisesRegex(ResearchBudgetError,"peak hours"):
                b.reserve([{"role":"user","content":"x"}],2,"bench",phase="benchmark")
        finally:b.close()

    def test_epoch_scope_cap_survives_rolling_window(self):
        guard=self.policy["budget"]["paid_research"]["runtime_guard"]
        guard["rolling_window_seconds"]=10
        guard["scope_raw_token_cap"]=100000
        guard["scope_epoch_raw_token_cap"]=1500
        self._write_policy()
        now=[10000.0]
        def fake_epoch(config,messages,max_tokens,timeout):
            return "OK",{
              "prompt_tokens":400,"completion_tokens":100,"total_tokens":500,
              "prompt_cache_hit_tokens":300,"prompt_cache_miss_tokens":100,
            }
        b=ResearchApiBudget(self.root,clock=lambda:now[0],transport=fake_epoch)
        try:
            b.chat([{"role":"user","content":"a"}],max_tokens=2,purpose="epoch case 1")
            now[0]+=20
            with self.assertRaisesRegex(ResearchBudgetError,"epoch raw-token guard"):
                b.chat([{"role":"user","content":"b"}],max_tokens=2,purpose="epoch case 2")
        finally:b.close()

    def test_require_proxy_tag_blocks_direct_before_reservation_and_transport(self):
        guard=self.policy["budget"]["paid_research"]["runtime_guard"]
        guard["require_proxy_tag"]=True
        self._write_policy()
        called=[]
        def fake(*args,**kwargs):
            called.append(True)
            return "BAD",{"total_tokens":1}
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=fake)
        try:
            before=b.conn.execute("select count(*) from calls").fetchone()[0]
            with self.assertRaisesRegex(ResearchBudgetError,"Direct paid research calls are forbidden"):
                b.chat([{"role":"user","content":"x"}],max_tokens=2,purpose="direct forbidden")
            after=b.conn.execute("select count(*) from calls").fetchone()[0]
            self.assertEqual(before,after)
            self.assertFalse(called)
        finally:b.close()

    def test_require_proxy_tag_rejects_spoofed_proxy_scope_without_proxy_capability(self):
        guard=self.policy["budget"]["paid_research"]["runtime_guard"]
        guard["require_proxy_tag"]=True
        self._write_policy()
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=self._fake)
        try:
            before=b.conn.execute("select count(*) from calls").fetchone()[0]
            with self.assertRaisesRegex(ResearchBudgetError,"authenticated local HTTP proxy"):
                b.chat(
                    [{"role":"user","content":"x"}],max_tokens=2,
                    purpose="proxy:xiaoyu:test",
                    budget_scope="proxy:xiaoyu")
            after=b.conn.execute("select count(*) from calls").fetchone()[0]
            self.assertEqual(before,after)
        finally:b.close()

    def test_authenticated_proxy_capability_records_http_proxy_origin(self):
        guard=self.policy["budget"]["paid_research"]["runtime_guard"]
        guard["require_proxy_tag"]=True
        self._write_policy()
        b=ResearchApiBudget(self.root,clock=lambda:10000,transport=self._fake)
        try:
            out,usage,cid=b.chat(
                [{"role":"user","content":"x"}],max_tokens=2,
                purpose="proxy:xiaoyu:test",
                budget_scope="proxy:xiaoyu:r29_test",
                _proxy_auth=_PROXY_AUTH_SENTINEL)
            self.assertEqual(out,"OK")
            row=b.conn.execute(
                "select budget_scope,status,gateway_origin from calls where call_id=?",(cid,)
            ).fetchone()
            self.assertEqual(row["budget_scope"],"proxy:xiaoyu:r29_test")
            self.assertEqual(row["status"],"COMMITTED")
            self.assertEqual(row["gateway_origin"],"http_proxy")
        finally:b.close()

    def test_normalize_budget_scope_collapses_case_numbers(self):
        self.assertEqual(
            normalize_budget_scope("HaluMem DF10 case 14"),
            normalize_budget_scope("HaluMem DF11 case 15"),
        )

if __name__=="__main__":
    unittest.main()
