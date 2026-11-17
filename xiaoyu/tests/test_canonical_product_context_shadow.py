from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from identity_core import IdentityStore
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.memory_backfill import LegacyMemoryTemporalBackfill
from xiaoyu.core.identity import LegacySelfBackfill
from xiaoyu.runtime.product_context import (
    CanonicalDialogueProjector,
    CanonicalProductContextBuilder,
    CanonicalReadShadowEvaluator,
    CanonicalReadShadowMonitor,
)


class CanonicalProductContextShadowTests(unittest.TestCase):
    def _legacy_fixture(self, root: Path):
        store = IdentityStore(root)
        identity_id = str(store.persona()["id"])

        tea_event = store.record(
            "conversation.user",
            "user",
            "我现在更喜欢咖啡",
            {
                "principal_id": "owner",
                "surface": "desktop",
                "source_type": "text",
                "audience_scope": "PRIVATE",
                "context_space": "PERSONAL",
            },
        )
        tea_memory = store.add_memory(
            "我现在更喜欢咖啡",
            category="preference",
            priority=5,
            source_event=tea_event,
        )
        store.record(
            "conversation.assistant",
            "assistant",
            "记住了。",
            {
                "surface": "desktop",
                "source_type": "text",
                "audience_scope": "PRIVATE",
                "context_space": "PERSONAL",
            },
        )

        stale_event = store.record(
            "conversation.user",
            "user",
            "我住在南京",
            {
                "principal_id": "owner",
                "surface": "desktop",
                "source_type": "text",
                "audience_scope": "PRIVATE",
                "context_space": "PERSONAL",
            },
        )
        stale_memory = store.add_memory(
            "我住在南京",
            category="shared",
            priority=4,
            source_event=stale_event,
        )
        corrected_memory = store.correct_memory(
            stale_memory,
            "更正：我现在住在苏州",
        )

        mixed_event = store.record(
            "conversation.user",
            "user",
            "我住在秘密地址，同时喜欢红茶",
            {
                "principal_id": "owner",
                "surface": "desktop",
                "source_type": "text",
                "audience_scope": "PRIVATE",
                "context_space": "PERSONAL",
            },
        )
        deleted_memory = store.add_memory(
            "我住在秘密地址",
            category="shared",
            priority=5,
            source_event=mixed_event,
        )
        survivor_memory = store.add_memory(
            "我喜欢红茶",
            category="preference",
            priority=4,
            source_event=mixed_event,
        )

        # Reproduce ProductMemoryBridge's privacy-preserving physical deletion:
        # plaintext row is gone; only source-event tombstone remains.
        with store.conn:
            store.conn.execute(
                "DELETE FROM memories WHERE memory_id=?",
                (deleted_memory,),
            )
            store.record(
                "memory.deleted",
                "system",
                str(deleted_memory),
                {
                    "source_event": int(mixed_event),
                    "detected_by": "product_memory_bridge",
                },
            )

        return {
            "store": store,
            "identity_id": identity_id,
            "tea_event": tea_event,
            "tea_memory": tea_memory,
            "stale_event": stale_event,
            "stale_memory": stale_memory,
            "corrected_memory": corrected_memory,
            "mixed_event": mixed_event,
            "deleted_memory": deleted_memory,
            "survivor_memory": survivor_memory,
        }

    @staticmethod
    def _migrate(root: Path, identity_id: str):
        db = Database(root / "identity" / "identity.sqlite3")
        apply_migrations(db)
        event_report = LegacyShadowBackfill(db).run_batch(
            identity_id,
            limit=1000,
        )
        if not event_report.converged:
            raise AssertionError("event backfill did not converge")
        LegacySelfBackfill(db).run()
        memory_report = LegacyMemoryTemporalBackfill(db).run(
            identity_id
        )
        if not memory_report.converged:
            raise AssertionError("memory backfill did not converge")
        return db

    def test_shadow_readiness_is_false_before_memory_migration_and_true_after(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._legacy_fixture(root)
            store = fixture["store"]
            identity_id = fixture["identity_id"]
            store.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            self.assertTrue(
                LegacyShadowBackfill(db)
                .run_batch(identity_id, limit=1000)
                .converged
            )
            LegacySelfBackfill(db).run()

            before = CanonicalReadShadowEvaluator(db).evaluate(
                identity_id=identity_id
            )
            self.assertFalse(before.ready)
            self.assertFalse(before.active_memory_equal)
            self.assertIn(
                "ACTIVE_MEMORY_MISMATCH",
                before.blockers(),
            )

            report = LegacyMemoryTemporalBackfill(db).run(
                identity_id
            )
            self.assertTrue(report.converged)

            after = CanonicalReadShadowEvaluator(db).evaluate(
                identity_id=identity_id
            )
            self.assertTrue(after.ready, after.blockers())
            self.assertEqual(after.blockers(), ())

    def test_canonical_history_marks_stale_and_suppresses_physically_deleted_plaintext(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._legacy_fixture(root)
            identity_id = fixture["identity_id"]
            fixture["store"].close()
            db = self._migrate(root, identity_id)

            turns = CanonicalDialogueProjector(db).project(
                identity_id=identity_id,
                principal_id="owner",
                limit=32,
            )
            by_id = {turn.event_id: turn for turn in turns}

            stale = by_id["legacy:%d" % fixture["stale_event"]]
            self.assertEqual(
                stale.memory_state_annotation,
                "historical_changed",
            )
            self.assertIn("不能作为当前事实", stale.content)
            self.assertIn("我住在南京", stale.content)

            mixed = by_id["legacy:%d" % fixture["mixed_event"]]
            self.assertEqual(
                mixed.memory_state_annotation,
                "partial_deleted",
            )
            self.assertNotIn("秘密地址", mixed.content)
            self.assertIn("我喜欢红茶", mixed.content)
            self.assertIn("物理删除", mixed.content)

    def test_recall_context_uses_current_canonical_memory_not_superseded_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._legacy_fixture(root)
            identity_id = fixture["identity_id"]
            legacy_state = fixture["store"].state()
            fixture["store"].close()
            db = self._migrate(root, identity_id)

            product = CanonicalProductContextBuilder(db).build(
                identity_id=identity_id,
                principal_id="owner",
                viewer_principal_ids=("owner",),
                turn_text="你还记得我现在住在哪里吗？",
                presentation_state=legacy_state,
                history_limit=32,
                explicit_recall=True,
            )
            kinds = {
                block.kind: block
                for block in product.assembled.blocks
            }
            self.assertIn("IDENTITY", kinds)
            self.assertIn("AUDIENCE_BOUNDARY", kinds)
            self.assertIn("MEMORY_FACTS", kinds)

            serialized = product.system_text
            self.assertIn("更正：我现在住在苏州", serialized)
            memory_payload = kinds["MEMORY_FACTS"].payload
            self.assertTrue(
                any(
                    item["value"].get("text")
                    == "更正：我现在住在苏州"
                    for item in memory_payload
                    if isinstance(item.get("value"), dict)
                )
            )

            stale_turn = next(
                turn
                for turn in product.history
                if turn.event_id
                == "legacy:%d" % fixture["stale_event"]
            )
            self.assertIn("我住在南京", stale_turn.content)
            self.assertIn("不能作为当前事实", stale_turn.content)

    def test_casual_turn_can_abstain_without_losing_self_or_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._legacy_fixture(root)
            identity_id = fixture["identity_id"]
            fixture["store"].close()
            db = self._migrate(root, identity_id)

            product = CanonicalProductContextBuilder(db).build(
                identity_id=identity_id,
                principal_id="owner",
                viewer_principal_ids=("owner",),
                turn_text="你好",
            )
            kinds = {
                block.kind
                for block in product.assembled.blocks
            }
            self.assertIn("IDENTITY", kinds)
            self.assertIn("AUDIENCE_BOUNDARY", kinds)
            self.assertIn("RELATIONSHIP_POLICY", kinds)
            self.assertNotIn("MEMORY_FACTS", kinds)

    def test_fail_closed_history_mode_keeps_only_current_user_event(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._legacy_fixture(root)
            identity_id = fixture["identity_id"]
            fixture["store"].close()
            db = self._migrate(root, identity_id)

            current = "legacy:%d" % fixture["mixed_event"]
            turns = CanonicalDialogueProjector(db).project(
                identity_id=identity_id,
                principal_id="owner",
                limit=32,
                fail_closed_current_event_id=current,
            )
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0].event_id, current)
            self.assertEqual(turns[0].role, "user")
            self.assertNotIn("秘密地址", turns[0].content)


    def test_shadow_monitor_requires_consecutive_success_and_resets_on_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._legacy_fixture(root)
            identity_id = fixture["identity_id"]
            tea_event = fixture["tea_event"]
            fixture["store"].close()
            db = self._migrate(root, identity_id)

            monitor = CanonicalReadShadowMonitor(
                db,
                root / "canonical-read-shadow.json",
                required_consecutive=2,
            )
            first = monitor.observe(identity_id=identity_id)
            self.assertEqual(first.consecutive_ready, 1)
            self.assertFalse(first.candidate_ready)

            second = monitor.observe(identity_id=identity_id)
            self.assertEqual(second.consecutive_ready, 2)
            self.assertTrue(second.candidate_ready)
            self.assertEqual(second.last_blockers, ())

            legacy = IdentityStore(root)
            legacy.add_memory(
                "新加入但尚未迁移的记忆",
                category="shared",
                priority=3,
                source_event=tea_event,
            )
            legacy.close()

            drifted = monitor.observe(identity_id=identity_id)
            self.assertEqual(drifted.consecutive_ready, 0)
            self.assertFalse(drifted.candidate_ready)
            self.assertIn(
                "ACTIVE_MEMORY_MISMATCH",
                drifted.last_blockers,
            )

            self.assertTrue(
                LegacyMemoryTemporalBackfill(db)
                .run(identity_id)
                .converged
            )
            repaired = monitor.observe(identity_id=identity_id)
            self.assertEqual(repaired.consecutive_ready, 1)
            self.assertFalse(repaired.candidate_ready)
            self.assertEqual(repaired.last_blockers, ())

            persisted = monitor.status()
            self.assertIsNotNone(persisted)
            self.assertEqual(
                persisted.evidence_digest,
                repaired.evidence_digest,
            )



if __name__ == "__main__":
    unittest.main()
