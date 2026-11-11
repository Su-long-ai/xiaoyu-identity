# -*- coding: utf-8 -*-
"""Provenance, proposal approval, old export migration, continuity tests.
Entirely offline. All mutations stay inside disposable temp directories.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest

from identity_core import IdentityStore,SCHEMA_VERSION
from model_adapter import save_provider,load_provider

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.home=Path(self.temp.name)/"fish"
        self.home.mkdir()
        (self.home/"MEMORY.md").write_text(
            "# 初始设定\n- 诞生：2026-10-26。\n- 用自然中文交流。\n"
            "- 主人希望本地养鱼。\n- 当前仅用于初始陪伴。\n",encoding="utf-8")
        self.s=IdentityStore(self.home)
    def tearDown(self):
        self.s.close()
        self.temp.cleanup()

    def test_bootstrap_does_not_count_as_memory_or_shared_history(self):
        p=self.s.actual_progress()
        self.assertEqual(p["bootstrap_notes"],4)
        self.assertEqual(p["confirmed_memories"],0)
        self.assertEqual(p["user_messages"],0)
        self.assertEqual(p["assistant_replies"],0)
        self.assertEqual(self.s.recall("主人希望本地养鱼"),[])
        self.assertEqual(self.s.list_memories(),[])
        self.assertNotIn("主人希望本地养鱼",self.s.identity_context("今天做什么"))

    def test_proposal_requires_real_event_exact_literal_and_user_approval(self):
        with self.assertRaises(ValueError):
            self.s.propose_from_user_event(500,"我喜欢自然表达")
        e=self.s.record("conversation.user","user","我喜欢安静的音乐")
        with self.assertRaises(ValueError):
            self.s.propose_from_user_event(e,"我喜欢别的")
        pid=self.s.propose_from_user_event(e,"我喜欢安静的音乐")
        self.assertEqual(self.s.propose_from_user_event(e,"我喜欢安静的音乐"),pid)
        self.assertEqual(self.s.actual_progress()["pending_candidates"],1)
        self.assertEqual(self.s.actual_progress()["confirmed_memories"],0)
        self.assertEqual(self.s.recall("音乐"),[])
        proposal=self.s.list_proposals()[0]
        self.assertEqual(proposal["source_event"],e)
        self.assertEqual(proposal["evidence_text"],"我喜欢安静的音乐")
        self.s.review_proposal(pid,True)
        self.assertEqual(self.s.actual_progress()["confirmed_memories"],1)
        self.assertEqual(self.s.actual_progress()["pending_candidates"],0)
        self.assertIn("安静",self.s.recall("音乐")[0]["text"])
        with self.assertRaises(ValueError):
            self.s.review_proposal(pid,True)

    def test_rejection_is_not_remembering(self):
        e=self.s.record("conversation.user","user","请记住：我偏好简洁的中文")
        proposal_id=self.s.propose_from_user_event(e,"请记住：我偏好简洁的中文")
        self.assertIsNotNone(proposal_id)
        self.s.review_proposal(proposal_id,False)
        self.assertEqual(self.s.actual_progress()["confirmed_memories"],0)
        self.assertEqual(self.s.list_memories(),[])
        self.assertEqual(self.s.list_proposals("rejected")[0]["source_event"],e)

    def test_unsupported_statements_do_not_generate_memory(self):
        for t in ("你好","下雨了吗？","我喜欢什么？","请替我写个程序","我现在想知道天气"):
            e=self.s.record("conversation.user","user",t)
            self.assertIsNone(self.s.propose_from_user_event(e,t))
        self.assertEqual(self.s.actual_progress()["pending_candidates"],0)

    def test_growth_rejects_fabricated_evidence(self):
        with self.assertRaises(ValueError):
            self.s.propose_growth("变得熟悉对方",[],True)
        e=self.s.record("system.migration","system","unrelated")
        e2=self.s.record("system.provenance_migration","system","also unrelated")
        with self.assertRaises(ValueError):
            self.s.propose_growth("变得熟悉对方",[e,e2],True)
        first=self.s.record("conversation.user","user","一起玩吧")
        second=self.s.record("pet.play","user","play")
        self.s.propose_growth("共同游戏中更默契了",[first,second],True)
        self.assertEqual(self.s.actual_progress()["approved_growth"],1)

    def test_export_with_pending_and_model_switch_keeps_identity(self):
        e=self.s.record("conversation.user","user","我希望明天也能见到小鱼")
        self.s.propose_from_user_event(e,"我希望明天也能见到小鱼")
        start=self.s.persona()["id"]
        save_provider(self.home,"ollama","qwen3:8b")
        self.assertEqual(self.s.persona()["id"],start)
        self.assertEqual(self.s.actual_progress()["pending_candidates"],1)
        export=self.s.export(self.home/"exports"/"xiaoyu-v2.zip")
        target=Path(self.temp.name)/"roundtrip"
        IdentityStore.import_to_new_home(export,target)
        restored=IdentityStore(target)
        try:
            self.assertEqual(restored.persona()["id"],start)
            self.assertEqual(restored.actual_progress()["pending_candidates"],1)
            self.assertEqual(restored.actual_progress()["confirmed_memories"],0)
            self.assertEqual(restored.verify()["integrity"],"ok")
        finally:restored.close()
        # provider config lives outside the portable export
        self.assertFalse((target/"provider.json").exists())

    def test_preexisting_v1_archive_restores_under_v2(self):
        # Real pre-upgrade export on current local system, if available.
        source=Path("D:/dsh-fish/exports/xiaoyu-initial-20261026.zip")
        if not source.exists():
            self.skipTest("No preexisting v1 archive in local workspace")
        target=Path(self.temp.name)/"from_v1"
        IdentityStore.import_to_new_home(source,target)
        restored=IdentityStore(target)
        try:
            p=restored.actual_progress()
            self.assertEqual(p["bootstrap_notes"],4)
            self.assertEqual(p["confirmed_memories"],0)
            self.assertEqual(restored.verify()["integrity"],"ok")
            self.assertEqual(restored._get("schema_version"),SCHEMA_VERSION)
        finally:restored.close()


    def test_explicitly_invalidated_proposal_requires_current_reconfirmation(self):
        old="我喜欢绿茶"
        e1=self.s.record("conversation.user","user",old)
        p1=self.s.propose_from_user_event(e1,old)
        self.s.record(
            "conversation.user","user","我不喜欢绿茶了",
            {"invalidates_source_event":e1,"memory_action":"RETRACT"},
        )
        fresh=self.s.proposal_freshness(p1)
        self.assertTrue(fresh["requires_reconfirmation"])
        self.assertEqual(fresh["reason"],"explicit_source_invalidation")
        with self.assertRaisesRegex(ValueError,"explicit current reconfirmation"):
            self.s.review_proposal(p1,True)
        self.assertEqual(self.s.list_proposals()[0]["proposal_id"],p1)
        self.s.review_proposal(p1,True,reconfirm_stale=True)
        memory=self.s.conn.execute(
            "SELECT text,source_event FROM memories WHERE text=? AND status='active'",
            (old,),
        ).fetchone()
        self.assertIsNotNone(memory)
        self.assertNotEqual(int(memory["source_event"]),e1)
        source=self.s.conn.execute(
            "SELECT kind,actor,content,extra FROM events WHERE event_id=?",
            (int(memory["source_event"]),),
        ).fetchone()
        self.assertEqual(source["kind"],"memory.saved")
        self.assertEqual(source["actor"],"user")
        self.assertEqual(source["content"],old)
        extra=json.loads(source["extra"])
        self.assertEqual(extra["original_source_event"],e1)
        self.assertEqual(extra["reconfirmed_from_proposal_id"],p1)

    def test_newer_confirmed_preference_blocks_old_one_click_promotion(self):
        old="我喜欢绿茶"
        new="我更喜欢乌龙茶"
        e1=self.s.record("conversation.user","user",old)
        p1=self.s.propose_from_user_event(e1,old)
        e2=self.s.record("conversation.user","user",new)
        p2=self.s.propose_from_user_event(e2,new)
        self.s.review_proposal(p2,True)
        fresh=self.s.proposal_freshness(p1)
        self.assertTrue(fresh["requires_reconfirmation"])
        self.assertEqual(fresh["reason"],"newer_confirmed_preference_exists")
        self.assertEqual(fresh["newer_proposal_id"],p2)
        with self.assertRaisesRegex(ValueError,"explicit current reconfirmation"):
            self.s.review_proposal(p1,True)
        active=[x["text"] for x in self.s.list_memories()]
        self.assertEqual(active,[new])
        self.s.review_proposal(p1,True,reconfirm_stale=True)
        active={x["text"] for x in self.s.list_memories()}
        self.assertEqual(active,{old,new})
        row=self.s.conn.execute(
            "SELECT source_event FROM memories WHERE text=? AND status='active'",(old,)
        ).fetchone()
        self.assertGreater(int(row["source_event"]),e2)
        kind=self.s.conn.execute(
            "SELECT kind FROM events WHERE event_id=?",(int(row["source_event"]),)
        ).fetchone()["kind"]
        self.assertEqual(kind,"memory.saved")

    def test_unrelated_and_explicit_reaffirmation_preserve_pending_freshness(self):
        old="我喜欢绿茶"
        e1=self.s.record("conversation.user","user",old)
        p1=self.s.propose_from_user_event(e1,old)
        self.s.record("conversation.user","user","我喜欢散步",{"topic":"unrelated"})
        self.assertFalse(self.s.proposal_freshness(p1)["requires_reconfirmation"])
        self.s.record(
            "conversation.user","user",old,
            {"reaffirms_source_event":e1},
        )
        fresh=self.s.proposal_freshness(p1)
        self.assertFalse(fresh["requires_reconfirmation"])
        self.assertEqual(fresh["reason"],"explicit_source_reaffirmation")
        self.s.review_proposal(p1,True)
        row=self.s.conn.execute(
            "SELECT source_event FROM memories WHERE text=? AND status='active'",(old,)
        ).fetchone()
        self.assertEqual(int(row["source_event"]),e1)

    def test_pending_staleness_survives_export_restore(self):
        old="我喜欢绿茶"
        new="我更喜欢乌龙茶"
        e1=self.s.record("conversation.user","user",old)
        p1=self.s.propose_from_user_event(e1,old)
        e2=self.s.record("conversation.user","user",new)
        p2=self.s.propose_from_user_event(e2,new)
        self.s.review_proposal(p2,True)
        archive=self.s.export(self.home/"exports"/"proposal-freshness.zip")
        target=Path(self.temp.name)/"proposal-freshness-restored"
        IdentityStore.import_to_new_home(archive,target)
        restored=IdentityStore(target)
        try:
            fresh=restored.proposal_freshness(p1)
            self.assertTrue(fresh["requires_reconfirmation"])
            self.assertEqual(fresh["reason"],"newer_confirmed_preference_exists")
            with self.assertRaisesRegex(ValueError,"explicit current reconfirmation"):
                restored.review_proposal(p1,True)
            self.assertEqual(
                {x["text"] for x in restored.list_memories()},
                {new},
            )
        finally:
            restored.close()

if __name__=="__main__":
    unittest.main(verbosity=2)
