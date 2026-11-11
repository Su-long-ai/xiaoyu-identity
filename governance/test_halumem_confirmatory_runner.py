# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "governance" / "confirmatory_frozen" / "HALUMEM_CONFIRMATORY_RUNNER.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("_xiaoyu_halu_runner_test", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HaluConfirmatoryRunnerTests(unittest.TestCase):
    def test_preflight_is_offline_and_does_not_touch_dataset_or_provider(self):
        m = load_runner()
        out = m.preflight()
        self.assertEqual(out["stage"], "PREFLIGHT_NO_DATASET_READ")
        self.assertEqual(out["confirmatory_dataset_records_read"], 0)
        self.assertEqual(out["provider_calls"], 0)
        self.assertEqual(out["judge_calls"], 0)
        self.assertEqual(out["confirmatory_user_count"], 18)
        self.assertIn("execution_authorized", out)

    def test_safe_projection_structurally_skips_gold_and_unselected_fields(self):
        m = load_runner()
        raw = {
            "uuid": "synthetic-uuid",
            "sessions": [{
                "dialogue": [
                    {"role": "user", "content": "I prefer tea.", "answer": "gold-in-turn"},
                    {"role": "assistant", "content": "Noted.", "evidence": "gold-evidence"},
                ],
                "questions": [{
                    "question": "What do I prefer?",
                    "answer": "tea",
                    "difficulty": "easy",
                }],
                "memory_points": ["secret-gold"],
            }],
            "persona_info": {"favorite": "tea"},
            "answer": "tea",
            "evidence": ["hidden"],
        }
        projected = m.safe_project_line(json.dumps(raw, ensure_ascii=False))
        self.assertEqual(projected["uuid"], "synthetic-uuid")
        self.assertEqual(
            projected["sessions"],
            [{
                "dialogue": [
                    {"role": "user", "content": "I prefer tea."},
                    {"role": "assistant", "content": "Noted."},
                ],
                "questions": [{"question": "What do I prefer?"}],
            }],
        )
        blob = json.dumps(projected, ensure_ascii=False)
        for key in m.FORBIDDEN_PREDICTION_KEYS:
            self.assertNotIn('"'+key+'"', blob)

    def test_safe_projection_fails_closed_if_sessions_precede_uuid(self):
        m = load_runner()
        line = json.dumps({
            "sessions": [{"dialogue": [], "questions": []}],
            "uuid": "late-uuid",
        })
        with self.assertRaisesRegex(m.RunnerError, "uuid must precede sessions"):
            m.safe_project_line(line)


if __name__ == "__main__":
    unittest.main()
