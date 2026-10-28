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
from model_adapter import load_provider,save_provider,chat

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

    def test_model_adapter_mock_no_remote_call(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*a): return b'{"choices":[{"message":{"content":"hello"}}],"usage":{"completion_tokens":3}}'
        with patch.dict(os.environ,{"DEEPSEEK_API_KEY":"DO_NOT_EXPORT_TEST_SECRET"}):
            with patch.object(urllib.request,"urlopen",return_value=FakeResponse()) as mocked:
                msg, usage=chat(load_provider(self.home),[{"role":"user","content":"你好"}])
                self.assertEqual(msg,"hello")
                self.assertEqual(usage["completion_tokens"],3)
                self.assertIn("Bearer DO_NOT_EXPORT_TEST_SECRET",mocked.call_args[0][0].get_header("Authorization"))
        archive=self.s.export(self.home/"out.zip")
        self.assertNotIn("DO_NOT_EXPORT_TEST_SECRET",archive.read_bytes().decode("latin1"))

if __name__=="__main__": unittest.main(verbosity=2)
