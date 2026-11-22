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

    def test_text_eol_only_difference_is_exact(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            installed = base / "installed"
            self._write_plugin(source)
            self._write_plugin(installed)

            for name in ("plugin.toml", "__init__.py"):
                path = installed / name
                text = path.read_text(encoding="utf-8")
                path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))

            exact, reason = mod._installed_matches_source(source, installed)
            self.assertTrue(exact)
            self.assertEqual(reason, "exact_source_match")

    def test_binary_payload_remains_byte_exact(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            installed = base / "installed"
            self._write_plugin(source)
            self._write_plugin(installed)
            (source / "asset.bin").write_bytes(b"\x00\x01")
            (installed / "asset.bin").write_bytes(b"\x00\x02")
            exact, reason = mod._installed_matches_source(source, installed)
            self.assertFalse(exact)
            self.assertEqual(reason, "content_mismatch:asset.bin")

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



    def test_classifier_binding_runs_native_autobind_for_fresh_unbound_usage(self):
        class Service:
            def __init__(self):
                self.slot_id = ""
                self.version = 0
                self.ensure_calls = 0
                self.set_calls = []
                self.slots = {
                    "slot_agent": {
                        "id": "slot_agent",
                        "source": "host_follow",
                        "host_api": "agent",
                        "capabilities": ["text"],
                    }
                }

            def get_bindings(self, plugin_id):
                return {"requirements": {
                    mod.CLASSIFIER_MODEL_USAGE: {
                        "slot_id": self.slot_id,
                        "status": "bound" if self.slot_id else "unbound",
                        "version": self.version,
                    }
                }}

            def get_slot(self, slot_id):
                return self.slots[slot_id]

            def ensure_host_follow_binding(self, plugin_id):
                self.ensure_calls += 1
                self.slot_id = "slot_agent"
                self.version = 1
                return {"bound": [mod.CLASSIFIER_MODEL_USAGE], "slot_id": self.slot_id}

            def list_slots(self):
                return {"slots": list(self.slots.values())}

            def create_slot(self, payload):
                slot = {"id": "slot_small", **payload}
                self.slots["slot_small"] = slot
                return slot

            def set_binding(self, plugin_id, usage_id, slot_id, expected_version):
                self.slot_id = slot_id
                self.version = expected_version + 1
                self.set_calls.append((usage_id, slot_id, expected_version))

        service = Service()
        state = mod._ensure_classifier_model_binding(service)
        self.assertEqual(service.ensure_calls, 1)
        self.assertEqual(state["migration"], "auto_agent_to_agent_small")
        self.assertEqual(state["host_api"], "agent_small")
        self.assertEqual(service.set_calls, [(mod.CLASSIFIER_MODEL_USAGE, "slot_small", 1)])

    def test_classifier_binding_preserves_explicit_unbind(self):
        class Service:
            def get_bindings(self, plugin_id):
                return {"requirements": {
                    mod.CLASSIFIER_MODEL_USAGE: {
                        "slot_id": "",
                        "status": "unbound",
                        "version": 1,
                    }
                }}

            def ensure_host_follow_binding(self, plugin_id):
                raise AssertionError("explicit unbind must not be rebound")

        state = mod._ensure_classifier_model_binding(Service())
        self.assertEqual(state["migration"], "user_binding_preserved")
        self.assertEqual(state["status"], "unbound")
        self.assertEqual(state["version"], 1)

    def test_classifier_binding_migrates_only_first_native_agent_autobind(self):
        class Service:
            def __init__(self):
                self.slot_id = "slot_agent"
                self.version = 1
                self.slots = {
                    "slot_agent": {
                        "id": "slot_agent",
                        "source": "host_follow",
                        "host_api": "agent",
                        "capabilities": ["text"],
                    }
                }
                self.set_calls = []

            def get_bindings(self, plugin_id):
                if plugin_id != mod.PLUGIN_ID:
                    raise AssertionError(plugin_id)
                return {"requirements": {
                    mod.CLASSIFIER_MODEL_USAGE: {
                        "slot_id": self.slot_id,
                        "status": "bound",
                        "version": self.version,
                    }
                }}

            def get_slot(self, slot_id):
                return self.slots[slot_id]

            def list_slots(self):
                return {"slots": list(self.slots.values())}

            def create_slot(self, payload):
                if payload["host_api"] != "agent_small":
                    raise AssertionError(payload)
                slot = {"id": "slot_small", **payload}
                self.slots["slot_small"] = slot
                return slot

            def set_binding(self, plugin_id, usage_id, slot_id, expected_version):
                if plugin_id != mod.PLUGIN_ID:
                    raise AssertionError(plugin_id)
                if usage_id != mod.CLASSIFIER_MODEL_USAGE or expected_version != 1:
                    raise AssertionError((usage_id, expected_version))
                self.slot_id = slot_id
                self.version = 2
                self.set_calls.append((usage_id, slot_id))

        service = Service()
        state = mod._ensure_classifier_model_binding(service)
        self.assertEqual(state["migration"], "auto_agent_to_agent_small")
        self.assertEqual(state["host_api"], "agent_small")
        self.assertEqual(service.set_calls, [(mod.CLASSIFIER_MODEL_USAGE, "slot_small")])

    def test_classifier_binding_preserves_user_managed_binding(self):
        class Service:
            def get_bindings(self, plugin_id):
                return {"requirements": {
                    mod.CLASSIFIER_MODEL_USAGE: {
                        "slot_id": "slot_user",
                        "status": "bound",
                        "version": 2,
                    }
                }}

            def get_slot(self, slot_id):
                return {
                    "id": slot_id,
                    "source": "host_follow",
                    "host_api": "agent",
                    "capabilities": ["text"],
                }

            def list_slots(self):
                raise AssertionError("user-managed binding must not be migrated")

            def set_binding(self, *args, **kwargs):
                raise AssertionError("user-managed binding must not be changed")

        state = mod._ensure_classifier_model_binding(Service())
        self.assertEqual(state["migration"], "user_binding_preserved")
        self.assertEqual(state["host_api"], "agent")
        self.assertEqual(state["version"], 2)



if __name__ == "__main__":
    unittest.main()
