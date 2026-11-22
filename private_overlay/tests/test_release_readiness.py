import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from check_release_readiness import evaluate_matrix


class ReleaseReadinessTests(unittest.TestCase):
    def test_current_acceptance_matrix_is_release_ready(self):
        matrix = json.loads((ROOT / "evals" / "acceptance_matrix.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(evaluate_matrix(matrix, ROOT), [])

    def test_required_acceptance_case_cannot_be_removed(self):
        matrix = json.loads(
            (ROOT / "evals" / "acceptance_matrix.json").read_text(
                encoding="utf-8-sig"
            )
        )
        matrix["tests"] = [
            case for case in matrix["tests"]
            if case.get("id") != "runtime_health_self_heal"
        ]
        problems = evaluate_matrix(matrix, ROOT)
        self.assertIn(
            "missing required acceptance id: runtime_health_self_heal",
            problems,
        )

    def test_pending_case_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            overlay = Path(td)
            evidence = overlay / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            matrix = {
                "tests": [
                    {
                        "id": "voice",
                        "status": "physical_mic_pending",
                        "evidence": "evidence.json",
                    }
                ]
            }
            problems = evaluate_matrix(matrix, overlay)
            self.assertTrue(any("unresolved status" in p for p in problems))

    def test_missing_evidence_fails_closed(self):
        matrix = {
            "tests": [
                {
                    "id": "voice",
                    "status": "physical_mic_pass",
                    "evidence": "missing.json",
                }
            ]
        }
        problems = evaluate_matrix(matrix, ROOT)
        self.assertTrue(any("evidence not found" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
