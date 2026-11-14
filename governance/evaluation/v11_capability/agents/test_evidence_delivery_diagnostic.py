# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from answer_outcome_gate import classify_delivery_trace
from evidence_delivery_diagnostic import (
    load_manual_evidence, model_input_record, replace_evidence_section, write_plan,
)


class EvidenceDeliveryDiagnosticTests(unittest.TestCase):
    def test_hrp_breakpoints_are_distinct(self):
        base = {"basis": "human_verified", "history_sufficient": True}
        self.assertEqual(
            classify_delivery_trace({**base, "retrieval_sufficient": False})["stage"],
            "retrieval_miss")
        self.assertEqual(
            classify_delivery_trace({
                **base, "retrieval_sufficient": True, "prompt_sufficient": False
            })["stage"], "evidence_incomplete")
        self.assertEqual(
            classify_delivery_trace({
                **base, "retrieval_sufficient": True, "prompt_sufficient": True,
                "temporal_required": True, "temporal_reasoning_correct": False
            })["stage"], "temporal_reasoning")
        self.assertEqual(
            classify_delivery_trace({
                **base, "retrieval_sufficient": True, "prompt_sufficient": True,
                "general_reasoning_correct": False
            })["stage"], "general_reasoning")
        self.assertEqual(
            classify_delivery_trace({
                **base, "retrieval_sufficient": True, "prompt_sufficient": True,
                "required_output_complete": False
            })["stage"], "answer_incomplete")

    def test_self_report_is_not_verified_trace(self):
        r = classify_delivery_trace({
            "basis": "model_self",
            "history_sufficient": True,
            "retrieval_sufficient": False,
        })
        self.assertEqual(r["stage"], "retrieval_miss")
        self.assertFalse(r["verified"])

    def test_manual_evidence_replaces_payload_and_records_exact_input(self):
        messages = [
            {"role": "system", "content": "Answer from evidence."},
            {"role": "user", "content":
             "QUESTION:\nWhen?\nAUTHORIZED EXTERNAL PUBLIC EVIDENCE:\nold\n"},
        ]
        out = replace_evidence_section(messages, "RAW A\nRAW B")
        self.assertIn("RAW A\nRAW B", out[1]["content"])
        self.assertNotIn("\nold\n", out[1]["content"])
        rec = model_input_record(out)
        self.assertEqual(len(rec["model_input_sha256"]), 64)
        self.assertEqual(rec["messages"], out)

    def test_prepare_plan_is_gold_free_and_contains_exact_messages(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            suite = td / "suite.json"
            manual = td / "manual.jsonl"
            out = td / "plan.json"
            suite.write_text(json.dumps({"cases": [{
                "case_id": "c1",
                "baseline_messages": [
                    {"role": "system", "content": "Answer."},
                    {"role": "user", "content":
                     "Q\nAUTHORIZED EXTERNAL PUBLIC EVIDENCE:\nold\n"},
                ],
            }]}) + "\n", "utf-8")
            manual.write_text(json.dumps({
                "case_id": "c1", "evidence_text": "raw fact",
                "source_refs": ["s1"]
            }) + "\n", "utf-8")
            result = write_plan(suite, manual, ["c1"], out)
            self.assertFalse(result["gold_loaded"])
            self.assertEqual(result["n"], 1)
            self.assertIn("raw fact", result["cases"][0]["messages"][1]["content"])
            self.assertEqual(len(result["cases"][0]["model_input_sha256"]), 64)

    def test_manual_packet_rejects_gold_fields(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "manual.jsonl"
            p.write_text(json.dumps({
                "case_id": "c1", "evidence_text": "raw",
                "gold_answer": "secret"
            }) + "\n", "utf-8")
            with self.assertRaisesRegex(ValueError, "gold_or_reference"):
                load_manual_evidence(p)


if __name__ == "__main__":
    unittest.main()
