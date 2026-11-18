from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.core.memory import MemoryControlState
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime.context import ContextAssembler, ContextRequest
from xiaoyu.runtime.product_context import CanonicalDialogueProjector
from xiaoyu.runtime.product_controls import MemoryControlService
from xiaoyu.runtime.product_store import CanonicalProductStore


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 14, 0, tzinfo=UTC)
SECRET = "SYNTHETIC_CANONICAL_R20_PRIVATE_SECRET"


class R20CanonicalContextRedTeamTests(unittest.TestCase):
    def _fixture(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        store = CanonicalProductStore(db, identity_id="fish-r20-redteam")
        source = store.record_user_turn(
            source_event_key="secret-user",
            text=SECRET,
            observed_at=T0,
        )
        memory = store.save_memory(
            memory_id="secret-memory",
            mutation_id="save-secret-memory",
            source_event_id=source.event_id,
            principal_id="owner",
            text=SECRET,
            category="preference",
            priority=5,
            created_at=T0,
        )
        store.record_assistant_turn(
            source_event_key="secret-assistant",
            text="I remember: " + SECRET,
            observed_at=T0 + timedelta(seconds=1),
            correlation_id="turn:secret-user",
        )
        return db, store, memory

    @staticmethod
    def _encoded_history(db):
        history = CanonicalDialogueProjector(db).project(
            identity_id="fish-r20-redteam",
            principal_id="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            limit=16,
        )
        return json.dumps(
            [
                {
                    "role": item.role,
                    "content": item.content,
                    "event_id": item.event_id,
                    "annotation": item.memory_state_annotation,
                }
                for item in history
            ],
            ensure_ascii=False,
        )

    def test_muted_memory_and_assistant_echo_are_absent_from_canonical_prompt_history(self):
        with tempfile.TemporaryDirectory() as td:
            db, store, memory = self._fixture(td)
            controls = MemoryControlService(store)
            controls.set_state(
                memory_id=memory.memory_id,
                expected_revision=memory.revision,
                control_state=MemoryControlState.MUTED,
                source_event_key="mute-secret",
                created_at=T0 + timedelta(minutes=1),
            )
            self.assertNotIn(SECRET, self._encoded_history(db))

    @staticmethod
    def _encoded_blocks(db):
        assembled = ContextAssembler(db).assemble(
            ContextRequest(
                identity_id="fish-r20-redteam",
                principal_id="owner",
                audience_scope="PRIVATE",
                context_space="PERSONAL",
                viewer_principal_ids=("owner",),
                turn_text="do not recall stale private data",
                identity_block={"identity_id": "fish-r20-redteam"},
            ),
            now=T0 + timedelta(minutes=2),
        )
        return json.dumps(
            [
                {
                    "kind": block.kind,
                    "payload": block.payload,
                }
                for block in assembled.blocks
            ],
            ensure_ascii=False,
        )

    def test_muted_memory_does_not_bypass_retrieval_via_current_corrections_block(self):
        with tempfile.TemporaryDirectory() as td:
            db, store, memory = self._fixture(td)
            MemoryControlService(store).set_state(
                memory_id=memory.memory_id,
                expected_revision=memory.revision,
                control_state=MemoryControlState.MUTED,
                source_event_key="mute-secret-context",
                created_at=T0 + timedelta(minutes=1),
            )
            self.assertNotIn(SECRET, self._encoded_blocks(db))

    def test_archived_memory_does_not_bypass_retrieval_via_current_corrections_block(self):
        with tempfile.TemporaryDirectory() as td:
            db, store, memory = self._fixture(td)
            MemoryControlService(store).archive(
                memory_id=memory.memory_id,
                expected_revision=memory.revision,
                archived=True,
                source_event_key="archive-secret-context",
                created_at=T0 + timedelta(minutes=1),
            )
            self.assertNotIn(SECRET, self._encoded_blocks(db))

    def test_archived_memory_and_assistant_echo_are_absent_from_canonical_prompt_history(self):
        with tempfile.TemporaryDirectory() as td:
            db, store, memory = self._fixture(td)
            controls = MemoryControlService(store)
            controls.archive(
                memory_id=memory.memory_id,
                expected_revision=memory.revision,
                archived=True,
                source_event_key="archive-secret",
                created_at=T0 + timedelta(minutes=1),
            )
            self.assertNotIn(SECRET, self._encoded_history(db))


if __name__ == "__main__":
    unittest.main()
