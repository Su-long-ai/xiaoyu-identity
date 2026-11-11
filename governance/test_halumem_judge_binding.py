# -*- coding: utf-8 -*-
import hashlib
import json
import os
import unittest
from pathlib import Path

GOV=Path(__file__).resolve().parent
CF=GOV/"confirmatory_frozen"

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class TestHaluMemJudgeBinding(unittest.TestCase):
    def setUp(self):
        self.binding=json.loads((CF/"HALUMEM_JUDGE_BINDING.json").read_text(encoding="utf-8"))
        self.cal=json.loads((CF/"HALUMEM_JUDGE_CALIBRATION_V1.json").read_text(encoding="utf-8"))
        self.impl=json.loads((GOV/"E2_CONFIRMATORY_IMPLEMENTATION_BINDINGS.json").read_text(encoding="utf-8"))

    def test_exact_qwen_config_and_no_substitution(self):
        self.assertEqual(self.binding["schema"],"xiaoyu-halumem-final-judge-binding-v2")
        self.assertEqual(self.binding["status"],"FROZEN_ALTERNATIVE_QWEN_CONFIRMATORY_BINDING")
        j=self.binding["judge"]
        self.assertEqual(j["provider"],"alibaba_model_studio")
        self.assertEqual(j["model_id"],"qwen3.8-flash")
        self.assertEqual(float(j["temperature"]),0.0)
        self.assertEqual(int(j["max_tokens"]),16384)
        self.assertIs(j["enable_thinking"],False)
        self.assertIs(j["substitution_allowed"],False)

    def test_implementation_binding_hashes_match(self):
        ref=self.impl["halumem_official_scorer_reference"]
        self.assertEqual(ref["judge_model_binding_status"],"FROZEN_ALTERNATIVE_QWEN_CONFIRMATORY_BINDING")
        jb=ref["final_judge_binding"]
        cal=ref["calibration"]
        self.assertEqual(sha(GOV.parent/jb["path"]),jb["sha256"])
        self.assertEqual(sha(GOV.parent/cal["path"]),cal["sha256"])
        self.assertEqual(cal["required_pass"],"12/12")
        self.assertEqual(ref["confirmatory_judge_config"]["model_id"],"qwen3.8-flash")
        self.assertFalse(ref["external_gpt4o_medians_formal_gate_allowed"])

    def test_calibration_is_balanced_and_exact_12(self):
        self.assertEqual(self.cal["status"],"FROZEN_BEFORE_QWEN38_FLASH_CALIBRATION_CALLS")
        self.assertEqual(self.cal["judge_candidate"]["model_id"],"qwen3.8-flash")
        cases=self.cal["cases"]
        self.assertEqual(len(cases),12)
        by={}
        for c in cases:
            by.setdefault(c["metric"],[]).append(c)
        self.assertEqual({k:len(v) for k,v in by.items()},
                         {"memory_integrity":3,"memory_accuracy":3,
                          "memory_update":3,"question_answering":3})
        self.assertEqual(self.cal["gate"]["required_pass"],12)
        self.assertIs(self.cal["gate"]["allow_partial"],False)

    def test_confirmatory_runner_contract_is_fail_closed_and_gold_isolated(self):
        contract_path=CF/"HALUMEM_CONFIRMATORY_RUNNER_CONTRACT.json"
        c=json.loads(contract_path.read_text(encoding="utf-8"))
        ref=self.impl["halumem_confirmatory_runner_contract"]
        self.assertEqual(sha(contract_path),ref["sha256"])
        self.assertEqual(c["schema"],"xiaoyu-halumem-confirmatory-runner-contract-v2")
        self.assertEqual(c["status"],"PREFREEZE_FINAL_RUNNER_BOUND_WAITING_FINAL_V2_REAUDIT")
        self.assertEqual(c["judge_and_scorer"]["model"],"qwen3.8-flash")
        self.assertEqual(c["judge_and_scorer"]["provider"],"alibaba_model_studio")
        self.assertIs(c["judge_and_scorer"]["enable_thinking"],False)
        self.assertEqual(c["promoted_runtime"]["r52_submission_id"],"sub-0cc4e587fc8a46d4")
        self.assertFalse(c["promoted_runtime"]["destructive_transition"]["auto_confirm_allowed"])
        self.assertFalse(c["promoted_runtime"]["destructive_transition"]["unconfirmed_destructive_mutates_authoritative_state"])
        self.assertEqual(c["prediction_boundary"]["stage_order"],
                         ["prediction","seal_predictions","judge_calibration","gold_scoring"])
        self.assertEqual(c["prediction_boundary"]["expected_prediction_files"],36)
        self.assertTrue(c["prediction_boundary"]["all_predictions_sealed_before_any_gold_read"])
        self.assertIn("questions[].answer",c["prediction_boundary"]["forbidden_before_seal"])
        self.assertIn("memory_points",c["prediction_boundary"]["forbidden_before_seal"])
        self.assertTrue(c["paid_execution"]["prefreeze_paid_calls_forbidden"])
        self.assertTrue(c["paid_execution"]["final_freeze_record_required"])

    def test_missing_key_never_changes_judge_config(self):
        if not os.getenv("DASHSCOPE_API_KEY"):
            self.assertIs(self.binding["runtime"]["execution_ready_at_freeze"],False)
        self.assertFalse(self.binding["comparability"]["external_median_gate_allowed"])
        self.assertTrue(self.binding["comparability"]["qwen_rebaseline_required"])
        self.assertIs(self.binding["judge"]["substitution_allowed"],False)

if __name__=="__main__":
    unittest.main()
