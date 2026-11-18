from __future__ import annotations

import unittest

from governance.implementation_reuse_gate import affected_areas, validate


POLICY = {
    "allowed_modes": [
        "reuse",
        "extend",
        "custom_policy",
        "legacy_compat",
        "falsification",
    ],
    "blocked_component_lifecycles": ["hold", "deprecated"],
    "unclassified_new_file_guard": {
        "prefixes": ["xiaoyu/runtime/"],
        "extensions": [".py"],
    },
    "areas": {
        "memory_retrieval": {
            "paths": [
                "xiaoyu/core/memory.py",
                "xiaoyu/runtime/retrieval.py",
            ],
            "required_component_kinds": ["stdlib_search", "embedding"],
        }
    },
}

CATALOG = {
    "components": [
        {
            "id": "sqlite_fts5",
            "kind": "stdlib_search",
            "lifecycle": "adopt",
            "source": {"type": "stdlib"},
        },
        {
            "id": "internal_only",
            "kind": "project_core",
            "lifecycle": "adopt",
            "source": {"type": "internal"},
        },
        {
            "id": "blocked_old",
            "kind": "embedding",
            "lifecycle": "deprecated",
            "source": {"type": "external_package"},
        },
        {
            "id": "voice_only",
            "kind": "voice_runtime",
            "lifecycle": "adopt",
            "source": {"type": "external_package"},
        },
    ]
}


def decision(entry):
    return [
        (
            "governance/implementation_reuse_decisions/test.json",
            {
                "schema": "xiaoyu-product-reuse-decision-v1",
                "change_id": "test-change",
                "areas": [entry],
            },
        )
    ]


class ProductReuseGateTests(unittest.TestCase):
    def test_authority_only_change_does_not_trigger(self):
        changed = ["xiaoyu/core/temporal.py"]
        self.assertEqual(affected_areas(changed, POLICY), {})
        self.assertEqual(
            validate(
                changed_files=changed,
                decision_payloads=[],
                policy=POLICY,
                catalog=CATALOG,
            ),
            [],
        )

    def test_new_unclassified_runtime_file_is_blocked(self):
        errors = validate(
            changed_files=["xiaoyu/runtime/new_search_engine.py"],
            new_files=["xiaoyu/runtime/new_search_engine.py"],
            decision_payloads=[],
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any("not classified" in value for value in errors)
        )

    def test_new_core_authority_file_is_not_blanket_blocked(self):
        errors = validate(
            changed_files=["xiaoyu/core/new_authority.py"],
            new_files=["xiaoyu/core/new_authority.py"],
            decision_payloads=[],
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertEqual(errors, [])

    def test_new_mapped_runtime_file_can_pass_with_reuse_decision(self):
        errors = validate(
            changed_files=["xiaoyu/runtime/retrieval.py"],
            new_files=["xiaoyu/runtime/retrieval.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "reuse",
                    "components": ["sqlite_fts5"],
                    "gap": "",
                    "no_new_infrastructure": True,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertEqual(errors, [])

    def test_commodity_change_without_decision_fails(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=[],
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any("without a reuse decision" in value for value in errors)
        )

    def test_direct_reuse_passes(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "reuse",
                    "components": ["sqlite_fts5"],
                    "gap": "",
                    "no_new_infrastructure": True,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertEqual(errors, [])

    def test_custom_policy_requires_bounded_gap_and_surface(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "custom_policy",
                    "components": ["sqlite_fts5"],
                    "gap": "too short",
                    "no_new_infrastructure": True,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any("gap of at least 40" in value for value in errors)
        )
        self.assertTrue(
            any("bounded custom_surface" in value for value in errors)
        )

    def test_custom_policy_with_external_substrate_passes(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "custom_policy",
                    "components": ["sqlite_fts5"],
                    "gap": (
                        "XiaoYu must retain audience admissibility and erasure "
                        "freshness before ranking results."
                    ),
                    "no_new_infrastructure": True,
                    "custom_surface": [
                        "audience/erasure admissibility filter"
                    ],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertEqual(errors, [])

    def test_internal_component_alone_is_not_enough(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "custom_policy",
                    "components": ["internal_only"],
                    "gap": (
                        "XiaoYu-specific policy is required but commodity "
                        "search must still consider mature reuse."
                    ),
                    "no_new_infrastructure": True,
                    "custom_surface": ["authority filter"],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any(
                "mature external/stdlib component" in value
                for value in errors
            )
        )

    def test_unrelated_external_component_does_not_satisfy_area(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "reuse",
                    "components": ["voice_only"],
                    "gap": "",
                    "no_new_infrastructure": True,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any("required kinds" in value for value in errors)
        )

    def test_deprecated_component_is_blocked(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "reuse",
                    "components": ["blocked_old"],
                    "gap": "",
                    "no_new_infrastructure": True,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any("blocked for new product use" in value for value in errors)
        )

    def test_unknown_component_is_blocked(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "reuse",
                    "components": ["made_up_library"],
                    "gap": "",
                    "no_new_infrastructure": True,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any("unknown component" in value for value in errors)
        )

    def test_new_infrastructure_is_never_implicit(self):
        errors = validate(
            changed_files=["xiaoyu/core/memory.py"],
            decision_payloads=decision(
                {
                    "area": "memory_retrieval",
                    "mode": "reuse",
                    "components": ["sqlite_fts5"],
                    "gap": "",
                    "no_new_infrastructure": False,
                    "custom_surface": [],
                }
            ),
            policy=POLICY,
            catalog=CATALOG,
        )
        self.assertTrue(
            any(
                "no_new_infrastructure must be true" in value
                for value in errors
            )
        )


if __name__ == "__main__":
    unittest.main()
