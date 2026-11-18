# -*- coding: utf-8 -*-
"""Offline regression tests. No real API calls and no writes outside temporary dirs."""
import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
from identity_core import IdentityStore
from model_adapter import load_provider,save_provider,chat,project_history

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.home=Path(self.tmp.name)/"fish"
        self.home.mkdir()
        (self.home/"MEMORY.md").write_text(
            "# Memory\n- 用户说希望跨模型保留回忆。\n- 偏好简洁中文。\n",encoding="utf-8")
        (self.home/"fish_data.json").write_text(json.dumps({
            "name":"小鱼","bond":7,"chat":[
                {"role":"user","content":"第一次见面"},
                {"role":"assistant","content":"你好！"}]}),encoding="utf-8")
        self.s=IdentityStore(self.home)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_migration_is_idempotent_and_history_persists(self):
        before=self.s.verify()
        self.assertEqual(self.s.state()["bond"],7)
        self.assertEqual([x["content"] for x in self.s.latest_dialog()],["第一次见面","你好！"])
        self.s.close()
        self.s=IdentityStore(self.home)
        self.assertEqual(self.s.verify()["events"],before["events"])
        self.assertEqual(self.s.verify()["identity_id"],before["identity_id"])

    def test_long_term_recall_and_growth_revision(self):
        self.s.add_memory("喜欢晚上听安静的音乐",category="preference",priority=5)
        self.assertIn("喜欢晚上",self.s.recall("晚上听音乐")[0]["text"])
        ver=self.s.verify()["persona_versions"]
        self.s.propose_growth("尚未经证实：更爱讲笑话。",confirmed=False)
        self.assertEqual(self.s.verify()["persona_versions"],ver)
        ev1=self.s.record("conversation.user","user","我们一起玩游戏吧")
        ev2=self.s.record("conversation.assistant","assistant","好呀，一起玩！")
        self.s.propose_growth("我们在共同游戏中逐渐学会配合。",[ev1,ev2],confirmed=True)
        self.assertEqual(self.s.verify()["persona_versions"],ver+1)
        self.assertEqual(len(self.s.persona()["growth_notes"]),1)

    def test_archive_and_export_import_same_identity(self):
        mid=self.s.add_memory("只保留重要记忆")
        self.s.archive_memory(mid)
        self.assertFalse(any(x["memory_id"]==mid for x in self.s.list_memories()))
        original=self.s.snapshot()
        out=self.s.export(self.home/"exports"/"backup.zip")
        imported_home=Path(self.tmp.name)/"restored"
        IdentityStore.import_to_new_home(out,imported_home)
        restored=IdentityStore(imported_home)
        try:
            self.assertEqual(restored.verify()["integrity"],"ok")
            self.assertEqual(restored.persona()["id"],self.s.persona()["id"])
            self.assertEqual(restored.snapshot(),original)
        finally:
            restored.close()
        with self.assertRaises(FileExistsError):
            IdentityStore.import_to_new_home(out,imported_home)

    def test_provider_switch_does_not_touch_identity(self):
        ident=self.s.verify()["identity_id"]
        save_provider(self.home,"openai","gpt-4.1-mini")
        self.assertEqual(load_provider(self.home)["provider"],"openai")
        save_provider(self.home,"deepseek","deepseek-flash")
        self.assertEqual(self.s.verify()["identity_id"],ident)
        qwen=save_provider(self.home,"qwen","qwen3.8-flash")
        self.assertEqual(qwen["key_env"],"DASHSCOPE_API_KEY")
        self.assertIs(qwen["enable_thinking"],False)
        self.assertEqual(load_provider(self.home)["provider"],"qwen")
        self.assertEqual(self.s.verify()["identity_id"],ident)

    def test_project_history_marks_corrected_and_retracted_sources(self):
        corrected_event=self.s.record("conversation.user","user","我现在住在苏州")
        corrected_mid=self.s.add_memory(
            "我现在住在苏州",category="shared",priority=5,source_event=corrected_event
        )
        active_event=self.s.record("conversation.user","user","我喜欢安静的鞋")
        self.s.add_memory(
            "我喜欢安静的鞋",category="preference",priority=5,source_event=active_event
        )
        retract_event=self.s.record("conversation.user","user","我喜欢薄荷茶")
        retract_mid=self.s.add_memory(
            "我喜欢薄荷茶",category="preference",priority=4,source_event=retract_event
        )
        self.s.correct_memory(corrected_mid,"我现在住在上海")
        self.s.retract_memory(retract_mid)

        raw={x["event_id"]:x for x in self.s.latest_dialog(16)}
        projected={x["event_id"]:x for x in project_history(self.s,16)}

        self.assertEqual(raw[corrected_event]["content"],"我现在住在苏州")
        self.assertEqual(raw[retract_event]["content"],"我喜欢薄荷茶")
        self.assertIn("已被用户更正",projected[corrected_event]["content"])
        self.assertNotIn("我现在住在苏州",projected[corrected_event]["content"])
        self.assertEqual(projected[corrected_event]["memory_state_annotation"],"superseded")
        self.assertIn("已被用户撤回",projected[retract_event]["content"])
        self.assertNotIn("我喜欢薄荷茶",projected[retract_event]["content"])
        self.assertEqual(projected[retract_event]["memory_state_annotation"],"retracted")
        self.assertEqual(projected[active_event]["content"],"我喜欢安静的鞋")
        self.assertNotIn("memory_state_annotation",projected[active_event])

    def test_project_history_marks_mixed_active_and_superseded_source(self):
        event=self.s.record(
            "conversation.user","user",
            "我现在住在苏州，而且我喜欢安静的鞋"
        )
        city=self.s.add_memory(
            "我现在住在苏州",category="shared",priority=5,source_event=event
        )
        self.s.add_memory(
            "我喜欢安静的鞋",category="preference",priority=5,source_event=event
        )
        self.s.correct_memory(city,"我现在住在上海")

        raw={x["event_id"]:x for x in self.s.latest_dialog(16)}
        projected={x["event_id"]:x for x in project_history(self.s,16)}

        self.assertEqual(
            raw[event]["content"],
            "我现在住在苏州，而且我喜欢安静的鞋",
        )
        self.assertEqual(
            projected[event]["memory_state_annotation"],
            "mixed_changed",
        )
        self.assertIn("部分长期事实后来已被更正",projected[event]["content"])
        self.assertNotIn("我现在住在苏州",projected[event]["content"])
        self.assertIn("我喜欢安静的鞋",projected[event]["content"])

    def test_project_history_fail_closed_keeps_only_current_user_turn(self):
        old_event=self.s.record(
            "conversation.user","user",
            "旧事实LEAK_TOKEN，而且还有一个仍有效的事实KEEP_TOKEN",
        )
        self.s.add_memory(
            "旧事实LEAK_TOKEN",category="shared",priority=5,source_event=old_event
        )
        self.s.add_memory(
            "仍有效的事实KEEP_TOKEN",category="shared",priority=5,source_event=old_event
        )
        current_event=self.s.record(
            "conversation.user","user","这是本轮新问题CURRENT_TOKEN"
        )

        normal=project_history(self.s,16)
        self.assertTrue(any("LEAK_TOKEN" in x["content"] for x in normal))

        fail_closed=project_history(
            self.s,16,fail_closed_current_event_id=current_event
        )
        self.assertEqual(len(fail_closed),1)
        self.assertEqual(fail_closed[0]["event_id"],current_event)
        self.assertEqual(fail_closed[0]["role"],"user")
        self.assertIn("CURRENT_TOKEN",fail_closed[0]["content"])
        self.assertNotIn("LEAK_TOKEN",fail_closed[0]["content"])
        self.assertNotIn("KEEP_TOKEN",fail_closed[0]["content"])

    def test_qwen_provider_mock_sends_nonthinking_flag(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*a): return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"total_tokens":7}}'
        config=save_provider(self.home,"qwen","qwen3.8-flash")
        with patch.dict(os.environ,{"DASHSCOPE_API_KEY":"DO_NOT_EXPORT_QWEN_SECRET"}):
            with patch.object(urllib.request,"urlopen",return_value=FakeResponse()) as mocked:
                msg, usage=chat(config,[{"role":"user","content":"test"}],max_tokens=16,required_data_class="PUBLIC")
                self.assertEqual(msg,"ok")
                self.assertEqual(usage["total_tokens"],7)
                req=mocked.call_args[0][0]
                body=json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["model"],"qwen3.8-flash")
                self.assertIs(body["enable_thinking"],False)
                self.assertIn("Bearer DO_NOT_EXPORT_QWEN_SECRET",req.get_header("Authorization"))

    def test_model_adapter_mock_no_remote_call(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*a): return b'{"choices":[{"message":{"content":"hello"}}],"usage":{"completion_tokens":3}}'
        with patch.dict(os.environ,{"DEEPSEEK_API_KEY":"DO_NOT_EXPORT_TEST_SECRET"}):
            with patch.object(urllib.request,"urlopen",return_value=FakeResponse()) as mocked:
                msg, usage=chat(load_provider(self.home),[{"role":"user","content":"你好"}],required_data_class="PUBLIC")
                self.assertEqual(msg,"hello")
                self.assertEqual(usage["completion_tokens"],3)
                self.assertIn("Bearer DO_NOT_EXPORT_TEST_SECRET",mocked.call_args[0][0].get_header("Authorization"))
        archive=self.s.export(self.home/"out.zip")
        self.assertNotIn("DO_NOT_EXPORT_TEST_SECRET",archive.read_bytes().decode("latin1"))

if __name__=="__main__": unittest.main(verbosity=2)
