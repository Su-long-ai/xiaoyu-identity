# -*- coding: utf-8 -*-
"""Regression contract for accepted E1 product composition integrated 2026-10-31."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from identity_core import IdentityStore, dump
from product_memory_bridge import ProductMemoryBridge

GROWTH_START = "【经过确认的成长记录】\n"
GROWTH_END = "\n【经确认的长期记忆；不包含开发者初始化设定】\n"
MEMORY_START = "【经确认的长期记忆；不包含开发者初始化设定】\n"
MEMORY_END = "\n【目前的模拟状态】"


def growth_section(context: str) -> str:
    return context.split(GROWTH_START, 1)[1].split(GROWTH_END, 1)[0]


def memory_section(context: str) -> str:
    return context.split(MEMORY_START, 1)[1].split(MEMORY_END, 1)[0]


def synthetic_row(i: int, text: str, category: str = "shared"):
    return {
        "memory_id": i,
        "category": category,
        "text": text,
        "priority": 5,
        "status": "active",
        "authority": "user_state",
        "source_id": f"memory:{i}",
    }


class AcceptedE1CompositionTests(unittest.TestCase):
    def test_identity_context_packs_complete_memory_records_under_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td))
            try:
                rows = [
                    synthetic_row(i, f"M{i}_" + ("中文长期记忆" * 65), "preference")
                    for i in range(1, 8)
                ]
                section = memory_section(
                    store.identity_context("probe", memories_override=rows)
                )
                parsed = json.loads(section)
                self.assertLessEqual(len(section), 2500)
                self.assertEqual(
                    [x["id"] for x in parsed],
                    list(range(1, len(parsed) + 1)),
                )
                self.assertTrue(
                    all(
                        set(x) == {"id", "type", "text", "authority", "source_id"}
                        for x in parsed
                    )
                )

                small = [
                    synthetic_row(1, "短记忆A", "preference"),
                    synthetic_row(2, "短记忆B", "shared"),
                ]
                expected = dump([
                    {
                        "id": x["memory_id"],
                        "type": x["category"],
                        "text": x["text"],
                        "authority": x["authority"],
                        "source_id": x["source_id"],
                    }
                    for x in small
                ])
                self.assertEqual(
                    memory_section(
                        store.identity_context("probe", memories_override=small)
                    ),
                    expected,
                )
            finally:
                store.close()

    def test_identity_context_packs_complete_growth_records_under_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td))
            try:
                for i in range(5):
                    user_event = store.record(
                        "conversation.user", "user", f"growth evidence user {i}"
                    )
                    assistant_event = store.record(
                        "conversation.assistant",
                        "assistant",
                        f"growth evidence assistant {i}",
                    )
                    store.propose_growth(
                        f"G{i}_BEGIN " + ("成长反思内容" * 120) + f" G{i}_END",
                        [user_event, assistant_event],
                        confirmed=True,
                    )
                section = growth_section(
                    store.identity_context("probe", memories_override=[])
                )
                parsed = json.loads(section)
                self.assertLessEqual(len(section), 1800)
                self.assertTrue(parsed)
                self.assertTrue(
                    all(
                        set(x) == {"at", "text", "evidence_event_ids"}
                        for x in parsed
                    )
                )
                for i in range(5):
                    if f"G{i}_BEGIN" in section:
                        self.assertIn(f"G{i}_END", section)
            finally:
                store.close()

        with tempfile.TemporaryDirectory() as td:
            store = IdentityStore(Path(td))
            try:
                user_event = store.record(
                    "conversation.user", "user", "short growth user"
                )
                assistant_event = store.record(
                    "conversation.assistant", "assistant", "short growth assistant"
                )
                store.propose_growth(
                    "短成长记录", [user_event, assistant_event], confirmed=True
                )
                recent = store.persona().get("growth_notes", [])[-5:]
                self.assertEqual(
                    growth_section(
                        store.identity_context("probe", memories_override=[])
                    ),
                    dump(recent),
                )
            finally:
                store.close()

    def test_recall_exact_dedupe_keeps_authoritative_rows_and_neutral_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            target = "饮料偏好 绿茶"
            others = [
                "饮料偏好 乌龙茶",
                "饮料偏好 红茶",
                "饮料偏好 白茶",
                "饮料偏好 咖啡",
                "饮料偏好 可可",
                "饮料偏好 绿茶拿铁",
            ]
            try:
                store.add_memory(target, category="preference", priority=5)
                for text in others:
                    store.add_memory(text, category="preference", priority=4)
                for _ in range(50):
                    store.add_memory(target, category="preference", priority=5)

                bridge = ProductMemoryBridge(home, store, component_root=ROOT)
                try:
                    rows = bridge.recall("饮料偏好", limit=7)
                    self.assertEqual(len(rows), 7)
                    self.assertEqual(
                        len({(x["category"], x["text"]) for x in rows}), 7
                    )
                    self.assertEqual(
                        {x["text"] for x in rows}, {target, *others}
                    )
                    self.assertEqual(
                        sum(x["text"] == target for x in rows), 1
                    )
                    self.assertTrue(
                        all(
                            x["retrieval"]
                            == "product_state+sqlite_fts5_zh_bigram_v2"
                            for x in rows
                        )
                    )
                    active = store.conn.execute(
                        "SELECT count(*) FROM memories WHERE status='active'"
                    ).fetchone()[0]
                    self.assertEqual(active, 57)
                    self.assertEqual(bridge.pipeline.source_count(), 57)
                    context = store.identity_context(
                        "饮料偏好", memories_override=rows
                    )
                    self.assertNotIn(
                        "product_state+sqlite_fts5_zh_bigram_v2", context
                    )
                finally:
                    bridge.close()
            finally:
                store.close()

    def test_physical_r47_only_component_root_still_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = root / "product_components" / "memory_engine_v1"
            engine.mkdir(parents=True)
            shutil.copy2(
                ROOT / "product_components" / "memory_engine_v1"
                / "r47_open_domain_memory_store_frozen.py",
                engine / "r47_open_domain_memory_store_frozen.py",
            )
            home = root / "home"
            store = IdentityStore(home)
            try:
                store.add_memory(
                    "唯一运行依赖测试 绿茶", category="preference", priority=5
                )
                bridge = ProductMemoryBridge(home, store, component_root=root)
                try:
                    rows = bridge.recall("运行依赖 绿茶", limit=7)
                    self.assertTrue(rows)
                    self.assertEqual(rows[0]["text"], "唯一运行依赖测试 绿茶")
                    status = bridge.status()
                    self.assertEqual(
                        status["runtime_memory_core"],
                        "r47_confirmed_product_adapter",
                    )
                    self.assertFalse(status["r52_runtime_loaded"])
                    loaded = [
                        name for name in sys.modules
                        if name.startswith(("r47_", "r49_", "r52_"))
                    ]
                    self.assertTrue(all(name.startswith("r47_") for name in loaded))
                finally:
                    bridge.close()
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
