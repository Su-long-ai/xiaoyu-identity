import sys
import unittest
from datetime import date
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from api_cost_report import estimate, summarize, render

class TestCost(unittest.TestCase):
    def test_cached(self):
        self.assertEqual(estimate({"prompt_tokens":1000000,"cached_tokens":500000,"completion_tokens":1000000},{"unit":"tokens","tiers":[{"input":2,"cached":1,"output":3}]}),(4.5,4.5))
    def test_tiers(self):
        self.assertEqual(estimate({"prompt_tokens":1000000},{"unit":"tokens","tiers":[{"input":1,"output":2},{"input":3,"output":4}]}, aggregate=True),(1.0,3.0))
    def test_exact_per_call_tier(self):
        tariff={"unit":"tokens","tiers":[
            {"input":1,"cached":0.2,"output":2,"max_prompt_tokens":100},
            {"input":3,"cached":0.6,"output":4,"max_prompt_tokens":1000},
        ]}
        self.assertEqual(estimate({"prompt_tokens":50,"cached_tokens":10,"completion_tokens":10},tariff),(0.000062,0.000062))
        self.assertEqual(estimate({"prompt_tokens":500,"completion_tokens":10},tariff),(0.00154,0.00154))

    def test_unknown(self):
        self.assertIsNone(estimate({"prompt_chars":100},None))
        self.assertIsNone(estimate({"prompt_tokens":100,"prompt_chars":100},{"unit":"tokens","tiers":[{"input":1,"output":2}]}))
    def test_char_rate(self):
        self.assertEqual(estimate({"prompt_chars":1000000},{"unit":"characters","cny_per_million_chars":4}),(4.0,4.0))
        self.assertEqual(estimate({"prompt_chars":100},{"unit":"characters","cny_per_million_chars":100,"char_multiplier_min":1,"char_multiplier_max":2}),(0.01,0.02))
        self.assertIsNone(estimate({"prompt_chars":10,"prompt_tokens":20},{"unit":"characters","cny_per_million_chars":4}))
    def test_realtime_modal_range(self):
        tariff={"unit":"token_modal_range","input_min":1.5,"input_max":6,"output_min":4.5,"output_max":12}
        self.assertEqual(estimate({"prompt_tokens":1000000,"completion_tokens":1000000},tariff),(6.0,18.0))

    def test_no_double_count(self):
        b={"prompt_tokens":1000000,"total_tokens":1000000,"call_count":1}
        d={"daily_stats":{"2026-11-20":{"by_model":{"m":b,"app_start":b},"by_call_type":{"chat":b}}},"recent_records":[{"model":"m","pt":1000000,"type":"chat"}]}
        p={"models":{"m":{"unit":"tokens","tiers":[{"input":1,"output":2}]}}}
        totals,_,_,sample=summarize(d,p,date(2026,11,20))
        self.assertEqual(totals["今日"]["low"],1)
        self.assertEqual(totals["本月"]["calls"],1)
        self.assertEqual(sample["chat"]["low"],1)
        self.assertIn("非硬限额",render(d,dict(p,daily_budget_cny=1),date(2026,11,20)))
    def test_unknown_not_zero(self):
        d={"daily_stats":{"2026-11-20":{"by_model":{"unknown":{"total_tokens":100,"call_count":1}}}}}
        totals,*_=summarize(d,{},date(2026,11,20))
        self.assertEqual(totals["今日"]["unknown_calls"],1)
        self.assertEqual(totals["今日"]["no_usage_calls"],0)
        self.assertEqual(totals["今日"]["known_rows"],0)

    def test_zero_usage_is_separate_from_unpriced_usage(self):
        d={"daily_stats":{"2026-11-20":{"by_model":{
            "priced-but-empty":{"total_tokens":0,"prompt_chars":0,"call_count":3},
            "unknown":{"total_tokens":100,"call_count":2},
        }}}}
        totals,*_=summarize(d,{},date(2026,11,20))
        self.assertEqual(totals["今日"]["unknown_calls"],2)
        self.assertEqual(totals["今日"]["no_usage_calls"],3)
        page=render(d,{},date(2026,11,20))
        self.assertIn("无用量记录：3 次",page)
        self.assertIn("有用量但未计价：2 次",page)

if __name__=="__main__":
    unittest.main()
