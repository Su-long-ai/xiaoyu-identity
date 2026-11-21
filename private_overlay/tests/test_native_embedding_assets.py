import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "ensure_native_embedding_assets.py"
spec = importlib.util.spec_from_file_location("ensure_native_embedding_assets", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class NativeEmbeddingAssetTests(unittest.TestCase):
    def _root(self, td: str) -> Path:
        root = Path(td)
        (root / ".venv" / "Scripts").mkdir(parents=True)
        (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"x")
        (root / "scripts").mkdir()
        (root / "scripts" / "prepare_embedding_model.py").write_text("# native", encoding="utf-8")
        return root

    def _marker(self, root: Path, *, repo=mod.REPO, revision=mod.REVISION) -> None:
        profile = root / "data" / "embedding_models" / mod.PROFILE_ID
        profile.mkdir(parents=True, exist_ok=True)
        (profile / mod.PREPARED_MARKER).write_text(
            json.dumps({"repo": repo, "revision": revision}),
            encoding="utf-8",
        )

    def test_ready_profile_is_zero_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            self._marker(root)
            with patch.object(mod, "_native_profile_complete", return_value=True), patch.object(
                mod.subprocess, "run"
            ) as run:
                result = mod.ensure_assets(root)
            self.assertEqual(result["action"], "already_ready")
            run.assert_not_called()

    def test_verify_only_fails_closed_on_missing_or_wrong_pin(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            self._marker(root, revision="0" * 40)
            with patch.object(mod, "_native_profile_complete", return_value=True):
                with self.assertRaises(RuntimeError):
                    mod.ensure_assets(root, verify_only=True)

    def test_missing_profile_delegates_download_to_neko_native_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            ready = {
                "output_root": str(root / "data" / "embedding_models"),
                "profile_dir": str(root / "data" / "embedding_models" / mod.PROFILE_ID),
                "complete": True,
                "pin_matches": True,
                "ready": True,
                "marker": {"repo": mod.REPO, "revision": mod.REVISION},
            }
            with patch.object(
                mod,
                "inspect_assets",
                side_effect=[
                    {"ready": False, "complete": False, "pin_matches": False},
                    ready,
                ],
            ), patch.object(mod.subprocess, "run") as run:
                result = mod.ensure_assets(root)
            self.assertEqual(result["action"], "prepared_by_neko_native_script")
            run.assert_called_once()
            argv = run.call_args.args[0]
            self.assertIn("prepare_embedding_model.py", argv[1])
            self.assertIn(mod.REPO, argv)
            self.assertIn(mod.REVISION, argv)
            self.assertIn("--variant", argv)
            self.assertIn("int8", argv)

    def test_helper_contains_no_downloader_or_model_mirror_implementation(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("urllib", source)
        self.assertNotIn("httpx", source)
        self.assertNotIn("requests", source)
        self.assertIn("prepare_embedding_model.py", source)
        self.assertIn("profile_is_complete", source)


if __name__ == "__main__":
    unittest.main()
