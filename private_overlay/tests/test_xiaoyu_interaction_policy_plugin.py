import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timezone
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

    def test_activitywatch_bucket_pair_prefers_requested_host(self):
        buckets = {
            "aw-watcher-window_A": {"type": "currentwindow", "hostname": "A", "last_updated": "2"},
            "aw-watcher-afk_A": {"type": "afkstatus", "hostname": "A", "last_updated": "2"},
            "aw-watcher-window_B": {"type": "currentwindow", "hostname": "B", "last_updated": "3"},
            "aw-watcher-afk_B": {"type": "afkstatus", "hostname": "B", "last_updated": "3"},
        }
        self.assertEqual(
            mod._select_activitywatch_buckets(buckets, "A"),
            ("aw-watcher-window_A", "aw-watcher-afk_A"),
        )

    def test_activitywatch_report_strips_titles_and_keeps_app_durations(self):
        start = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc)
        result = {
            "raw": [
                {"timestamp": "2026-11-20T10:00:00+00:00", "duration": 60, "data": {"app": "PyCharm.exe", "title": "secret.py"}},
            ],
            "events": [
                {"timestamp": "2026-11-20T10:00:00+00:00", "duration": 60, "data": {"app": "PyCharm.exe", "title": "secret.py"}},
            ],
            "apps": [
                {"timestamp": "2026-11-20T10:00:00+00:00", "duration": 60, "data": {"app": "PyCharm.exe", "title": "secret.py"}},
            ],
            "active_seconds": 60,
        }
        report = mod._activitywatch_report_from_result(
            result,
            minutes=1,
            requested_start=start,
            requested_end=end,
            version="v0.14.3",
        )
        blob = json.dumps(report, ensure_ascii=False)
        self.assertTrue(report["coverage"]["complete"])
        self.assertEqual(report["summary"]["by_app_seconds"]["PyCharm.exe"], 60.0)
        self.assertIn("PyCharm.exe", blob)
        self.assertNotIn("secret.py", blob)
        self.assertNotIn('"title"', blob)
        self.assertIn("ActivityWatch", report["evidence_policy"])

    def test_activitywatch_partial_coverage_is_unknown_not_inactivity(self):
        start = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc)
        report = mod._activitywatch_report_from_result(
            {"raw": [], "events": [], "apps": [], "active_seconds": 0},
            minutes=1,
            requested_start=start,
            requested_end=end,
            version="v0.14.3",
        )
        self.assertFalse(report["coverage"]["complete"])
        self.assertIn("UNKNOWN", report["evidence_policy"])
        self.assertIn("AFK", report["evidence_policy"])

    def test_recent_activity_llm_tool_is_role_scoped_and_activitywatch_backed(self):
        method = mod.XiaoYuInteractionPolicyPlugin.xiaoyu_recent_activity
        meta = method.__test_llm_tool_meta__
        self.assertEqual(meta["name"], "xiaoyu_recent_activity")
        self.assertEqual(meta["role"], "XiaoYu")
        self.assertEqual(meta["timeout"], 5.0)
        self.assertEqual(meta["parameters"]["properties"]["minutes"]["maximum"], 1440)
        self.assertIn("ActivityWatch", meta["description"])
        self.assertIn("missing coverage is unknown", meta["description"])



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
