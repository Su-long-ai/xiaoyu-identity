import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "check_reuse_first.py"
SPEC = importlib.util.spec_from_file_location("check_reuse_first", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class ReuseArtifactAdmissionTests(unittest.TestCase):
    def test_runtime_artifact_classifier_is_narrow_and_semantic(self):
        root = Path("/repo/private_overlay")
        self.assertEqual(
            mod.classify_runtime_artifact(root / "tools" / "presence_adapter.py", root),
            "runtime_adapter",
        )
        self.assertEqual(
            mod.classify_runtime_artifact(root / "tools" / "delivery_router.py", root),
            "router",
        )
        self.assertEqual(
            mod.classify_runtime_artifact(root / "daemons" / "worker.py", root),
            "daemon",
        )
        self.assertEqual(
            mod.classify_runtime_artifact(root / "tools" / "session_store.py", root),
            "state_store",
        )
        self.assertIsNone(
            mod.classify_runtime_artifact(root / "tests" / "test_delivery_router.py", root)
        )
        self.assertIsNone(
            mod.classify_runtime_artifact(root / "evals" / "evidence_router.py", root)
        )
        self.assertIsNone(
            mod.classify_runtime_artifact(root / "tools" / "restore_runtime.py", root)
        )

    def test_external_patch_requires_exact_reuse_artifact_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patch = root / "qq_patches" / "0001-live.patch"
            patch.parent.mkdir(parents=True)
            patch.write_text("candidate", encoding="utf-8")
            (root / "plugins").mkdir()

            errors = []
            counts = mod.check_additional_artifacts(root, {}, {}, errors)
            self.assertEqual(counts, (1, 0, 0))
            self.assertIn(
                "external_patch has no approved reuse artifact claim: "
                "qq_patches/0001-live.patch",
                errors,
            )

            errors = []
            items = [
                {
                    "id": "external:qq-live",
                    "artifacts": [
                        {
                            "path": "qq_patches/0001-live.patch",
                            "kind": "external_patch",
                            "retirement_condition": "retire when pinned QQ provides equivalent behavior",
                        }
                    ],
                }
            ]
            claims = mod.collect_artifact_claims(items, errors)
            counts = mod.check_additional_artifacts(root, {}, claims, errors)
            self.assertEqual(counts, (1, 0, 0))
            self.assertEqual(errors, [])

    def test_private_plugin_directory_requires_review_before_manifest_admission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin = root / "plugins" / "future_plugin"
            plugin.mkdir(parents=True)
            (plugin / "plugin.toml").write_text("[plugin]\n", encoding="utf-8")

            errors = []
            counts = mod.check_additional_artifacts(root, {}, {}, errors)
            self.assertEqual(counts, (0, 1, 0))
            self.assertIn(
                "private plugin directory has no approved reuse review: future_plugin",
                errors,
            )

            errors = []
            counts = mod.check_additional_artifacts(
                root, {"plugin:future_plugin": {"status": "approved"}}, {}, errors
            )
            self.assertEqual(counts, (0, 1, 0))
            self.assertEqual(errors, [])

    def test_router_and_state_store_require_matching_claim_kind(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            (tools_dir / "surface_router.py").write_text("", encoding="utf-8")
            (tools_dir / "delivery_store.py").write_text("", encoding="utf-8")
            (root / "plugins").mkdir()

            errors = []
            mod.check_additional_artifacts(root, {}, {}, errors)
            self.assertIn(
                "router has no approved reuse artifact claim: tools/surface_router.py",
                errors,
            )
            self.assertIn(
                "state_store has no approved reuse artifact claim: tools/delivery_store.py",
                errors,
            )

            errors = []
            items = [
                {
                    "id": "governance:test",
                    "artifacts": [
                        {
                            "path": "tools/surface_router.py",
                            "kind": "router",
                            "retirement_condition": "native router exists",
                        },
                        {
                            "path": "tools/delivery_store.py",
                            "kind": "state_store",
                            "retirement_condition": "native store exists",
                        },
                    ],
                }
            ]
            claims = mod.collect_artifact_claims(items, errors)
            mod.check_additional_artifacts(root, {}, claims, errors)
            self.assertEqual(errors, [])

    def test_artifact_claim_requires_retirement_condition(self):
        errors = []
        claims = mod.collect_artifact_claims(
            [
                {
                    "id": "governance:test",
                    "artifacts": [
                        {
                            "path": "tools/x_adapter.py",
                            "kind": "runtime_adapter",
                        }
                    ],
                }
            ],
            errors,
        )
        self.assertEqual(claims["tools/x_adapter.py"][1], "runtime_adapter")
        self.assertIn(
            "artifact 0 missing retirement_condition: governance:test",
            errors,
        )

    def test_artifact_path_rejects_parent_escape(self):
        errors = []
        claims = mod.collect_artifact_claims(
            [
                {
                    "id": "governance:test",
                    "artifacts": [
                        {
                            "path": "../outside_router.py",
                            "kind": "router",
                            "retirement_condition": "never",
                        }
                    ],
                }
            ],
            errors,
        )
        self.assertEqual(claims, {})
        self.assertIn("artifact 0 has invalid path: governance:test", errors)


    def _hierarchy_entry(self, status, *, outcome=None, evidence=None, rationale=None):
        item = {"status": status}
        if outcome is not None:
            item["outcome"] = outcome
        if evidence is not None:
            item["evidence"] = evidence
        if rationale is not None:
            item["rationale"] = rationale
        return item

    def _layered_review(self):
        evidence = "governance/architecture_freeze.json"
        return {
            "id": "governance:test-hierarchy",
            "reviewed_at": "2026-11-23",
            "decision": "thin_adapter",
            "search_layers": {
                "L0_authority": self._hierarchy_entry(
                    "checked", outcome="native authority retained", evidence=evidence
                ),
                "L1_neko_current_pin": self._hierarchy_entry(
                    "checked", outcome="current pin checked", evidence=evidence
                ),
                "L2_neko_upstream_extensions": self._hierarchy_entry(
                    "checked", outcome="upstream/extensions checked", evidence=evidence
                ),
                "L3_existing_pinned_external": self._hierarchy_entry(
                    "not_applicable",
                    rationale="No pinned external component owns this repository-local gap.",
                ),
                "L4_broader_external_ecosystem": self._hierarchy_entry(
                    "not_applicable",
                    rationale="External replacement would duplicate the already-selected authority.",
                ),
                "L5_thin_integration": self._hierarchy_entry(
                    "checked", outcome="thin integration selected", evidence=evidence
                ),
                "L6_private_implementation": self._hierarchy_entry(
                    "not_applicable",
                    rationale="No private implementation is required after the thin integration.",
                ),
            },
        }

    def test_hierarchy_policy_and_current_reviews_are_machine_enforced(self):
        data = mod.load(mod.REVIEWS)
        errors = []
        cutoff = mod.validate_hierarchy_policy(data, errors)
        self.assertEqual(cutoff, "2026-11-23")
        for item in data["reviews"]:
            mod.validate_search_layers(item, cutoff, errors)
        self.assertEqual(errors, [])

    def test_hierarchy_rejects_component_local_review(self):
        review = self._layered_review()
        for layer in (
            "L1_neko_current_pin",
            "L2_neko_upstream_extensions",
            "L3_existing_pinned_external",
            "L4_broader_external_ecosystem",
        ):
            review["search_layers"][layer] = self._hierarchy_entry(
                "not_applicable",
                rationale=(
                    "This layer was declared outside the local component without "
                    "materially evaluating another reusable implementation."
                ),
            )
        errors = []
        mod.validate_search_layers(review, "2026-11-23", errors)
        self.assertIn(
            "hierarchical reuse is too local; fewer than two discovery layers were checked: "
            "governance:test-hierarchy",
            errors,
        )

    def test_hierarchy_rejects_missing_layer(self):
        review = self._layered_review()
        del review["search_layers"]["L4_broader_external_ecosystem"]
        errors = []
        mod.validate_search_layers(review, "2026-11-23", errors)
        self.assertIn(
            "hierarchical reuse layer missing L4_broader_external_ecosystem: "
            "governance:test-hierarchy",
            errors,
        )

    def test_hierarchy_rejects_checked_layer_without_evidence(self):
        review = self._layered_review()
        review["search_layers"]["L2_neko_upstream_extensions"].pop("evidence")
        errors = []
        mod.validate_search_layers(review, "2026-11-23", errors)
        self.assertIn(
            "checked hierarchy layer missing evidence L2_neko_upstream_extensions: "
            "governance:test-hierarchy",
            errors,
        )



if __name__ == "__main__":
    unittest.main()
