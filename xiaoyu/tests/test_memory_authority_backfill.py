from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from identity_core import IdentityStore
from xiaoyu.contracts import InputSourceEnvelope, Taint, TrustClass
from xiaoyu.core.claims import ClaimAdmissionError
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.memory import (
    CanonicalMemoryService,
    MemoryRetriever,
)
from xiaoyu.core.profile import ProfileService
from xiaoyu.core.temporal import FactMutationOperation
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.memory_backfill import (
    LegacyMemoryTemporalBackfill,
)
from xiaoyu.persistence.repositories.events import CanonicalEventRepository


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class MemoryAuthorityBackfillTests(unittest.TestCase):
    @staticmethod
    def _event(
        db,
        *,
        identity_id,
        key,
        text,
        at,
        trust=TrustClass.OWNER_DIRECT,
        principal="owner",
        eligible=True,
        taint=(),
    ):
        envelope = InputSourceEnvelope(
            event_id="raw:" + key,
            surface="desktop",
            source_type="text",
            principal_hint=principal,
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=trust,
            taint=tuple(taint),
            eligible_for_memory=eligible,
            correlation_id="corr:" + key,
            observed_at=at,
            payload_type="text/plain",
            payload={"text": text},
        )
        event = CanonicalEvent.from_envelope(
            identity_id=identity_id,
            event_type="conversation.user",
            envelope=envelope,
            principal_id=principal,
            recorded_at=at,
            source_namespace="memory-api-test",
            source_event_key=key,
            event_id_override=stable_event_id(
                identity_id, "memory-api-test", key
            ),
        )
        with db.transaction(immediate=True) as conn:
            return CanonicalEventRepository().append_or_get(
                conn, event
            )

    def test_legacy_memory_lifecycle_converges_into_temporal_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = IdentityStore(root)
            identity_id = store.persona()["id"]

            source_one = store.record(
                "conversation.user",
                "user",
                "我喜欢乌龙茶",
            )
            old = store.add_memory(
                "我喜欢乌龙茶",
                category="preference",
                priority=5,
                source_event=source_one,
            )
            corrected = store.correct_memory(
                old,
                "我现在更喜欢咖啡",
            )

            source_two = store.record(
                "conversation.user",
                "user",
                "项目代号是 Bluefin",
            )
            retracted = store.add_memory(
                "项目代号是 Bluefin",
                category="shared",
                priority=4,
                source_event=source_two,
            )
            self.assertTrue(store.retract_memory(retracted))

            source_three = store.record(
                "conversation.user",
                "user",
                "旧的临时安排",
            )
            archived = store.add_memory(
                "旧的临时安排",
                category="shared",
                priority=2,
                source_event=source_three,
            )
            self.assertTrue(store.archive_memory(archived))

            source_four = store.record(
                "conversation.user",
                "user",
                "长期项目叫 XiaoYu",
            )
            active = store.add_memory(
                "长期项目叫 XiaoYu",
                category="relationship",
                priority=5,
                source_event=source_four,
            )
            legacy_rows = store.conn.execute(
                """SELECT memory_id,status FROM memories
                   WHERE category NOT IN ('bootstrap','legacy')
                   ORDER BY memory_id"""
            ).fetchall()
            self.assertEqual(len(legacy_rows), 5)
            store.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            event_report = LegacyShadowBackfill(db).run_batch(
                identity_id, limit=1000
            )
            self.assertTrue(event_report.converged)

            report = LegacyMemoryTemporalBackfill(db).run(
                identity_id
            )
            self.assertTrue(report.converged)
            self.assertEqual(report.considered_rows, 5)
            self.assertEqual(report.active_rows, 2)
            self.assertEqual(report.inactive_rows, 3)
            self.assertEqual(report.lifecycle_closed, 3)

            service = CanonicalMemoryService(db)
            current = service.list_current(
                identity_id=identity_id,
                principal_scope="owner",
            )
            by_id = {item.memory_id: item for item in current}
            self.assertEqual(
                set(by_id),
                {
                    "legacy:%d" % corrected,
                    "legacy:%d" % active,
                },
            )
            self.assertEqual(
                by_id["legacy:%d" % corrected].text,
                "我现在更喜欢咖啡",
            )
            self.assertEqual(
                by_id["legacy:%d" % corrected].category,
                "preference",
            )
            self.assertNotIn("legacy:%d" % old, by_id)
            self.assertNotIn("legacy:%d" % retracted, by_id)
            self.assertNotIn("legacy:%d" % archived, by_id)

            retrieved = MemoryRetriever(db).retrieve(
                identity_id=identity_id,
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="你记得我喜欢什么饮料吗 咖啡",
                limit=10,
            )
            values = [
                item.value
                for item in retrieved
                if item.predicate == "remembered_item"
            ]
            self.assertTrue(
                any(value["text"] == "我现在更喜欢咖啡" for value in values)
            )
            self.assertFalse(
                any(value["text"] == "我喜欢乌龙茶" for value in values)
            )

            # Episodic memories are not owner-profile fields.
            profile = ProfileService(db).rebuild(
                identity_id=identity_id,
                principal_scope="owner",
                context_space="PERSONAL",
            )
            self.assertNotIn("remembered_item", profile.fields)

            # Deterministic mutation IDs make restart/rerun idempotent.
            again = LegacyMemoryTemporalBackfill(db).run(
                identity_id
            )
            self.assertTrue(again.converged)
            with db.transaction() as conn:
                count = conn.execute(
                    """SELECT COUNT(*) FROM fact_mutations
                       WHERE identity_id=?
                         AND mutation_id LIKE 'legacy-memory:%'""",
                    (identity_id,),
                ).fetchone()[0]
            self.assertEqual(count, 8)

    def test_canonical_memory_api_reuses_r9_revision_and_erasure_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            identity_id = "fish-memory"
            service = CanonicalMemoryService(db)

            one = self._event(
                db,
                identity_id=identity_id,
                key="save",
                text="记住我喜欢茶",
                at=T0,
            )
            saved = service.save(
                memory_id="drink",
                mutation_id="mem-save",
                source_event_id=one.event_id,
                principal_id="owner",
                text="我喜欢茶",
                category="preference",
                priority=4,
            )
            self.assertEqual(saved.revision, 1)

            two = self._event(
                db,
                identity_id=identity_id,
                key="correct",
                text="更正，我喜欢咖啡",
                at=T0 + timedelta(minutes=1),
            )
            corrected = service.correct(
                memory_id="drink",
                mutation_id="mem-correct",
                source_event_id=two.event_id,
                principal_id="owner",
                expected_revision=1,
                text="我喜欢咖啡",
                category="preference",
                priority=5,
            )
            self.assertEqual(corrected.revision, 2)
            self.assertEqual(corrected.text, "我喜欢咖啡")

            three = self._event(
                db,
                identity_id=identity_id,
                key="delete",
                text="删除这个偏好",
                at=T0 + timedelta(minutes=2),
            )
            deleted = service.delete(
                memory_id="drink",
                mutation_id="mem-delete",
                source_event_id=three.event_id,
                principal_id="owner",
                expected_revision=2,
            )
            self.assertEqual(deleted.revision, 3)
            self.assertGreater(deleted.erasure_generation, 0)
            with self.assertRaises(KeyError):
                service.get("drink", corrected.fact_key)

    def test_normal_runtime_does_not_inherit_legacy_missing_principal_exception(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            identity_id = "fish-normal-gate"
            envelope = InputSourceEnvelope(
                event_id="legacy-shaped-but-not-legacy",
                surface="desktop",
                source_type="text",
                principal_hint=None,
                audience_scope="PRIVATE",
                context_space="PERSONAL",
                trust_class=TrustClass.OWNER_DIRECT,
                taint=(),
                eligible_for_memory=True,
                correlation_id="corr-normal",
                observed_at=T0,
                payload_type="text/plain",
                payload={"text": "remember this"},
            )
            event = CanonicalEvent.from_envelope(
                identity_id=identity_id,
                event_type="conversation.user",
                envelope=envelope,
                principal_id=None,
                recorded_at=T0,
                source_namespace="normal-runtime",
                source_event_key="normal",
                event_id_override=stable_event_id(
                    identity_id,
                    "normal-runtime",
                    "normal",
                ),
            )
            with db.transaction(immediate=True) as conn:
                event = CanonicalEventRepository().append_or_get(
                    conn, event
                )
            with self.assertRaises(ClaimAdmissionError):
                CanonicalMemoryService(db).save(
                    memory_id="unsafe",
                    mutation_id="unsafe-save",
                    source_event_id=event.event_id,
                    principal_id="owner",
                    text="remember this",
                    category="shared",
                    priority=3,
                )

    def test_model_or_tainted_source_cannot_create_runtime_memory(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            identity_id = "fish-memory-gate"

            model = self._event(
                db,
                identity_id=identity_id,
                key="model",
                text="model inferred preference",
                at=T0,
                trust=TrustClass.MODEL_DERIVED,
                eligible=False,
                taint=(Taint.MODEL_INFERRED,),
            )
            with self.assertRaises(ClaimAdmissionError):
                CanonicalMemoryService(db).save(
                    memory_id="model-memory",
                    mutation_id="model-save",
                    source_event_id=model.event_id,
                    principal_id="owner",
                    text="model inferred preference",
                    category="preference",
                )


if __name__ == "__main__":
    unittest.main()
