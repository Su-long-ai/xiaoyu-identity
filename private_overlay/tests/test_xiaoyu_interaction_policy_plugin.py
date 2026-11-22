import asyncio
import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
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
sdk.on_event = _identity
def _plugin_entry(*_a, **kwargs):
    def decorate(obj):
        obj.__test_plugin_entry_meta__ = dict(kwargs)
        return obj
    return decorate
sdk.plugin_entry = _plugin_entry
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


class ModelGatewayClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_uses_declared_native_model_usage(self):
        calls = []

        class Completions:
            async def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"action":"quiet","duration_minutes":null,"speech_action":"mute","vision_action":"unchanged"}'
                            )
                        )
                    ]
                )

        class Models:
            async def get_client(self):
                return SimpleNamespace(
                    chat=SimpleNamespace(completions=Completions())
                )

        plugin = object.__new__(mod.XiaoYuInteractionPolicyPlugin)
        plugin.ctx = SimpleNamespace(models=Models())
        plugin.logger = SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
        )

        result = await plugin._classify("别说话")
        self.assertEqual(result["action"], "quiet")
        self.assertEqual(result["speech_action"], "mute")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], mod._CLASSIFIER_MODEL_USAGE)
        self.assertEqual(calls[0]["model"], "interaction_classifier")
        self.assertEqual(calls[0]["temperature"], 0.0)
        self.assertLessEqual(calls[0]["max_tokens"], 96)
        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        self.assertEqual(calls[0]["messages"][1], {"role": "user", "content": "别说话"})


class InterruptibilityCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_shadow_provider_abstains_and_returns_bounded_evidence(self):
        async def fake_recent(_minutes):
            return {
                "source": "ActivityWatch",
                "coverage": {"complete": True},
                "summary": {
                    "active_seconds": 73.25,
                    "by_app_seconds": {"private-game.exe": 70.0},
                },
                "segments": [{"app": "private-game.exe"}],
            }

        plugin = object.__new__(mod.XiaoYuInteractionPolicyPlugin)
        with patch.object(mod, "query_activitywatch_recent", new=fake_recent):
            result = await plugin.interruptibility_v1(
                activity_state="gaming",
                notification_state=3,
                os_signals_available=True,
                allow_focused_work=False,
                native_block_reason="windows_notification_state:3",
            )

        payload = result.value
        self.assertEqual(payload["contract"], "interruptibility.v1")
        self.assertEqual(payload["decision"], "abstain")
        self.assertEqual(payload["reason"], "activitywatch_shadow_evidence_only")
        self.assertTrue(payload["native"]["blocked"])
        self.assertEqual(
            payload["evidence"],
            {
                "source": "ActivityWatch",
                "available": True,
                "coverage_complete": True,
                "active_seconds": 73.25,
            },
        )
        self.assertNotIn("by_app_seconds", payload["evidence"])
        self.assertNotIn("segments", payload["evidence"])

        meta = mod.XiaoYuInteractionPolicyPlugin.interruptibility_v1.__test_plugin_entry_meta__
        self.assertEqual(meta["id"], "interruptibility_v1")
        self.assertTrue(meta["metadata"]["agent_hidden"])



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

    def test_v5_state_normalization_collapses_legacy_speech_mute_and_adds_conversation_cursor(self):
        state = mod._normalize_state({
            "version": 1,
            "quiet": True,
            "speech_muted": True,
            "previous_proactive_chat_enabled": True,
        })
        self.assertEqual(state["version"], 5)
        self.assertTrue(state["quiet"])
        self.assertFalse(state["speech_muted"])
        self.assertFalse(state["vision_blocked"])
        self.assertFalse(state["conversation_cursor_initialized"])
        self.assertIsNone(state["last_conversation_observed_at"])
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
        for phrase in ("说吧", "你说吧", "那你说吧", "那就说吧", "可以说了"):
            self.assertEqual(
                mod.fast_speech_control(phrase),
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

    def test_semantic_hard_gate_rejects_speed_and_audio_diagnostics(self):
        bad = {
            "action": "quiet",
            "duration_minutes": None,
            "speech_action": "mute",
            "vision_action": "unchanged",
        }
        for text in (
            "语速还是太快了",
            "你说话真的太快了",
            "这次还是没声音",
            "怎么没声音",
            "预览有声，但是回复又快了",
            "预览有声，但是回复没声音",
        ):
            self.assertEqual(
                mod.gate_semantic_hard_control(text, bad),
                {
                    "action": "none",
                    "duration_minutes": None,
                    "speech_action": "unchanged",
                    "vision_action": "unchanged",
                },
                text,
            )

    def test_semantic_hard_gate_allows_explicit_novel_speech_controls(self):
        self.assertEqual(
            mod.gate_semantic_hard_control(
                "你先别开口了",
                {
                    "action": "quiet",
                    "duration_minutes": None,
                    "speech_action": "mute",
                    "vision_action": "unchanged",
                },
            ),
            {
                "action": "quiet",
                "duration_minutes": None,
                "speech_action": "mute",
                "vision_action": "unchanged",
            },
        )
        self.assertEqual(
            mod.gate_semantic_hard_control(
                "好了，你可以开口了",
                {
                    "action": "resume",
                    "duration_minutes": None,
                    "speech_action": "unmute",
                    "vision_action": "unchanged",
                },
            ),
            {
                "action": "resume",
                "duration_minutes": None,
                "speech_action": "unmute",
                "vision_action": "unchanged",
            },
        )

    def test_semantic_hard_gate_allows_talk_to_me_again(self):
        self.assertEqual(
            mod.gate_semantic_hard_control(
                "You can talk to me again now.",
                {
                    "action": "resume",
                    "duration_minutes": None,
                    "speech_action": "unmute",
                    "vision_action": "unchanged",
                },
            ),
            {
                "action": "resume",
                "duration_minutes": None,
                "speech_action": "unmute",
                "vision_action": "unchanged",
            },
        )
    def test_semantic_hard_gate_separates_proactive_from_speech_mute(self):
        self.assertEqual(
            mod.gate_semantic_hard_control(
                "暂时不要主动联系我",
                {
                    "action": "quiet",
                    "duration_minutes": 10,
                    "speech_action": "mute",
                    "vision_action": "unchanged",
                },
            ),
            {
                "action": "quiet",
                "duration_minutes": 10,
                "speech_action": "unchanged",
                "vision_action": "unchanged",
            },
        )

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
        self.assertFalse(state["speech_muted"])

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



class ReplyOutputContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_speech_controls_toggle_only_whole_reply_quiet(self):
        obj = object.__new__(mod.XiaoYuInteractionPolicyPlugin)
        obj.logger = types.SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
        obj._save_state = lambda _state: None
        proactive_writes = []

        async def current_proactive():
            return True

        async def set_proactive(enabled):
            proactive_writes.append(bool(enabled))

        obj._current_proactive_enabled = current_proactive
        obj._set_proactive = set_proactive

        state = mod._normalize_state({"initialized": True})
        state, decisions = await obj._apply_control_text(state, "别说话", reason="user")
        self.assertEqual(decisions, 1)
        self.assertTrue(state["quiet"])
        self.assertFalse(state["speech_muted"])
        self.assertEqual(proactive_writes, [False])

        state, decisions = await obj._apply_control_text(state, "说吧", reason="user")
        self.assertEqual(decisions, 1)
        self.assertFalse(state["quiet"])
        self.assertFalse(state["speech_muted"])
        self.assertEqual(proactive_writes, [False, True])


class CrossLoopLockTests(unittest.TestCase):
    def test_lock_can_be_reused_across_distinct_asyncio_event_loops(self):
        lock = mod._CrossLoopAsyncLock()
        seen = []

        async def once(label):
            async with lock:
                self.assertTrue(lock.locked())
                seen.append(label)
            self.assertFalse(lock.locked())

        asyncio.run(once("first"))
        asyncio.run(once("second"))
        self.assertEqual(seen, ["first", "second"])


class ConversationWatcherTests(unittest.IsolatedAsyncioTestCase):
    def _message(self, message_id, text, observed_at):
        return types.SimpleNamespace(
            id=message_id,
            text=text,
            observed_at=float(observed_at),
            input_source="text",
        )

    def _obj_with_state(self, state):
        obj = object.__new__(mod.XiaoYuInteractionPolicyPlugin)
        obj._lock = mod._CrossLoopAsyncLock()
        obj._conversation_watcher = None
        obj.logger = types.SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
        )
        holder = {"state": mod._normalize_state(state)}
        obj._load_state = lambda: dict(holder["state"])

        def save(value):
            holder["state"] = mod._normalize_state(dict(value))
        obj._save_state = save

        async def expire(value):
            return value
        obj._expire_if_needed = expire

        async def enforce(_value):
            return None
        obj._enforce_quiet_if_needed = enforce
        return obj, holder

    async def test_explicit_baseline_does_not_replay_old_controls(self):
        obj, holder = self._obj_with_state({"initialized": True})
        records = (
            self._message("m2", "说吧", 20),
            self._message("m1", "别说话", 10),
        )

        async def get(**kwargs):
            self.assertEqual(kwargs["order"], "desc")
            self.assertEqual(kwargs["max_count"], 20)
            return records

        obj.bus = types.SimpleNamespace(
            conversations_v2=types.SimpleNamespace(get=get)
        )
        applied = []

        async def apply(value, text, *, reason):
            applied.append((text, reason))
            return value, 1
        obj._apply_control_text = apply

        await obj._baseline_conversation_cursor()

        self.assertEqual(applied, [])
        self.assertTrue(holder["state"]["conversation_cursor_initialized"])
        self.assertEqual(holder["state"]["last_conversation_observed_at"], 20.0)
        self.assertEqual(holder["state"]["seen_event_ids"][-2:], ["m1", "m2"])

    async def test_new_record_is_processed_once_after_baseline(self):
        obj, holder = self._obj_with_state({
            "initialized": True,
            "conversation_cursor_initialized": True,
            "last_conversation_observed_at": 10.0,
            "seen_event_ids": ["m1"],
        })
        applied = []

        async def apply(value, text, *, reason):
            applied.append((text, reason))
            value["last_action"] = "tested"
            return value, 1
        obj._apply_control_text = apply

        message = self._message("m2", "你先别主动找我", 11)
        await obj._conversation_control_record(message)
        await obj._conversation_control_record(message)

        self.assertEqual(applied, [("你先别主动找我", "text")])
        self.assertEqual(holder["state"]["last_conversation_observed_at"], 11.0)
        self.assertIn("m2", holder["state"]["seen_event_ids"])

    async def test_active_reconcile_timer_does_not_self_deadlock(self):
        obj, holder = self._obj_with_state({
            "initialized": True,
            "conversation_cursor_initialized": True,
        })
        obj._conversation_watcher = types.SimpleNamespace(_active=True)
        entered = []

        async def reconcile():
            async with obj._lock:
                entered.append(True)
        obj._reconcile_state = reconcile

        result = await asyncio.wait_for(
            obj.reconcile_interaction_state(),
            timeout=0.25,
        )
        self.assertEqual(entered, [True])
        self.assertEqual(result.value["watcher"], "active")
        self.assertFalse(holder["state"]["quiet"])

    def test_text_control_source_is_event_driven_not_one_second_memory_polling(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("self.bus.conversations_v2.watch(", source)
        self.assertIn('subscribe(on="record")', source)
        self.assertIn("self.bus.conversations_v2.get(", source)
        self.assertIn('seconds=30', source)
        self.assertNotIn("self.bus.memory.get(", source)
        self.assertNotIn('subscribe(on="change")', source)
        self.assertNotIn('seconds=1, auto_start=True', source)


class VoiceControlEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_transcript_uses_same_control_path(self):
        obj = object.__new__(mod.XiaoYuInteractionPolicyPlugin)
        obj._lock = asyncio.Lock()
        state = mod._normalize_state({
            "initialized": True,
            "quiet": True,
            "speech_muted": True,
            "previous_proactive_chat_enabled": True,
        })
        obj._load_state = lambda: dict(state)

        async def expire(value):
            return value
        obj._expire_if_needed = expire

        seen = {}
        async def apply(value, text, *, reason):
            seen["text"] = text
            seen["reason"] = reason
            value["quiet"] = False
            value["speech_muted"] = False
            value["last_action"] = "speech_unmute:voice"
            return value, 2
        obj._apply_control_text = apply

        async def enforce(_value):
            seen["enforced"] = True
        obj._enforce_quiet_if_needed = enforce

        result = await obj.voice_control_intent(
            transcript="那你说吧",
            lanlan_name="XiaoYu",
        )
        self.assertEqual(seen["text"], "那你说吧")
        self.assertEqual(seen["reason"], "voice")
        self.assertTrue(seen["enforced"])
        self.assertEqual(result.value["decisions"], 2)
        self.assertFalse(result.value["quiet"])
        self.assertFalse(result.value["speech_muted"])



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
