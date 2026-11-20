import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

sdk = types.ModuleType("plugin.sdk.plugin")
class _Base: pass
class _Ok:
    def __init__(self, value=None): self.value = value
class _Err:
    def __init__(self, error=None): self.error = error
class _SdkError(Exception): pass
def _identity(*_a, **_k):
    return lambda obj: obj

sdk.NekoPluginBase = _Base
sdk.Ok = _Ok
sdk.Err = _Err
sdk.SdkError = _SdkError
sdk.lifecycle = _identity
sdk.neko_plugin = lambda cls: cls
sdk.plugin_entry = _identity
sdk.timer_interval = _identity
sys.modules.setdefault("plugin", types.ModuleType("plugin"))
sys.modules.setdefault("plugin.sdk", types.ModuleType("plugin.sdk"))
sys.modules["plugin.sdk.plugin"] = sdk

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "xiaoyu_interaction_policy" / "__init__.py"
spec = importlib.util.spec_from_file_location("xiaoyu_interaction_policy", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class ParserTests(unittest.TestCase):
    def test_json_quiet(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"quiet","duration_minutes":10}'),
            {"action": "quiet", "duration_minutes": 10, "speech_action": "unchanged"},
        )

    def test_resume_never_keeps_duration(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"resume","duration_minutes":10}'),
            {"action": "resume", "duration_minutes": None, "speech_action": "unchanged"},
        )

    def test_invalid_output_fails_to_none(self):
        self.assertEqual(
            mod.parse_classifier_output("maybe quiet"),
            {"action": "none", "duration_minutes": None, "speech_action": "unchanged"},
        )

    def test_markdown_json_is_accepted(self):
        fence = chr(96) * 3
        raw = fence + 'json\n{"action":"quiet","duration_minutes":30}\n' + fence
        self.assertEqual(
            mod.parse_classifier_output(raw),
            {"action": "quiet", "duration_minutes": 30, "speech_action": "unchanged"},
        )

    def test_v1_state_normalization_preserves_explicit_speech_migration(self):
        state = mod._normalize_state({
            "version": 1,
            "quiet": True,
            "speech_muted": True,
            "previous_proactive_chat_enabled": True,
        })
        self.assertEqual(state["version"], 2)
        self.assertTrue(state["quiet"])
        self.assertTrue(state["speech_muted"])
        self.assertTrue(state["previous_proactive_chat_enabled"])

    def test_ambiguous_v1_quiet_does_not_invent_speech_mute(self):
        state = mod._normalize_state({"version": 1, "quiet": True})
        self.assertTrue(state["quiet"])
        self.assertFalse(state["speech_muted"])

    def test_speech_action_is_parsed(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"quiet","duration_minutes":null,"speech_action":"mute"}'),
            {"action": "quiet", "duration_minutes": None, "speech_action": "mute"},
        )

    def test_fast_speech_control_handles_exact_hard_commands(self):
        self.assertEqual(
            mod.fast_speech_control("小鱼，请别说话。"),
            {"action": "quiet", "duration_minutes": None, "speech_action": "mute"},
        )
        self.assertEqual(
            mod.fast_speech_control("可以说话了"),
            {"action": "resume", "duration_minutes": None, "speech_action": "unmute"},
        )
        self.assertIsNone(mod.fast_speech_control("朋友让我别说话是什么意思"))

    def test_candidate_filter_covers_live_phrases(self):
        self.assertTrue(mod.candidate_needs_semantic_check("别说话哦"))
        self.assertTrue(mod.candidate_needs_semantic_check("可以说话了"))
        self.assertTrue(mod.candidate_needs_semantic_check("你先别主动找我"))

    def test_quiet_mode_semantically_checks_novel_resume_phrasing(self):
        self.assertTrue(mod.should_run_semantic_check("好了你正常来吧", quiet=True))
        self.assertTrue(mod.should_run_semantic_check("你又能讲话了", quiet=True))

    def test_nonquiet_mode_keeps_cost_prefilter_for_ordinary_chat(self):
        self.assertFalse(mod.should_run_semantic_check("今天天气不错", quiet=False))
        self.assertTrue(mod.should_run_semantic_check("你先别主动找我", quiet=False))

    def test_candidate_filter_avoids_ordinary_chat(self):
        self.assertFalse(mod.candidate_needs_semantic_check("今天天气不错，我们继续写代码吧"))

    def test_state_does_not_contain_user_text(self):
        state = mod._normalize_state({
            "initialized": True,
            "seen_event_ids": ["a"],
            "quiet": True,
            "speech_muted": True,
            "previous_proactive_chat_enabled": True,
        })
        blob = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("content", state)
        self.assertNotIn("user_text", state)
        self.assertNotIn("别说话", blob)
        self.assertTrue(state["speech_muted"])

    def test_duration_out_of_range_is_dropped(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"quiet","duration_minutes":1441}'),
            {"action": "quiet", "duration_minutes": None, "speech_action": "unchanged"},
        )


if __name__ == "__main__":
    unittest.main()
