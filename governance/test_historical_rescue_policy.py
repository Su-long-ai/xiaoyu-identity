import json
import unittest
from pathlib import Path

from governance.control import Governance, GovernanceError

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"


class HistoricalRescuePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((GOV / "policy.json").read_text(encoding="utf-8"))
        self.obj = Governance.__new__(Governance)
        self.obj.policy = self.policy
        self.effective = float(self.policy["historical_rescue"]["effective_after_epoch"])

    def manifest(self, **extra):
        m = {
            "evidence_label": "NONPASS",
            "scientific_outcome": "NEGATIVE",
            "promotion_evidence_status": "VALID",
            "scientific_falsifier_observed": True,
            "delta": 0.2,
        }
        m.update(extra)
        return m

    def test_new_nonpass_requires_scope(self):
        lease = {"claimed_at": self.effective + 1}
        with self.assertRaises(GovernanceError):
            self.obj._validate_scientific_evidence_separation(lease, self.manifest())

    def test_new_nonpass_requires_preserved_signal(self):
        lease = {"claimed_at": self.effective + 1}
        with self.assertRaises(GovernanceError):
            self.obj._validate_scientific_evidence_separation(
                lease, self.manifest(falsification_scope="EXACT_HYPOTHESIS_ONLY")
            )

    def test_new_nonpass_with_scope_and_signal_passes(self):
        lease = {"claimed_at": self.effective + 1}
        self.obj._validate_scientific_evidence_separation(
            lease,
            self.manifest(
                falsification_scope="EXACT_HYPOTHESIS_ONLY",
                preserved_signal="Positive recall delta remains valid; only the exact commit rule failed.",
            ),
        )

    def test_pre_policy_history_not_rewritten(self):
        lease = {"claimed_at": self.effective - 1}
        self.obj._validate_scientific_evidence_separation(lease, self.manifest())

    def test_queue_and_first_rescue_are_nonblocking(self):
        q = json.loads((GOV / "HISTORICAL_RESCUE_QUEUE_20261101.json").read_text(encoding="utf-8"))
        self.assertTrue(q["historical_results_are_immutable"])
        self.assertFalse(q["rc_v8_scope_expansion"])
        self.assertGreaterEqual(q["summary"]["pending_rescue_review"], 1)
        b = json.loads((GOV / "RESEARCH_BACKLOG.json").read_text(encoding="utf-8"))
        r = next(x for x in b["candidates"] if x.get("id") == "RESCUE01")
        self.assertEqual(r["destination"], "RC-v8.1_or_RC-v9")
        self.assertTrue(r["historical_rescue"])
        self.assertEqual(r["priority"], 50)
        self.assertIn("non-authoritative L0 proposal", r["hypothesis"])
        self.assertFalse(b["phase_policy"]["historical_rescue"]["preempts_rc_v8_release_blockers"])


if __name__ == "__main__":
    unittest.main()
