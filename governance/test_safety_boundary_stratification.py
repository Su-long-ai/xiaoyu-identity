import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"


class SafetyBoundaryStratificationTests(unittest.TestCase):
    def test_policy_layers_and_zero_tolerance_boundary(self):
        p = json.loads((GOV / "SAFETY_BOUNDARY_STRATIFICATION_20261101.json").read_text(encoding="utf-8"))
        self.assertEqual(p["status"], "ACTIVE")
        layers = {x["id"]: x for x in p["layers"]}
        self.assertEqual(layers["L0_PROPOSAL"]["authority"], "NON_AUTHORITATIVE")
        self.assertEqual(layers["L1_AUTHORITY_GATE"]["authority"], "AUTHORITATIVE_GATE")
        self.assertEqual(layers["L2_DURABLE_PRODUCT"]["authority"], "DURABLE_AUTHORITATIVE")
        self.assertIn("Nonzero prediction error", layers["L0_PROPOSAL"]["allowed"])
        self.assertIn("must be zero", layers["L1_AUTHORITY_GATE"]["hard_rule"])

    def test_policy_json_machine_contract(self):
        p = json.loads((GOV / "policy.json").read_text(encoding="utf-8"))
        s = p["safety_boundary_stratification"]
        self.assertTrue(s["enabled"])
        self.assertFalse(s["upstream_prediction_error_zero_required"])
        self.assertTrue(s["durable_authority_boundary_zero_unsafe_effect_required"])
        self.assertTrue(s["historical_frozen_results_immutable"])
        self.assertTrue(s["exact_hypothesis_negative_does_not_imply_family_killed"])

    def test_rc8m2_uses_end_to_end_boundary_falsifier(self):
        b = json.loads((GOV / "RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        x = next(x for x in b["candidates"] if x.get("id") == "RC8M2")
        self.assertIn("zero unsafe authoritative effects", x["hypothesis"])
        self.assertIn("Nonzero L0 proposal error alone is not a product-safety falsifier", x["falsifier"])
        self.assertEqual(x["safety_boundary_policy"], "governance/SAFETY_BOUNDARY_STRATIFICATION_20261101.json")

    def test_rc8_scope_preserves_history_but_changes_future_rule(self):
        r = json.loads((GOV / "RC_V8_INTEGRATION_SCOPE_FREEZE_20261101.json").read_text(encoding="utf-8"))
        b2 = next(x for x in r["release_blockers"] if x["id"] == "RC8-B2")
        self.assertIn("Upstream proposal error may be nonzero", b2["required_outcome"])
        self.assertIn("historical outcomes remain immutable", b2["rule"])
        self.assertIn("unsafe authoritative effects", b2["rule"])

    def test_role_prompts_reference_boundary_policy(self):
        paths = [
            GOV / "agent_prompts" / "LEAD_PROMPT.md",
            GOV / "agent_prompts" / "MAINLINE_RESEARCH_AGENT_PROMPT.md",
            GOV / "agent_prompts" / "DIVERGENT_RESEARCH_AGENT_PROMPT.md",
            GOV / "agent_prompts" / "INDEPENDENT_AUDITOR_PROMPT.md",
            GOV / "AUDIT_POLICY.md",
            GOV / "WORKER_ENTRY.md",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("Safety Boundary Stratification", text, str(path))
            self.assertIn("SAFETY_BOUNDARY_STRATIFICATION_20261101.json", text, str(path))


if __name__ == "__main__":
    unittest.main()
