# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from identity_core import IdentityStore
from product_memory_bridge import EXPECTED, ProductMemoryBridge, safe_product_recall
from model_adapter import load_provider, save_provider, project_history


ROOT = Path(__file__).resolve().parent


class ProductMemoryBridgeTests(unittest.TestCase):
    def test_product_component_is_runtime_independent_of_governance_tree(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            sandbox = Path(td)
            component_root = sandbox / "component_root"
            shutil.copytree(
                ROOT / "product_components",
                component_root / "product_components",
            )
            self.assertFalse((component_root / "governance").exists())
            home = sandbox / "home"
            store = IdentityStore(home)
            mid = store.add_memory(
                "I prefer low profile quiet shoes",
                category="preference",
                priority=5,
            )
            bridge = ProductMemoryBridge(
                home, store, component_root=component_root
            )
            try:
                rows = bridge.recall("quiet shoes", limit=7)
                self.assertTrue(any(x["memory_id"] == mid for x in rows))
                self.assertIn(
                    "product_components",
                    str(bridge.frozen).replace("\\", "/"),
                )
            finally:
                bridge.close()
                store.close()

    def test_confirmed_memory_correction_retraction_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            identity_id = store.persona()["id"]

            first = store.add_memory("我现在喜欢无糖拿铁", category="preference", priority=5)
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                rows = bridge.recall("我喜欢喝什么", limit=7)
                self.assertTrue(any(x["memory_id"] == first for x in rows))
                self.assertTrue(all(x["authority"] == "user_state" for x in rows))
                self.assertEqual(bridge.status()["provider_calls"], 0)
                self.assertFalse(bridge.status()["private_data_uploaded"])

                second = store.correct_memory(first, "我现在更喜欢美式咖啡")
                bridge.sync()
                current = bridge.pipeline.current_rows()
                texts = [x["text"] for x in current]
                self.assertNotIn("我现在喜欢无糖拿铁", texts)
                self.assertIn("我现在更喜欢美式咖啡", texts)
                rows = bridge.recall("我喜欢什么咖啡", limit=7)
                self.assertTrue(any(x["memory_id"] == second for x in rows))

                self.assertTrue(store.retract_memory(second))
                bridge.sync()
                self.assertNotIn("我现在更喜欢美式咖啡",
                                 [x["text"] for x in bridge.pipeline.current_rows()])
                self.assertEqual(bridge.recall("我喜欢什么咖啡", limit=7), [])
            finally:
                bridge.close()
                store.close()

            # Provider/model changes are deliberately outside the identity DB. Reopen
            # the same identity and bridge to prove persisted continuity.
            store2 = IdentityStore(home)
            self.assertEqual(store2.persona()["id"], identity_id)
            third = store2.add_memory("我平时用PyCharm写Python项目", category="shared", priority=4)
            bridge2 = ProductMemoryBridge(home, store2, component_root=ROOT)
            try:
                rows = bridge2.recall("我用什么写Python", limit=7)
                self.assertTrue(any(x["memory_id"] == third for x in rows))
                runtime_status = bridge2.status()
                self.assertEqual(
                    runtime_status["runtime_memory_core"],
                    "r47_confirmed_product_adapter",
                )
                self.assertEqual(
                    runtime_status["runtime_core_sha256"],
                    EXPECTED["r47_open_domain_memory_store_frozen.py"],
                )
                self.assertFalse(runtime_status["r52_runtime_loaded"])
                self.assertNotIn("r52_sha256", runtime_status)
            finally:
                bridge2.close()
                store2.close()

    def test_context_accepts_bridge_authority_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            mid = store.add_memory("我偏好安静的走路鞋", category="preference", priority=5)
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                memories = bridge.recall("我的鞋子偏好", limit=7)
                ctx = store.identity_context("我的鞋子偏好", memories_override=memories)
                self.assertIn("我偏好安静的走路鞋", ctx)
                self.assertIn("user_state", ctx)
                self.assertIn(f"memory:{mid}", ctx)
            finally:
                bridge.close()
                store.close()


    def test_export_import_rebuilds_bridge_without_ghosts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            home.mkdir()
            store = IdentityStore(home)
            old = store.add_memory("我现在住在苏州", category="shared", priority=5)
            keep = store.add_memory("我的鸟叫Pippin", category="shared", priority=4)
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                new = store.correct_memory(old, "我现在住在上海")
                doomed = store.add_memory("我临时喜欢薄荷茶", category="preference", priority=3)
                self.assertTrue(store.retract_memory(doomed))
                bridge.sync()
                self.assertFalse(any("苏州" in x["text"] for x in bridge.recall("我住哪里", limit=7)))
                self.assertTrue(any(x["memory_id"] == new for x in bridge.recall("我住哪里 上海", limit=7)))
                self.assertEqual(bridge.recall("薄荷茶", limit=7), [])
                archive = root / "identity.zip"
                store.export(archive)
                identity_id = store.persona()["id"]
            finally:
                bridge.close()
                store.close()

            restored = root / "restored"
            IdentityStore.import_to_new_home(archive, restored)
            store2 = IdentityStore(restored)
            bridge2 = ProductMemoryBridge(restored, store2, component_root=ROOT)
            try:
                self.assertEqual(store2.persona()["id"], identity_id)
                rows = bridge2.recall("我住哪里 上海 苏州", limit=7)
                texts = [x["text"] for x in rows]
                self.assertIn("我现在住在上海", texts)
                self.assertNotIn("我现在住在苏州", texts)
                self.assertFalse(any("薄荷茶" in x for x in texts))
                self.assertTrue(any(x["memory_id"] == keep for x in bridge2.recall("Pippin 鸟", limit=7)))
            finally:
                bridge2.close()
                store2.close()

    def test_in_place_text_drift_is_quarantined_not_reindexed(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            mid = store.add_memory("我使用PyCharm写Python", category="shared", priority=5)
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                self.assertTrue(any(x["memory_id"] == mid for x in bridge.recall("PyCharm Python", limit=7)))
                # Simulate an out-of-contract in-place mutation bypassing correct_memory().
                with store.conn:
                    store.conn.execute(
                        "UPDATE memories SET text=?,updated_at=? WHERE memory_id=?",
                        ("我使用未知编辑器写Python", "9999-12-31T23:59:59+00:00", mid),
                    )
                result = bridge.sync()
                self.assertTrue(any("source_text_drift_quarantined" in x for x in result["warnings"]))
                self.assertEqual(bridge.recall("未知编辑器 Python", limit=7), [])
                self.assertEqual(bridge.recall("PyCharm Python", limit=7), [])
                meta = bridge.index.execute(
                    "SELECT status FROM product_memory_meta WHERE memory_id=?", (mid,)
                ).fetchone()
                self.assertIsNotNone(meta)
                self.assertEqual(meta["status"], "quarantined")
            finally:
                bridge.close()
                store.close()

    def test_full_reconcile_removes_deleted_row_and_quarantines_orphan_source(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            mid = store.add_memory("我的备用雨伞在玄关", category="shared", priority=4)
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                self.assertTrue(bridge.recall("备用雨伞 玄关", limit=7))
                sid = bridge._r47.source_message_id(
                    "xiaoyu-product-confirmed-memory", f"memory-{mid}"
                )
                with store.conn:
                    store.conn.execute("DELETE FROM memories WHERE memory_id=?", (mid,))
                result = bridge.sync()
                self.assertTrue(result["full_reconcile"])
                self.assertEqual(bridge.recall("备用雨伞 玄关", limit=7), [])
                self.assertIsNone(
                    bridge.index.execute(
                        "SELECT memory_id FROM product_memory_meta WHERE memory_id=?", (mid,)
                    ).fetchone()
                )
                src = bridge.pipeline.store._source(sid)
                self.assertIsNotNone(src)
                self.assertEqual(src["lifecycle"], "quarantined")
            finally:
                bridge.close()
                store.close()

    def test_index_v2_migrates_source_event_and_rebuilds(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            event = store.record("conversation.user", "user", "我喜欢青绿色")
            mid = store.add_memory(
                "我喜欢青绿色", category="preference", priority=5, source_event=event
            )
            index_path = home / "identity" / "product_memory_index.sqlite3"
            legacy = sqlite3.connect(str(index_path))
            try:
                legacy.executescript("""
                    CREATE TABLE index_settings(
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    INSERT INTO index_settings(key,value) VALUES
                        ('schema_version','2'),('initialized','1'),
                        ('last_updated_at',''),('last_memory_id','0'),
                        ('last_change_seq','0'),('identity_row_count','0');
                    CREATE TABLE product_memory_meta(
                        memory_id INTEGER PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        category TEXT NOT NULL,
                        text TEXT NOT NULL,
                        priority INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        source_message_id TEXT NOT NULL,
                        text_hash TEXT NOT NULL
                    );
                    CREATE VIRTUAL TABLE product_memory_fts
                        USING fts5(memory_id UNINDEXED, terms, tokenize='unicode61');
                """)
                legacy.commit()
            finally:
                legacy.close()

            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                cols = {
                    row["name"]
                    for row in bridge.index.execute(
                        "PRAGMA table_info(product_memory_meta)"
                    )
                }
                self.assertIn("source_event", cols)
                meta = bridge.index.execute(
                    "SELECT source_event,status FROM product_memory_meta "
                    "WHERE memory_id=?", (mid,)
                ).fetchone()
                self.assertIsNotNone(meta)
                self.assertEqual(int(meta["source_event"]), event)
                self.assertEqual(meta["status"], "active")
                self.assertTrue(any(
                    x["memory_id"] == mid
                    for x in bridge.recall("青绿色", limit=7)
                ))
                self.assertEqual(
                    bridge._index_get("schema_version"),
                    str(bridge.INDEX_SCHEMA_VERSION),
                )
            finally:
                bridge.close()
                store.close()

    def test_physical_delete_of_one_shared_source_sibling_is_not_reexposed(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            event = store.record(
                "conversation.user", "user",
                "我的旧饮料偏好是桂花茶DEL，且我最喜欢的颜色是青绿色KEEP。"
            )
            old = store.add_memory(
                "我的旧饮料偏好是桂花茶DEL。",
                category="preference", priority=5, source_event=event
            )
            keep = store.add_memory(
                "我最喜欢的颜色是青绿色KEEP。",
                category="shared", priority=5, source_event=event
            )
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                self.assertTrue(any(
                    x["memory_id"] == keep
                    for x in bridge.recall("青绿色 KEEP", limit=7)
                ))
                with store.conn:
                    store.conn.execute(
                        "DELETE FROM memories WHERE memory_id=?", (old,)
                    )
                result = bridge.sync()
                self.assertTrue(result["full_reconcile"])
                history = {
                    x["event_id"]: x for x in project_history(store, 16)
                }
                self.assertEqual(
                    history[event].get("memory_state_annotation"),
                    "partial_deleted",
                )
                self.assertNotIn("桂花茶DEL", history[event]["content"])
                self.assertIn("青绿色KEEP", history[event]["content"])
                tombstones = [
                    dict(x) for x in store.conn.execute(
                        "SELECT kind,content,extra FROM events "
                        "WHERE kind='memory.deleted' AND content=?",
                        (str(old),),
                    )
                ]
                self.assertEqual(len(tombstones), 1)
                self.assertNotIn("桂花茶DEL", str(tombstones[0]))
                bridge.sync()
                self.assertEqual(
                    store.conn.execute(
                        "SELECT count(*) FROM events "
                        "WHERE kind='memory.deleted' AND content=?",
                        (str(old),),
                    ).fetchone()[0],
                    1,
                )
            finally:
                bridge.close()
                store.close()

            store2 = IdentityStore(home)
            bridge2 = ProductMemoryBridge(home, store2, component_root=ROOT)
            try:
                history2 = {
                    x["event_id"]: x for x in project_history(store2, 16)
                }
                self.assertNotIn("桂花茶DEL", history2[event]["content"])
                self.assertIn("青绿色KEEP", history2[event]["content"])
                self.assertTrue(any(
                    x["memory_id"] == keep
                    for x in bridge2.recall("青绿色 KEEP", limit=7)
                ))
            finally:
                bridge2.close()
                store2.close()

    def test_scale_recall_is_bounded_and_target_survives_1500_memories(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            target = None
            for i in range(1500):
                text = f"归档标记{i}对应石英Quartz{i}"
                mid = store.add_memory(text, category="shared", priority=3)
                if i == 1377:
                    target = mid
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                start = time.perf_counter()
                results = []
                for _ in range(40):
                    rows = bridge.recall("石英 Quartz1377 归档标记1377", limit=7)
                    self.assertLessEqual(len(rows), 7)
                    results.append(rows)
                elapsed = time.perf_counter() - start
                self.assertTrue(any(x["memory_id"] == target for x in results[-1]))
                # Product regression guard only; deliberately generous for CI/slow disks.
                self.assertLess(elapsed, 5.0)
                ctx = store.identity_context("石英 Quartz1377", memories_override=results[-1])
                self.assertLess(len(ctx), 9000)
            finally:
                bridge.close()
                store.close()



    def test_fts5_backend_rebuilds_old_derived_postings(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            mid = store.add_memory("I prefer durable long term memory", category="preference", priority=5)
            idx = home / "identity" / "product_memory_index.sqlite3"
            db = sqlite3.connect(str(idx))
            try:
                db.execute("CREATE TABLE index_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                db.execute("INSERT INTO index_settings(key,value) VALUES('schema_version','1')")
                db.execute("INSERT INTO index_settings(key,value) VALUES('initialized','1')")
                db.execute("CREATE TABLE product_memory_terms(term TEXT NOT NULL,memory_id INTEGER NOT NULL,PRIMARY KEY(term,memory_id))")
                db.execute("INSERT INTO product_memory_terms(term,memory_id) VALUES('ghost',999999)")
                db.commit()
            finally:
                db.close()
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                status = bridge.status()
                self.assertEqual(status["index_schema_version"], ProductMemoryBridge.INDEX_SCHEMA_VERSION)
                self.assertEqual(status["retrieval_backend"], "sqlite_fts5")
                names = {row[0] for row in bridge.index.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
                self.assertIn("product_memory_fts", names)
                self.assertNotIn("product_memory_terms", names)
                self.assertTrue(any(x["memory_id"] == mid for x in bridge.recall("durable memory", limit=7)))
            finally:
                bridge.close()
                store.close()

    def test_provider_switch_preserves_identity_context_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            identity_id = store.persona()["id"]
            store.add_memory("I prefer quiet low profile walking shoes", category="preference", priority=5)
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                memories1 = bridge.recall("walking shoes preference", limit=7)
                ctx1 = store.identity_context("walking shoes preference", memories_override=memories1)
                save_provider(home, "deepseek")
                self.assertEqual(load_provider(home)["provider"], "deepseek")
                save_provider(home, "ollama")
                self.assertEqual(load_provider(home)["provider"], "ollama")
                memories2 = bridge.recall("walking shoes preference", limit=7)
                ctx2 = store.identity_context("walking shoes preference", memories_override=memories2)
                self.assertEqual(ctx1, ctx2)
                self.assertEqual(store.persona()["id"], identity_id)
                self.assertEqual(bridge.status()["retrieval_backend"], "sqlite_fts5")
            finally:
                bridge.close()
                store.close()


    def test_add_memory_rejects_non_user_source_event(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            try:
                assistant_event = store.record(
                    "conversation.assistant", "assistant", "I prefer mint tea"
                )
                system_event = store.record(
                    "system.synthetic", "system", "I prefer soft music"
                )
                with self.assertRaisesRegex(ValueError, "canonical user evidence"):
                    store.add_memory(
                        "I prefer mint tea",
                        category="preference",
                        priority=5,
                        source_event=assistant_event,
                    )
                with self.assertRaisesRegex(ValueError, "canonical user evidence"):
                    store.add_memory(
                        "I prefer soft music",
                        category="preference",
                        priority=5,
                        source_event=system_event,
                    )
            finally:
                store.close()

    def test_bridge_quarantines_legacy_invalid_canonical_source(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            assistant_event = store.record(
                "conversation.assistant", "assistant", "I prefer mint tea"
            )
            with store.conn:
                seq = store._next_memory_change_seq()
                cur = store.conn.execute(
                    """INSERT INTO memories(
                           created_at,updated_at,category,text,source_event,
                           priority,status,change_seq)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        "2026-10-29T12:00:00+00:00",
                        "2026-10-29T12:00:00+00:00",
                        "preference",
                        "I prefer mint tea",
                        assistant_event,
                        5,
                        "active",
                        seq,
                    ),
                )
                mid = int(cur.lastrowid)

            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                initial_sync = dict(bridge.last_sync)
                self.assertFalse(
                    any(x["memory_id"] == mid for x in bridge.recall("mint tea", limit=7))
                )
                meta = bridge.index.execute(
                    "SELECT status FROM product_memory_meta WHERE memory_id=?", (mid,)
                ).fetchone()
                self.assertIsNotNone(meta)
                self.assertEqual(meta["status"], "quarantined")
                self.assertTrue(
                    any(
                        "invalid_canonical_source_quarantined" in x
                        for x in initial_sync["warnings"]
                    )
                )
                sid = bridge._r47.source_message_id(
                    "xiaoyu-product-confirmed-memory", f"memory-{mid}"
                )
                src = bridge.pipeline.store._source(sid)
                self.assertTrue(src is None or src["lifecycle"] != "active")
            finally:
                bridge.close()
                store.close()

    def test_same_timestamp_retract_is_not_left_model_visible(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            fixed = "2026-10-29T12:00:00+00:00"
            store = IdentityStore(home)
            with patch("identity_core.now", return_value=fixed):
                mid = store.add_memory("I prefer quiet shoes", category="preference", priority=5)
                bridge = ProductMemoryBridge(home, store, component_root=ROOT)
                try:
                    self.assertTrue(any(x["memory_id"] == mid for x in bridge.recall("quiet shoes", limit=7)))
                    self.assertTrue(store.retract_memory(mid))
                    result = bridge.sync()
                    self.assertGreaterEqual(result["processed"], 1)
                    self.assertEqual(bridge.recall("quiet shoes", limit=7), [])
                    self.assertNotIn(
                        "I prefer quiet shoes",
                        [x["text"] for x in bridge.pipeline.current_rows()],
                    )
                finally:
                    bridge.close()
            store.close()


    def test_bridge_failover_is_explicit_empty_not_legacy_recall(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            store.add_memory("target long tail memory", category="shared", priority=5)
            rows, err = safe_product_recall(None, "target long tail", limit=7)
            self.assertEqual(rows, [])
            self.assertEqual(err, "memory_bridge_unavailable")
            fail_closed = store.identity_context("target long tail", memories_override=rows)
            legacy = store.identity_context("target long tail")
            self.assertNotEqual(fail_closed, legacy)
            self.assertNotIn("target long tail memory", fail_closed)
            self.assertIn("target long tail memory", legacy)
            store.close()

    def test_bridge_runtime_recall_error_is_explicit_empty(self):
        class BrokenBridge:
            def recall(self, query, limit=7):
                raise RuntimeError("synthetic bridge failure")
        rows, err = safe_product_recall(BrokenBridge(), "anything", limit=7)
        self.assertEqual(rows, [])
        self.assertIn("RuntimeError", err)


    def test_unexpected_ingest_is_row_local_quarantine_not_bridge_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            good = store.add_memory(
                "I prefer quiet shoes", category="preference", priority=5
            )
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                bad = store.add_memory(
                    "A newly confirmed row with valid user provenance",
                    category="shared",
                    priority=3,
                )
                original = bridge.pipeline.ingest_source

                def controlled_ingest(source, raw_projection=None):
                    if source.get("source_id") == f"memory:{bad}":
                        return {"kind": "unsupported_test_fixture"}
                    return original(source, raw_projection=raw_projection)

                with patch.object(
                    bridge.pipeline, "ingest_source", side_effect=controlled_ingest
                ):
                    result = bridge.sync()

                self.assertTrue(
                    any("unexpected_ingest" in x for x in result["warnings"])
                )
                q = bridge.index.execute(
                    "SELECT status FROM product_memory_meta WHERE memory_id=?", (bad,)
                ).fetchone()
                self.assertIsNotNone(q)
                self.assertEqual(q["status"], "quarantined")
                rows, warning = safe_product_recall(
                    bridge, "quiet shoes", limit=7
                )
                self.assertTrue(any(x["memory_id"] == good for x in rows))
                self.assertIn("quarantined_memories", warning)
            finally:
                bridge.close()
                store.close()


    def test_tombstone_write_failure_failcloses_recent_dialog_to_current_event(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            old_token = "DELETE_FAILCLOSED_SENTINEL"
            keep_token = "KEEP_FAILCLOSED_SENTINEL"
            source_event = store.record(
                "conversation.user",
                "user",
                f"My old preference is {old_token}; my sibling fact is {keep_token}.",
            )
            store.record("conversation.assistant", "assistant", "Acknowledged.")
            old = store.add_memory(
                f"My old preference is {old_token}.",
                category="preference",
                priority=5,
                source_event=source_event,
            )
            store.add_memory(
                f"My sibling fact is {keep_token}.",
                category="shared",
                priority=5,
                source_event=source_event,
            )
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                self.assertTrue(
                    any(
                        int(x["memory_id"]) == old
                        for x in bridge.recall(old_token, limit=7)
                    )
                )
                with store.conn:
                    store.conn.execute(
                        "DELETE FROM memories WHERE memory_id=?", (old,)
                    )

                original = bridge._record_physical_delete

                def fail_tombstone(memory_id, source_event_id):
                    if int(memory_id) == int(old):
                        raise RuntimeError("synthetic_identity_tombstone_write_failure")
                    return original(memory_id, source_event_id)

                bridge._record_physical_delete = fail_tombstone
                query = "Please answer using my saved information."
                current_event = store.record(
                    "conversation.user", "user", query
                )
                memory_rows, recall_error = safe_product_recall(
                    bridge, query, limit=7
                )
                self.assertEqual(memory_rows, [])
                self.assertIn(
                    "synthetic_identity_tombstone_write_failure",
                    str(recall_error),
                )
                hard_memory_failure = bool(
                    recall_error
                    and not str(recall_error).startswith(
                        "quarantined_memories:"
                    )
                )
                history = project_history(
                    store,
                    16,
                    fail_closed_current_event_id=(
                        current_event if hard_memory_failure else None
                    ),
                )
                self.assertEqual(len(history), 1)
                self.assertEqual(
                    int(history[0]["event_id"]), int(current_event)
                )
                packed = "\n".join(str(x["content"]) for x in history)
                self.assertIn(query, packed)
                self.assertNotIn(old_token, packed)
                self.assertNotIn(keep_token, packed)
            finally:
                bridge._record_physical_delete = original
                bridge.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
