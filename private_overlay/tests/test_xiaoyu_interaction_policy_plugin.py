import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sdk = types.ModuleType("plugin.sdk.plugin")
class _Base: pass
class _Ok:
    def __init__(self, value=None): self.value = value
class _Err:
    def __init__(self, error=None): self.error = error
class _SdkError(Exception): pass
def _identity(*_a, **_k):
    return lambda obj: obj
def _llm_tool(*, name=None, description="", parameters=None, timeout=30.0, role=None, reply_tail=False):
    def decorate(obj):
        obj.__test_llm_tool_meta__ = {
            "name": name or getattr(obj, "__name__", ""),
            "description": description,
            "parameters": parameters or {"type": "object", "properties": {}},
            "timeout": timeout,
            "role": role,
            "reply_tail": reply_tail,
        }
        return obj
    return decorate

sdk.NekoPluginBase = _Base
sdk.Ok = _Ok
sdk.Err = _Err
sdk.SdkError = _SdkError
sdk.lifecycle = _identity
sdk.neko_plugin = lambda cls: cls
sdk.plugin_entry = _identity
sdk.llm_tool = _llm_tool
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
            {"action": "quiet", "duration_minutes": 10, "speech_action": "unchanged", "vision_action": "unchanged"},
        )

    def test_resume_never_keeps_duration(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"resume","duration_minutes":10}'),
            {"action": "resume", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "unchanged"},
        )

    def test_invalid_output_fails_to_none(self):
        self.assertEqual(
            mod.parse_classifier_output("maybe quiet"),
            {"action": "none", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "unchanged"},
        )

    def test_markdown_json_is_accepted(self):
        fence = chr(96) * 3
        raw = fence + 'json\n{"action":"quiet","duration_minutes":30}\n' + fence
        self.assertEqual(
            mod.parse_classifier_output(raw),
            {"action": "quiet", "duration_minutes": 30, "speech_action": "unchanged", "vision_action": "unchanged"},
        )

    def test_v1_state_normalization_preserves_explicit_speech_migration(self):
        state = mod._normalize_state({
            "version": 1,
            "quiet": True,
            "speech_muted": True,
            "previous_proactive_chat_enabled": True,
        })
        self.assertEqual(state["version"], 3)
        self.assertTrue(state["quiet"])
        self.assertTrue(state["speech_muted"])
        self.assertFalse(state["vision_blocked"])
        self.assertTrue(state["previous_proactive_chat_enabled"])

    def test_ambiguous_v1_quiet_does_not_invent_speech_mute(self):
        state = mod._normalize_state({"version": 1, "quiet": True})
        self.assertTrue(state["quiet"])
        self.assertFalse(state["speech_muted"])

    def test_speech_action_is_parsed(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"quiet","duration_minutes":null,"speech_action":"mute"}'),
            {"action": "quiet", "duration_minutes": None, "speech_action": "mute", "vision_action": "unchanged"},
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
        self.assertTrue(mod.candidate_needs_semantic_check("不要看屏幕"))

    def test_fast_vision_and_full_resume_controls(self):
        self.assertEqual(mod.fast_vision_control("小鱼，不要看屏幕。"), "block")
        self.assertEqual(mod.fast_vision_control("可以看屏幕了"), "allow")
        self.assertIsNone(mod.fast_vision_control("帮我看看屏幕上这是什么"))
        self.assertTrue(mod.fast_full_resume("恢复正常"))
        self.assertFalse(mod.fast_full_resume("恢复这个文件"))

    def test_vision_action_is_parsed(self):
        self.assertEqual(
            mod.parse_classifier_output('{"action":"none","duration_minutes":null,"speech_action":"unchanged","vision_action":"block"}'),
            {"action": "none", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "block"},
        )
        self.assertEqual(
            mod.parse_classifier_output('{"action":"none","vision_action":"restore"}')["vision_action"],
            "restore",
        )

    def test_quiet_mode_semantically_checks_novel_resume_phrasing(self):
        self.assertTrue(mod.should_run_semantic_check("好了你正常来吧", quiet=True))
        self.assertTrue(mod.should_run_semantic_check("你又能讲话了", quiet=True))
        self.assertTrue(mod.should_run_semantic_check("好了，可以继续看了", quiet=False, vision_blocked=True))

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
            {"action": "quiet", "duration_minutes": None, "speech_action": "unchanged", "vision_action": "unchanged"},
        )

    def test_activity_timeline_merges_adjacent_same_app(self):
        timeline = mod._default_activity_timeline(1000.0)
        timeline = mod._append_activity_sample(
            timeline, now=1000.0, category="focused_work", app="PyCharm", privacy_state="visible"
        )
        timeline = mod._append_activity_sample(
            timeline, now=1010.0, category="focused_work", app="PyCharm", privacy_state="visible"
        )
        self.assertEqual(len(timeline["segments"]), 1)
        self.assertEqual(timeline["segments"][0]["samples"], 2)
        self.assertEqual(timeline["segments"][0]["end"], 1010.0)

    def test_activity_timeline_preserves_gap_as_unknown(self):
        timeline = mod._default_activity_timeline(1000.0)
        timeline = mod._append_activity_sample(
            timeline, now=1000.0, category="focused_work", app="PyCharm", privacy_state="visible"
        )
        timeline = mod._append_activity_sample(
            timeline, now=1100.0, category="casual_browsing", app="Chrome", privacy_state="visible"
        )
        report = mod.build_recent_activity_report(timeline, minutes=3, now=1110.0)
        self.assertFalse(report["coverage"]["complete"])
        self.assertTrue(report["coverage"]["gaps"])
        self.assertIn("UNKNOWN", report["evidence_policy"])

    def test_activity_report_never_exposes_raw_titles(self):
        timeline = mod._default_activity_timeline(1000.0)
        timeline = mod._append_activity_sample(
            timeline, now=1000.0, category="focused_work", app="PyCharm", privacy_state="visible"
        )
        report = mod.build_recent_activity_report(timeline, minutes=1, now=1010.0)
        blob = json.dumps(report, ensure_ascii=False)
        self.assertIn("PyCharm", blob)
        self.assertNotIn("window_title", blob)
        self.assertNotIn("process_name", blob)

    def test_private_activity_has_no_app_name(self):
        timeline = mod._default_activity_timeline(1000.0)
        timeline = mod._append_activity_sample(
            timeline, now=1000.0, category="private", app=None, privacy_state="private"
        )
        report = mod.build_recent_activity_report(timeline, minutes=1, now=1010.0)
        self.assertEqual(report["segments"][0]["category"], "private")
        self.assertIsNone(report["segments"][0]["app"])


    def test_recent_activity_llm_tool_is_role_scoped_and_evidence_aware(self):
        method = mod.XiaoYuInteractionPolicyPlugin.xiaoyu_recent_activity
        meta = method.__test_llm_tool_meta__
        self.assertEqual(meta["name"], "xiaoyu_recent_activity")
        self.assertEqual(meta["role"], "XiaoYu")
        self.assertEqual(meta["timeout"], 5.0)
        self.assertEqual(meta["parameters"]["properties"]["minutes"]["maximum"], 1440)
        self.assertIn("missing coverage is unknown", meta["description"])
        policy = mod.build_recent_activity_report(mod._default_activity_timeline(1000.0), minutes=60, now=1010.0)
        self.assertFalse(policy["coverage"]["complete"])
        self.assertIn("never inactivity", policy["evidence_policy"])


class VisionNativeWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_vision_write_uses_user_settings_cas_route(self):
        class Response:
            def __init__(self, status, payload, etag=None):
                self.status_code = status
                self._payload = payload
                self.headers = {"etag": etag} if etag else {}
            def json(self):
                return self._payload
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

        class Client:
            last = None
            def __init__(self, *args, **kwargs):
                self.posts = []
                Client.last = self
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                return False
            async def get(self, url):
                self.get_url = url
                return Response(200, {"settings": {"proactiveVisionEnabled": True}}, 'W/"7"')
            async def post(self, url, json=None, headers=None):
                self.posts.append((url, json, headers))
                return Response(200, {"settings": {"proactiveVisionEnabled": False}})

        obj = object.__new__(mod.XiaoYuInteractionPolicyPlugin)
        fake_config = types.ModuleType("config")
        fake_config.MAIN_SERVER_PORT = 48911
        with patch.dict(sys.modules, {"config": fake_config}), patch.object(mod.httpx, "AsyncClient", Client):
            previous = await obj._write_native_vision_enabled(False)

        self.assertTrue(previous)
        client = Client.last
        self.assertTrue(client.get_url.endswith("/api/config/conversation-settings"))
        self.assertEqual(
            client.posts,
            [(
                "http://127.0.0.1:48911/api/config/conversation-settings",
                {"proactiveVisionEnabled": False},
                {"If-Match": 'W/"7"'},
            )],
        )


if __name__ == "__main__":
    unittest.main()
