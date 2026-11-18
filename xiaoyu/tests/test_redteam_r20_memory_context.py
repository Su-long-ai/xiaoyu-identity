from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from identity_core import IdentityStore
from model_adapter import project_history


class R20MemoryContextRedTeamTests(unittest.TestCase):
    SECRET = "SYNTHETIC_R20_PRIVATE_CONTEXT_MUST_DISAPPEAR"

    def _store_with_sourced_memory(self, td):
        store = IdentityStore(Path(td))
        source_event = store.record(
            "conversation.user",
            "user",
            self.SECRET,
        )
        memory_id = store.add_memory(
            self.SECRET,
            category="shared",
            priority=5,
            source_event=source_event,
        )
        return store, memory_id

    def _assert_secret_not_projected(self, store):
        encoded = json.dumps(
            project_history(store, 16),
            ensure_ascii=False,
        )
        self.assertNotIn(self.SECRET, encoded)

    def test_archived_memory_source_text_does_not_remain_in_prompt_history(self):
        with tempfile.TemporaryDirectory() as td:
            store, memory_id = self._store_with_sourced_memory(td)
            try:
                self.assertTrue(store.archive_memory(memory_id))
                self._assert_secret_not_projected(store)
            finally:
                store.close()

    def test_archived_memory_assistant_echo_does_not_remain_in_prompt_history(self):
        with tempfile.TemporaryDirectory() as td:
            store, memory_id = self._store_with_sourced_memory(td)
            try:
                store.record(
                    "conversation.assistant",
                    "assistant",
                    "I remember: " + self.SECRET,
                )
                self.assertTrue(store.archive_memory(memory_id))
                self._assert_secret_not_projected(store)
            finally:
                store.close()

    def test_retracted_memory_source_text_does_not_remain_in_prompt_history(self):
        with tempfile.TemporaryDirectory() as td:
            store, memory_id = self._store_with_sourced_memory(td)
            try:
                self.assertTrue(store.retract_memory(memory_id))
                self._assert_secret_not_projected(store)
            finally:
                store.close()

    def test_corrected_memory_source_text_does_not_remain_in_prompt_history(self):
        with tempfile.TemporaryDirectory() as td:
            store, memory_id = self._store_with_sourced_memory(td)
            try:
                store.correct_memory(
                    memory_id,
                    "SYNTHETIC_R20_CURRENT_REPLACEMENT",
                )
                self._assert_secret_not_projected(store)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
