from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_adapter
from identity_core import IdentityStore
from product_memory_bridge import ProductMemoryBridge
from send_guard import (
    FreshnessChanged,
    capture_context_fence,
    capture_expectations,
    dual_guarded_chat,
    persist_assistant_if_fresh,
)


class LegacyFallbackFreshnessRedTeamTests(unittest.TestCase):
    def _fixture(self, td):
        store=IdentityStore(Path(td))
        memory_id=store.add_memory(
            "SYNTHETIC_FALLBACK_PRIVATE_SECRET"
        )
        bridge=ProductMemoryBridge(Path(td),store)
        rows=[
            row for row in store.list_memories()
            if int(row["memory_id"])==int(memory_id)
        ]
        generation=store.memory_generation()
        expectations=capture_expectations(bridge,rows)
        config=model_adapter._fallback_config("deepseek_web")
        config["fallbacks"]=["deepseek"]
        messages=[
            {
                "role":"system",
                "content":rows[0]["text"],
            }
        ]
        return (
            store,bridge,memory_id,generation,
            expectations,config,messages,
        )

    def test_memory_retraction_after_first_dispatch_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            calls=[]

            def fake_once(
                candidate,messages,max_tokens,timeout,on_dispatched
            ):
                if on_dispatched:
                    on_dispatched()
                calls.append(
                    {
                        "provider":candidate["provider"],
                        "generation":store.memory_generation(),
                    }
                )
                if len(calls)==1:
                    store.retract_memory(memory_id)
                    raise RuntimeError(
                        "request failed after first dispatch"
                    )
                return "must-not-run",{}

            try:
                with patch.object(
                    model_adapter,
                    "_chat_once",
                    side_effect=fake_once,
                ):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,
                            config,
                            messages,
                            store.db_path,
                            bridge.db_path,
                            generation,
                            expectations,
                        )
                self.assertEqual(len(calls),1)
                self.assertEqual(
                    calls[0]["provider"],
                    "deepseek_web",
                )
                self.assertNotEqual(
                    store.memory_generation(),
                    generation,
                )
            finally:
                bridge.close()
                store.close()

    def test_unchanged_authority_allows_guarded_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            calls=[]

            def fake_once(
                candidate,messages,max_tokens,timeout,on_dispatched
            ):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                if len(calls)==1:
                    raise RuntimeError("first provider unavailable")
                return "ok",{}

            try:
                with patch.object(
                    model_adapter,
                    "_chat_once",
                    side_effect=fake_once,
                ):
                    answer,usage=dual_guarded_chat(
                        model_adapter.chat,
                        config,
                        messages,
                        store.db_path,
                        bridge.db_path,
                        generation,
                        expectations,
                    )
                self.assertEqual(answer,"ok")
                self.assertEqual(
                    calls,
                    ["deepseek_web","deepseek"],
                )
            finally:
                bridge.close()
                store.close()

    def test_private_context_skips_ineligible_fallback_provider(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            config["fallbacks"]=["custom"]
            calls=[]

            def fake_once(
                candidate,messages,max_tokens,timeout,on_dispatched
            ):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                raise RuntimeError("primary failed")

            try:
                with patch.object(
                    model_adapter,
                    "_chat_once",
                    side_effect=fake_once,
                ):
                    with self.assertRaises(RuntimeError) as raised:
                        dual_guarded_chat(
                            model_adapter.chat,
                            config,
                            messages,
                            store.db_path,
                            bridge.db_path,
                            generation,
                            expectations,
                        )
                self.assertEqual(
                    calls,
                    ["deepseek_web"],
                )
                self.assertIn(
                    "custom",
                    str(raised.exception),
                )
            finally:
                bridge.close()
                store.close()


    def test_response_after_retraction_is_rejected_before_return(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                store.retract_memory(memory_id)
                return "STALE_RESPONSE_MUST_NOT_ESCAPE",{}
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()

    def test_provider_attempts_do_not_share_mutable_messages(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            seen=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                seen.append(attempt_messages[0]["content"])
                if len(seen)==1:
                    attempt_messages[0]["content"]="MUTATED_BY_PROVIDER_A"
                    raise RuntimeError("primary failed")
                return "ok",{}
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    answer,_=dual_guarded_chat(
                        model_adapter.chat,config,messages,
                        store.db_path,bridge.db_path,generation,expectations,
                    )
                self.assertEqual(answer,"ok")
                self.assertEqual(seen,[messages[0]["content"],messages[0]["content"]])
            finally:
                bridge.close()
                store.close()

    def test_audience_switch_during_fallback_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            state={
                "identity_id":"id-1",
                "principal_id":"owner",
                "audience_scope":"PRIVATE",
                "context_space":"PERSONAL",
                "authorization_digest":"auth-v1",
                "tool_result_digest":None,
            }
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                if len(calls)==1:
                    state["audience_scope"]="GROUP"
                    raise RuntimeError("primary failed")
                return "must-not-run",{}
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            identity_id="id-1",
                            principal_id="owner",
                            audience_scope="PRIVATE",
                            context_space="PERSONAL",
                            authorization_digest="auth-v1",
                            context_state_provider=lambda:dict(state),
                        )
                self.assertEqual(calls,["deepseek_web"])
            finally:
                bridge.close()
                store.close()

    def test_private_tool_result_without_digest_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            try:
                with self.assertRaises(FreshnessChanged):
                    dual_guarded_chat(
                        model_adapter.chat,config,messages,
                        store.db_path,bridge.db_path,generation,expectations,
                        source_contains_private_tool_result=True,
                        tool_result_digest=None,
                    )
            finally:
                bridge.close()
                store.close()


    def test_nonmemory_prompt_state_change_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            fence=capture_context_fence(store)
            calls=[]
            def fake_once(candidate,attempt_messages,max_tokens,timeout,on_dispatched):
                if on_dispatched:
                    on_dispatched()
                calls.append(candidate["provider"])
                state=store.state()
                state["mood"]="context-fence-changed"
                store.set_state(state)
                raise RuntimeError("primary failed")
            try:
                with patch.object(model_adapter,"_chat_once",side_effect=fake_once):
                    with self.assertRaises(FreshnessChanged):
                        dual_guarded_chat(
                            model_adapter.chat,config,messages,
                            store.db_path,bridge.db_path,generation,expectations,
                            expected_context_fence=fence,
                        )
                self.assertEqual(calls,["deepseek_web"])
                self.assertEqual(store.memory_generation(),generation)
            finally:
                bridge.close()
                store.close()

    def test_nonmemory_change_rejects_stale_assistant_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            (
                store,bridge,memory_id,generation,
                expectations,config,messages,
            )=self._fixture(td)
            fence=capture_context_fence(store)
            before=store.event_count()
            state=store.state()
            state["mood"]="changed-before-persist"
            store.set_state(state)
            try:
                with self.assertRaises(FreshnessChanged):
                    persist_assistant_if_fresh(
                        store,bridge,generation,expectations,
                        "must-not-persist",
                        expected_context_fence=fence,
                    )
                self.assertEqual(store.event_count(),before)
                self.assertEqual(store.memory_generation(),generation)
            finally:
                bridge.close()
                store.close()


if __name__=="__main__":
    unittest.main()
