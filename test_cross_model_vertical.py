# -*- coding: utf-8 -*-
"""Current-root cross-model identity vertical slice. No real provider calls."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from identity_core import IdentityStore
from model_adapter import chat, project_history, save_provider
from product_memory_bridge import ProductMemoryBridge

ROOT = Path(__file__).resolve().parent


class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return json.dumps(
            {
                "choices": [{"message": {"content": self.content}}],
                "usage": {"total_tokens": 11},
            },
            ensure_ascii=False,
        ).encode("utf-8")


class CrossModelVerticalTests(unittest.TestCase):
    @staticmethod
    def _capture_calls(captured):
        def fake_urlopen(req, timeout=75):
            body = json.loads(req.data.decode("utf-8"))
            captured.append(
                {
                    "url": req.full_url,
                    "body": body,
                    "authorization": req.get_header("Authorization"),
                    "timeout": timeout,
                }
            )
            label = "qwen-ok" if "dashscope" in req.full_url else "deepseek-ok"
            return _FakeResponse(label)
        return fake_urlopen

    def test_same_identity_context_is_provider_neutral_at_send_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            first = store.add_memory("我现在住在苏州", category="shared", priority=5)
            store.correct_memory(first, "我现在住在上海")
            ev1 = store.record("conversation.user", "user", "我们一起完成了迁移测试")
            ev2 = store.record("conversation.assistant", "assistant", "迁移测试完成")
            store.propose_growth(
                "我们会在切换模型时继续保留已经确认的共同经历。",
                [ev1, ev2],
                confirmed=True,
            )
            question_event = store.record(
                "conversation.user", "user", "我现在住在哪里？"
            )
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            try:
                rows = bridge.recall("我现在住在哪里 上海 苏州", limit=7)
                system = store.identity_context(
                    "我现在住在哪里？", memories_override=rows
                )
                history = project_history(store, 16)
                messages = [{"role": "system", "content": system}] + [
                    {"role": x["role"], "content": x["content"]} for x in history
                ]
                identity_before = store.snapshot()

                deepseek = save_provider(home, "deepseek", "deepseek-flash")
                qwen = save_provider(home, "qwen", "qwen3.8-flash")
                captured = []
                with patch.dict(
                    os.environ,
                    {
                        "DEEPSEEK_API_KEY": "TEST_DEEPSEEK_KEY",
                        "DASHSCOPE_API_KEY": "TEST_QWEN_KEY",
                    },
                    clear=False,
                ):
                    with patch.object(
                        urllib.request,
                        "urlopen",
                        side_effect=self._capture_calls(captured),
                    ):
                        deepseek_reply, _ = chat(deepseek, messages, max_tokens=32)
                        qwen_reply, _ = chat(qwen, messages, max_tokens=32)

                self.assertEqual(deepseek_reply, "deepseek-ok")
                self.assertEqual(qwen_reply, "qwen-ok")
                self.assertEqual(len(captured), 2)
                self.assertEqual(
                    captured[0]["body"]["messages"],
                    captured[1]["body"]["messages"],
                )
                self.assertEqual(captured[0]["body"]["model"], "deepseek-flash")
                self.assertNotIn("enable_thinking", captured[0]["body"])
                self.assertEqual(captured[1]["body"]["model"], "qwen3.8-flash")
                self.assertIs(captured[1]["body"]["enable_thinking"], False)
                self.assertIn("我现在住在上海", system)
                self.assertNotIn("我现在住在苏州", system)
                self.assertIn("切换模型时继续保留", system)
                self.assertEqual(store.snapshot(), identity_before)
                self.assertTrue(any(x.get("event_id") == question_event for x in history))
            finally:
                bridge.close()
                store.close()

    def test_deepseek_history_survives_restart_and_is_visible_after_qwen_switch(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = IdentityStore(home)
            identity_id = store.persona()["id"]
            store.add_memory("我的鸟叫Pippin", category="shared", priority=5)
            first_user = store.record(
                "conversation.user", "user", "我的鸟叫什么？"
            )
            bridge = ProductMemoryBridge(home, store, component_root=ROOT)
            captured = []
            try:
                rows = bridge.recall("鸟 Pippin", limit=7)
                system = store.identity_context("我的鸟叫什么？", memories_override=rows)
                history = project_history(store, 16)
                deepseek_messages = [{"role": "system", "content": system}] + [
                    {"role": x["role"], "content": x["content"]} for x in history
                ]
                deepseek = save_provider(home, "deepseek", "deepseek-flash")
                with patch.dict(
                    os.environ, {"DEEPSEEK_API_KEY": "TEST_DEEPSEEK_KEY"}, clear=False
                ):
                    with patch.object(
                        urllib.request,
                        "urlopen",
                        side_effect=self._capture_calls(captured),
                    ):
                        reply, _ = chat(deepseek, deepseek_messages, max_tokens=32)
                self.assertEqual(reply, "deepseek-ok")
                store.record("conversation.assistant", "assistant", reply)
            finally:
                bridge.close()
                store.close()

            # Simulate a product restart before switching providers.
            store2 = IdentityStore(home)
            bridge2 = ProductMemoryBridge(home, store2, component_root=ROOT)
            try:
                self.assertEqual(store2.persona()["id"], identity_id)
                second_user = store2.record(
                    "conversation.user", "user", "你还记得上一轮和我的鸟吗？"
                )
                rows2 = bridge2.recall("上一轮 鸟 Pippin", limit=7)
                system2 = store2.identity_context(
                    "你还记得上一轮和我的鸟吗？", memories_override=rows2
                )
                history2 = project_history(store2, 16)
                qwen_messages = [{"role": "system", "content": system2}] + [
                    {"role": x["role"], "content": x["content"]} for x in history2
                ]
                qwen = save_provider(home, "qwen", "qwen3.8-flash")
                with patch.dict(
                    os.environ, {"DASHSCOPE_API_KEY": "TEST_QWEN_KEY"}, clear=False
                ):
                    with patch.object(
                        urllib.request,
                        "urlopen",
                        side_effect=self._capture_calls(captured),
                    ):
                        qreply, _ = chat(qwen, qwen_messages, max_tokens=32)

                self.assertEqual(qreply, "qwen-ok")
                self.assertIn("我的鸟叫Pippin", system2)
                self.assertTrue(
                    any(
                        x["role"] == "assistant" and x["content"] == "deepseek-ok"
                        for x in history2
                    )
                )
                self.assertTrue(any(x.get("event_id") == first_user for x in history2))
                self.assertTrue(any(x.get("event_id") == second_user for x in history2))
                self.assertEqual(captured[-1]["body"]["messages"], qwen_messages)
                self.assertIs(captured[-1]["body"]["enable_thinking"], False)
                self.assertEqual(
                    bridge2.status()["runtime_memory_core"],
                    "r47_confirmed_product_adapter",
                )
                self.assertFalse(bridge2.status()["r52_runtime_loaded"])
            finally:
                bridge2.close()
                store2.close()


if __name__ == "__main__":
    unittest.main()
