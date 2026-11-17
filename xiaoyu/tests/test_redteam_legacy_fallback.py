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
    capture_expectations,
    dual_guarded_chat,
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


if __name__=="__main__":
    unittest.main()
