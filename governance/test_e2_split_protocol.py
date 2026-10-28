# -*- coding: utf-8 -*-
"""Anti-peeking split/protocol regressions. Local metadata only."""
import hashlib,json,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent

class E2SplitProtocolTests(unittest.TestCase):
    def setUp(self):
        self.split_path=HERE/"E2_SPLIT_MANIFEST.json"
        self.pilot_path=HERE/"E2_PROSPECTIVE_PROTOCOL_CANDIDATE.json"
        self.confirm_path=HERE/"E2_CONFIRMATORY_PROTOCOL_CANDIDATE.json"
        self.split=json.loads(self.split_path.read_text(encoding="utf-8"))
        self.pilot=json.loads(self.pilot_path.read_text(encoding="utf-8"))
        self.confirm=json.loads(self.confirm_path.read_text(encoding="utf-8"))
        self.sha=hashlib.sha256(self.split_path.read_bytes()).hexdigest()

    def test_longmemeval_seen_cases_are_pilot_and_holdout_is_exact_complement(self):
        l=self.split["longmemeval"]
        expected=(list(range(20))+list(range(70,75))+list(range(132,137))+
                  list(range(233,238))+list(range(366,371))+
                  list(range(444,449))+[499])
        self.assertEqual(l["pilot_indices"],expected)
        self.assertEqual(l["pilot_count"],46)
        self.assertEqual(l["confirmatory_count"],454)
        self.assertFalse(set(l["pilot_indices"]) & set(l["confirmatory_indices"]))
        self.assertEqual(sorted(l["pilot_indices"]+l["confirmatory_indices"]),list(range(500)))

    def test_halumem_split_is_user_level_and_shared_across_lengths(self):
        h=self.split["halumem"]
        self.assertTrue(h["uuid_sets_identical_across_medium_long"])
        self.assertEqual(h["pilot_user_count"],2)
        self.assertEqual(h["confirmatory_user_count"],18)
        self.assertFalse(set(h["pilot_uuids"]) & set(h["confirmatory_uuids"]))
        self.assertEqual(len(set(h["pilot_uuids"]+h["confirmatory_uuids"])),20)

    def test_pilot_is_nonpromotional_and_binds_split(self):
        self.assertEqual(self.pilot["schema"],"xiaoyu-e2-pilot-protocol-v2")
        self.assertEqual(self.pilot["protocol_role"],"NONPROMOTIONAL_PILOT")
        self.assertEqual(self.pilot["claim_eligibility"],"NONE")
        self.assertFalse(self.pilot["scope"]["confirmatory_calls_allowed"])
        self.assertEqual(self.pilot["split_manifest"]["sha256"],self.sha)
        self.assertFalse(self.pilot["execution_rules"]["pilot_results_may_support_e2_claim"])

    def test_confirmatory_holdout_is_fixed_but_thresholds_remain_unset(self):
        self.assertEqual(self.confirm["status"],"BLOCKED_UNTIL_PILOT_COMPLETE")
        self.assertEqual(self.confirm["split_manifest"]["sha256"],self.sha)
        self.assertTrue(self.confirm["holdout"]["longmemeval"]["untouched_required"])
        self.assertTrue(self.confirm["holdout"]["halumem"]["untouched_required"])
        self.assertEqual(self.confirm["quantitative_thresholds"]["status"],
                         "UNSET_UNTIL_PILOT_COMPLETE")
        self.assertIsNone(self.confirm["quantitative_thresholds"]["longmemeval"])
        self.assertIsNone(self.confirm["quantitative_thresholds"]["halumem"])
        self.assertTrue(self.confirm["execution_rules"]["pilot_cases_forbidden"])

    def test_frozen_pilot_record_must_match_if_present(self):
        record=HERE/"E2_PROTOCOL_FREEZE_RECORD.json"
        status=self.pilot["status"]
        self.assertIn(status,("DRAFT_PRE_FREEZE","FROZEN_BEFORE_EXECUTION"))
        if record.exists():
            r=json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(status,"FROZEN_BEFORE_EXECUTION")
            self.assertEqual(r["protocol_sha256"],
                             hashlib.sha256(self.pilot_path.read_bytes()).hexdigest())

if __name__=="__main__":
    unittest.main(verbosity=2)
