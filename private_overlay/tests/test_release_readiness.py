import json
import tempfile
import unittest
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from check_release_readiness import _git_blob_sha, evaluate_matrix, evaluate_release_manifest


class ReleaseReadinessTests(unittest.TestCase):
    def test_current_acceptance_matrix_is_release_ready(self):
        matrix = json.loads((ROOT / "evals" / "acceptance_matrix.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(evaluate_matrix(matrix, ROOT), [])

    def test_release_binding_uses_canonical_git_blob_identity(self):
        rel = "private_overlay/plugins/xiaoyu_interaction_policy/plugin.toml"
        expected = subprocess.check_output(
            ["git", "-C", str(ROOT.parent), "rev-parse", f"HEAD:{rel}"],
            text=True,
            encoding="utf-8",
        ).strip()
        self.assertEqual(
            _git_blob_sha(ROOT / "plugins" / "xiaoyu_interaction_policy" / "plugin.toml", ROOT.parent),
            expected,
        )

    def test_current_stable_release_manifest_matches_authoritative_product_state(self):
        manifest = json.loads(
            (ROOT / "release" / "NEKO_OVERLAY_V1_FINAL.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(evaluate_release_manifest(manifest, ROOT), [])

    def test_stale_release_manifest_pin_patch_acceptance_and_binding_fail_closed(self):
        manifest = json.loads(
            (ROOT / "release" / "NEKO_OVERLAY_V1_FINAL.json").read_text(
                encoding="utf-8-sig"
            )
        )

        stale_pin = json.loads(json.dumps(manifest))
        stale_pin["external_pins"]["neko"]["commit"] = "stale"
        self.assertIn(
            "release manifest N.E.K.O pin does not match NEKO_UPSTREAM.lock.json",
            evaluate_release_manifest(stale_pin, ROOT),
        )

        stale_patch = json.loads(json.dumps(manifest))
        stale_patch["managed_core_patches"]["count"] -= 1
        self.assertIn(
            "release manifest managed patch count is stale",
            evaluate_release_manifest(stale_patch, ROOT),
        )

        stale_acceptance = json.loads(json.dumps(manifest))
        stale_acceptance["acceptance"]["ids"] = stale_acceptance["acceptance"]["ids"][:-1]
        self.assertIn(
            "release manifest acceptance IDs are stale",
            evaluate_release_manifest(stale_acceptance, ROOT),
        )

        stale_binding = json.loads(json.dumps(manifest))
        stale_binding["bindings_git_blob_sha"]["QQ_PLUGIN_UPSTREAM.lock.json"] = "stale"
        self.assertIn(
            "release manifest binding stale: QQ_PLUGIN_UPSTREAM.lock.json",
            evaluate_release_manifest(stale_binding, ROOT),
        )


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
