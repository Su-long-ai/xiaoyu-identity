import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "ensure_private_plugin.py"
spec = importlib.util.spec_from_file_location("ensure_private_plugin", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class EnsurePrivatePluginTests(unittest.TestCase):
    def _write_plugin(self, root: Path, *, version: str = "0.3.0", body: str = "VALUE = 1\n") -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "plugin.toml").write_text(
            "[plugin]\n"
            'name = "XiaoYu Interaction Policy"\n'
            f'version = "{version}"\n'
            'id = "xiaoyu_interaction_policy"\n'
            'type = "plugin"\n'
            'entry = "plugin.plugins.xiaoyu_interaction_policy:X"\n',
            encoding="utf-8",
        )
        (root / "__init__.py").write_text(body, encoding="utf-8")

    def test_exact_install_matches_source(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            installed = base / "installed"
            self._write_plugin(source)
            self._write_plugin(installed)
            exact, reason = mod._installed_matches_source(source, installed)
            self.assertTrue(exact)
            self.assertEqual(reason, "exact_source_match")

    def test_version_or_content_drift_is_stale(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            installed = base / "installed"
            self._write_plugin(source, version="0.3.0", body="VALUE = 1\n")
            self._write_plugin(installed, version="0.2.0", body="VALUE = 1\n")
            exact, reason = mod._installed_matches_source(source, installed)
            self.assertFalse(exact)
            self.assertEqual(reason, "version_mismatch")
            self._write_plugin(installed, version="0.3.0", body="VALUE = 2\n")
            exact, reason = mod._installed_matches_source(source, installed)
            self.assertFalse(exact)
            self.assertEqual(reason, "content_mismatch:__init__.py")

    def test_runtime_state_is_not_part_of_executable_match(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            installed = base / "installed"
            self._write_plugin(source)
            self._write_plugin(installed)
            state = base / "plugins" / "xiaoyu_interaction_policy" / "data"
            state.mkdir(parents=True)
            (state / "state.json").write_text('{"quiet":true}', encoding="utf-8")
            exact, _ = mod._installed_matches_source(source, installed)
            self.assertTrue(exact)


    def test_live_runtime_blocks_only_replacement_not_verify_or_exact(self):
        self.assertTrue(mod._should_block_live_replacement(
            exact=False, verify_only=False, open_ports=[48911, 48916]
        ))
        self.assertFalse(mod._should_block_live_replacement(
            exact=True, verify_only=False, open_ports=[48911]
        ))
        self.assertFalse(mod._should_block_live_replacement(
            exact=False, verify_only=True, open_ports=[48911]
        ))
        self.assertFalse(mod._should_block_live_replacement(
            exact=False, verify_only=False, open_ports=[]
        ))


    def test_v060_migration_clears_legacy_audio_only_mute_without_changing_quiet(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "plugins" / mod.PLUGIN_ID / "data" / "state.json"
            state.parent.mkdir(parents=True)
            state.write_text(
                '{"version":3,"quiet":false,"speech_muted":true}',
                encoding="utf-8",
            )
            changed = mod._migrate_reply_output_state(
                root,
                from_version="0.5.1",
                target_version="0.6.0",
            )
            self.assertTrue(changed)
            value = __import__("json").loads(state.read_text(encoding="utf-8"))
            self.assertEqual(value["version"], 4)
            self.assertFalse(value["quiet"])
            self.assertFalse(value["speech_muted"])

    def test_non_v060_install_does_not_rewrite_legacy_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "plugins" / mod.PLUGIN_ID / "data" / "state.json"
            state.parent.mkdir(parents=True)
            state.write_text(
                '{"version":3,"quiet":true,"speech_muted":true}',
                encoding="utf-8",
            )
            changed = mod._migrate_reply_output_state(
                root,
                from_version="0.5.1",
                target_version="0.5.2",
            )
            self.assertFalse(changed)
            self.assertTrue(
                __import__("json").loads(state.read_text(encoding="utf-8"))["speech_muted"]
            )

if __name__ == "__main__":
    unittest.main()
