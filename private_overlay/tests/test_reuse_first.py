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


if __name__ == "__main__":
    unittest.main()
