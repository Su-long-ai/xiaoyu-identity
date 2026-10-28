# -*- coding: utf-8 -*-
import unittest

from research_api import ResearchBudgetError
from research_api_proxy import research_purpose_from_headers, enforce_allowed_proxy_scope


class TestProxyTagging(unittest.TestCase):
    def test_tagged_proxy_key_maps_to_scope(self):
        purpose,scope=research_purpose_from_headers(
            {"Authorization":"Bearer local-budget-proxy:hindsight.t19"},
            require_tag=True,
        )
        self.assertEqual(purpose,"proxy:hindsight.t19")
        self.assertEqual(scope,"proxy:hindsight.t19")

    def test_registered_tag_with_run_suffix_maps_to_unique_scope(self):
        purpose,scope=research_purpose_from_headers(
            {"Authorization":"Bearer local-budget-proxy:xiaoyu",
             "X-XiaoYu-Research-Run":"r29_replay_v1"},
            require_tag=True,
        )
        self.assertEqual(purpose,"proxy:xiaoyu:r29_replay_v1")
        self.assertEqual(scope,"proxy:xiaoyu:r29_replay_v1")
        enforce_allowed_proxy_scope(scope,{"allowed_proxy_tags":["xiaoyu"]})

    def test_invalid_run_suffix_is_rejected(self):
        with self.assertRaisesRegex(ResearchBudgetError,"Invalid X-XiaoYu-Research-Run"):
            research_purpose_from_headers(
                {"Authorization":"Bearer local-budget-proxy:xiaoyu",
                 "X-XiaoYu-Research-Run":"bad/run"},
                require_tag=True,
            )

    def test_missing_tag_rejected_when_required(self):
        with self.assertRaisesRegex(ResearchBudgetError,"Tagged local proxy key required"):
            research_purpose_from_headers(
                {"Authorization":"Bearer local-budget-proxy"},
                require_tag=True,
            )

    def test_invalid_tag_rejected(self):
        with self.assertRaisesRegex(ResearchBudgetError,"Invalid local proxy tag"):
            research_purpose_from_headers(
                {"Authorization":"Bearer local-budget-proxy:bad/tag"},
                require_tag=True,
            )

    def test_legacy_fallback_only_when_not_required(self):
        purpose,scope=research_purpose_from_headers({},require_tag=False)
        self.assertEqual(purpose,"OpenAI-compatible benchmark proxy")
        self.assertEqual(scope,"proxy:legacy-untagged")

    def test_registered_proxy_tag_allowed(self):
        enforce_allowed_proxy_scope(
            "proxy:hindsight", {"allowed_proxy_tags":["hindsight","mem0oss"]}
        )

    def test_unregistered_proxy_tag_rejected(self):
        with self.assertRaisesRegex(ResearchBudgetError,"not registered"):
            enforce_allowed_proxy_scope(
                "proxy:rotated-tag", {"allowed_proxy_tags":["hindsight","mem0oss"]}
            )


if __name__=="__main__":
    unittest.main()
