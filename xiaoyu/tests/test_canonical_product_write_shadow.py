from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from identity_core import IdentityStore, LegacyAuthorityFenced
from xiaoyu.core.export import NativeCanonicalExporter
from xiaoyu.core.identity import (
    LegacySelfBackfill,
    SelfAuthorityService,
)
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.memory_backfill import (
    LegacyMemoryTemporalBackfill,
)
from xiaoyu.release.migration import (
    AuthorityCutoverController,
    AuthorityCutoverEvidence,
)
from xiaoyu.runtime.product_store import (
    CanonicalProductStore,
    PresentationStateStore,
)
from xiaoyu.runtime.product_readiness import (
    CanonicalWriteShadowDrill,
)


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class CanonicalProductWriteShadowTests(unittest.TestCase):
    @staticmethod
    def _canonical_db(root: Path, identity_id: str = "fish-product"):
        db = Database(root / "identity.sqlite3")
        apply_migrations(db)
        SelfAuthorityService(db).initialize(
            identity_id=identity_id,
            persona={
                "name": "小鱼",
                "identity_commitments": ["诚实", "保持身份连续"],
                "style": {"language": "zh-CN"},
                "growth_notes": [],
                "bond_description": "长期伙伴",
            },
            created_at=T0,
            reason="test-bootstrap",
        )
        return db, CanonicalProductStore(
            db,
            identity_id=identity_id,
        )

    def test_turn_write_is_idempotent_and_semantic_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._canonical_db(Path(td))
            first = store.record_user_turn(
                source_event_key="turn-user-1",
                text="你好",
                observed_at=T0,
            )
            same = store.record_user_turn(
                source_event_key="turn-user-1",
                text="你好",
                observed_at=T0 + timedelta(seconds=5),
            )
            self.assertEqual(first.event_id, same.event_id)

            with self.assertRaises(Exception):
                store.record_user_turn(
                    source_event_key="turn-user-1",
                    text="同一个 key 却换了内容",
                    observed_at=T0 + timedelta(seconds=10),
                )

            assistant = store.record_assistant_turn(
                source_event_key="turn-assistant-1",
                text="你好，我在。",
                observed_at=T0 + timedelta(seconds=1),
            )
            self.assertFalse(assistant.eligible_for_memory)

            with db.transaction() as conn:
                count = conn.execute(
                    """SELECT COUNT(*) FROM canonical_events
                       WHERE identity_id=?""",
                    ("fish-product",),
                ).fetchone()[0]
            self.assertEqual(count, 2)

    def test_memory_proposal_requires_owner_decision_and_is_retry_safe(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._canonical_db(Path(td))
            source = store.record_user_turn(
                source_event_key="proposal-source",
                text="我喜欢咖啡",
                observed_at=T0,
            )
            proposal = store.propose_memory(
                claim_id="proposal-coffee",
                source_event_id=source.event_id,
                text="我喜欢咖啡",
                category="preference",
                priority=5,
                confidence=0.9,
                created_at=T0,
            )
            self.assertEqual(proposal.state, "PENDING")
            self.assertEqual(
                [item.claim_id for item in store.proposals.list_pending(
                    "fish-product"
                )],
                ["proposal-coffee"],
            )

            model_decision = store.record_assistant_turn(
                source_event_key="bad-approve",
                text="我替用户批准这条记忆",
                observed_at=T0 + timedelta(minutes=1),
            )
            with self.assertRaises(Exception):
                store.approve_memory(
                    claim_id="proposal-coffee",
                    decision_event_id=model_decision.event_id,
                    principal_id="owner",
                )

            approval = store.record_owner_control(
                source_event_key="approve-coffee",
                event_type="memory.approved",
                payload={"claim_id": "proposal-coffee"},
                observed_at=T0 + timedelta(minutes=2),
            )
            memory = store.approve_memory(
                claim_id="proposal-coffee",
                decision_event_id=approval.event_id,
                principal_id="owner",
            )
            self.assertEqual(memory.text, "我喜欢咖啡")
            self.assertEqual(memory.revision, 1)

            again = store.approve_memory(
                claim_id="proposal-coffee",
                decision_event_id=approval.event_id,
                principal_id="owner",
            )
            self.assertEqual(again.fact_id, memory.fact_id)
            self.assertEqual(
                store.proposals.get("proposal-coffee").state,
                "APPROVED",
            )

            second_source = store.record_user_turn(
                source_event_key="proposal-source-2",
                text="也许记住临时信息",
                observed_at=T0 + timedelta(minutes=3),
            )
            store.propose_memory(
                claim_id="proposal-reject",
                source_event_id=second_source.event_id,
                text="临时信息",
                category="other",
                priority=2,
                created_at=T0 + timedelta(minutes=3),
            )
            reject_event = store.record_owner_control(
                source_event_key="reject-memory",
                event_type="memory.rejected",
                payload={"claim_id": "proposal-reject"},
                observed_at=T0 + timedelta(minutes=4),
            )
            rejected = store.reject_memory(
                claim_id="proposal-reject",
                decision_event_id=reject_event.event_id,
                principal_id="owner",
            )
            self.assertEqual(rejected.state, "REJECTED")
            self.assertEqual(
                [item.claim_id for item in store.proposals.list_pending(
                    "fish-product"
                )],
                [],
            )

    def test_product_facade_reuses_memory_persona_purpose_and_presentation_authorities(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._canonical_db(Path(td))
            source = store.record_user_turn(
                source_event_key="memory-save",
                text="项目叫 Bluefin",
                observed_at=T0,
            )
            memory = store.save_memory(
                memory_id="project-name",
                mutation_id="product-memory-save",
                source_event_id=source.event_id,
                principal_id="owner",
                text="项目叫 Bluefin",
                category="project",
                priority=5,
            )
            self.assertEqual(memory.revision, 1)

            correction = store.record_user_turn(
                source_event_key="memory-correct",
                text="更正，项目叫 XiaoYu",
                observed_at=T0 + timedelta(minutes=1),
            )
            memory = store.correct_memory(
                memory_id="project-name",
                mutation_id="product-memory-correct",
                source_event_id=correction.event_id,
                principal_id="owner",
                expected_revision=1,
                text="项目叫 XiaoYu",
                category="project",
                priority=5,
            )
            self.assertEqual(memory.revision, 2)

            persona_event = store.record_user_turn(
                source_event_key="persona-revise",
                text="以后表达更简洁一些",
                observed_at=T0 + timedelta(minutes=2),
            )
            current = store.self_authority.get("fish-product")
            revised = store.revise_persona(
                expected_revision=current.persona_revision,
                persona={
                    **current.persona,
                    "style": {
                        **current.persona["style"],
                        "verbosity": "compact",
                    },
                },
                reason="owner-approved-style",
                source_event_ids=(persona_event.event_id,),
                principal_id="owner",
                created_at=T0 + timedelta(minutes=2),
            )
            self.assertEqual(
                revised.persona["style"]["verbosity"],
                "compact",
            )

            purpose = Purpose(
                purpose_id="purpose-product",
                identity_id="fish-product",
                owner_type=PurposeOwner.USER,
                owner_id="owner",
                state=PurposeState.CONFIRMED,
                kind=PurposeKind.FOLLOW_UP,
                source_event_id=source.event_id,
                payload={"topic": "Bluefin"},
                scheduled_wall_time=None,
                timezone_name=None,
                resolved_utc_time=None,
                miss_policy=MissPolicy.RECONCILE,
            )
            store.create_purpose(
                purpose,
                created_at=T0 + timedelta(minutes=3),
            )

            self.assertEqual(
                store.presentation_state(),
                {
                    "mood": 80,
                    "hunger": 20,
                    "energy": 90,
                    "bond": 0,
                },
            )
            presentation = store.update_presentation_state(
                {"mood": 101, "energy": -10, "bond": 42},
                updated_at=T0 + timedelta(minutes=4),
            )
            self.assertEqual(presentation["mood"], 100)
            self.assertEqual(presentation["energy"], 0)
            self.assertEqual(presentation["bond"], 42)

            with db.transaction() as conn:
                fact_count = conn.execute(
                    """SELECT COUNT(*) FROM temporal_facts
                       WHERE identity_id='fish-product'"""
                ).fetchone()[0]
                purpose_state = conn.execute(
                    """SELECT state FROM purposes
                       WHERE purpose_id='purpose-product'"""
                ).fetchone()[0]
            self.assertEqual(fact_count, 2)
            self.assertEqual(purpose_state, "CONFIRMED")

    def test_native_export_contains_self_and_rebuild_ledgers_not_presentation_state(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._canonical_db(Path(td))
            source = store.record_user_turn(
                source_event_key="export-source",
                text="记住导出测试",
                observed_at=T0,
            )
            store.propose_memory(
                claim_id="export-proposal",
                source_event_id=source.event_id,
                text="导出测试",
                category="shared",
                priority=3,
                created_at=T0,
            )
            store.update_presentation_state(
                {"mood": 12, "bond": 55},
                updated_at=T0,
            )

            data = NativeCanonicalExporter(db).build(
                identity_id="fish-product"
            )["data"]
            for required in (
                "self_identity",
                "self_persona_versions",
                "relationship_transitions",
                "promise_candidates",
                "promise_transitions",
                "memory_proposal_decisions",
            ):
                self.assertIn(required, data)
            self.assertEqual(len(data["self_identity"]), 1)
            self.assertEqual(
                len(data["self_persona_versions"]),
                1,
            )
            self.assertEqual(
                len(data["memory_proposal_decisions"]),
                1,
            )
            self.assertNotIn("presentation_state", data)

    def test_legacy_presentation_state_backfills_without_becoming_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = IdentityStore(root)
            identity_id = str(legacy.persona()["id"])
            legacy.set_state(
                {"mood": 61, "hunger": 33, "energy": 47, "bond": 12}
            )
            legacy.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            state = PresentationStateStore(db).backfill_legacy(
                identity_id=identity_id,
                updated_at=T0,
            )
            self.assertEqual(
                {key: state[key] for key in ("mood","hunger","energy","bond")},
                {"mood": 61, "hunger": 33, "energy": 47, "bond": 12},
            )
            with db.transaction() as conn:
                facts = conn.execute(
                    "SELECT COUNT(*) FROM temporal_facts"
                ).fetchone()[0]
                self_rows = conn.execute(
                    "SELECT COUNT(*) FROM self_identity"
                ).fetchone()[0]
            self.assertEqual(facts, 0)
            self.assertEqual(self_rows, 0)

    def test_product_store_remains_writable_after_canonical_cutover(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = IdentityStore(root)
            identity_id = str(legacy.persona()["id"])
            legacy_event = legacy.record(
                "conversation.user",
                "user",
                "cutover seed",
                {
                    "principal_id": "owner",
                    "surface": "desktop",
                    "source_type": "text",
                    "audience_scope": "PRIVATE",
                    "context_space": "PERSONAL",
                },
            )
            legacy.add_memory(
                "cutover seed",
                category="shared",
                priority=3,
                source_event=legacy_event,
            )
            legacy.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            backfill = LegacyShadowBackfill(db)
            self.assertTrue(
                backfill.run_batch(
                    identity_id,
                    limit=1000,
                ).converged
            )
            LegacySelfBackfill(db).run()
            self.assertTrue(
                LegacyMemoryTemporalBackfill(db)
                .run(identity_id)
                .converged
            )
            PresentationStateStore(db).backfill_legacy(
                identity_id=identity_id,
                updated_at=T0,
            )

            controller = AuthorityCutoverController(
                db,
                backfill=backfill,
            )
            controller.activate(
                identity_id=identity_id,
                evidence=AuthorityCutoverEvidence(
                    shadow_caught_up=True,
                    rebuild_equal=True,
                    unresolved_conflicts=0,
                    erasure_generation_source=0,
                    erasure_generation_shadow=0,
                    source_order_ok=True,
                    old_writer_fenced=False,
                    canonical_read_path_ready=True,
                    canonical_write_path_ready=True,
                ),
                activated_at=T0,
            )
            with self.assertRaises(LegacyAuthorityFenced):
                IdentityStore(root)

            product = CanonicalProductStore(
                db,
                identity_id=identity_id,
            )
            turn = product.record_user_turn(
                source_event_key="post-cutover-turn",
                text="切换之后继续工作",
                observed_at=T0 + timedelta(minutes=1),
            )
            memory = product.save_memory(
                memory_id="post-cutover",
                mutation_id="post-cutover-memory",
                source_event_id=turn.event_id,
                principal_id="owner",
                text="切换之后继续工作",
                category="shared",
                priority=4,
                created_at=T0 + timedelta(minutes=1),
            )
            product.update_presentation_state(
                {"mood": 88},
                updated_at=T0 + timedelta(minutes=1),
            )
            self.assertEqual(memory.revision, 1)
            self.assertEqual(
                product.presentation_state()["mood"],
                88,
            )
            self.assertTrue(
                controller.verify_legacy_writer_frozen(
                    identity_id
                )
            )


    def test_disposable_write_drill_is_ready_for_legacy_migrated_identity_without_touching_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = IdentityStore(root)
            identity_id = str(legacy.persona()["id"])
            event_id = legacy.record(
                "conversation.user",
                "user",
                "legacy write-drill seed",
                {
                    "principal_id": "owner",
                    "surface": "desktop",
                    "source_type": "text",
                    "audience_scope": "PRIVATE",
                    "context_space": "PERSONAL",
                },
            )
            legacy.add_memory(
                "legacy write-drill seed",
                category="shared",
                priority=3,
                source_event=event_id,
            )
            legacy.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            backfill = LegacyShadowBackfill(db)
            self.assertTrue(
                backfill.run_batch(
                    identity_id,
                    limit=1000,
                ).converged
            )
            LegacySelfBackfill(db).run()
            self.assertTrue(
                LegacyMemoryTemporalBackfill(db)
                .run(identity_id)
                .converged
            )

            with db.transaction() as conn:
                source_events_before = conn.execute(
                    "SELECT COUNT(*) FROM canonical_events"
                ).fetchone()[0]
                source_mutations_before = conn.execute(
                    "SELECT COUNT(*) FROM fact_mutations"
                ).fetchone()[0]
                source_persona_before = conn.execute(
                    """SELECT current_persona_revision
                       FROM self_identity
                       WHERE identity_id=?""",
                    (identity_id,),
                ).fetchone()[0]

            status = CanonicalWriteShadowDrill(
                db,
                root / "write-readiness.json",
            ).run(
                identity_id=identity_id,
                observed_at=T0,
            )
            self.assertTrue(
                status.candidate_ready,
                status.blockers,
            )
            self.assertEqual(status.blockers, ())

            with db.transaction() as conn:
                source_events_after = conn.execute(
                    "SELECT COUNT(*) FROM canonical_events"
                ).fetchone()[0]
                source_mutations_after = conn.execute(
                    "SELECT COUNT(*) FROM fact_mutations"
                ).fetchone()[0]
                source_persona_after = conn.execute(
                    """SELECT current_persona_revision
                       FROM self_identity
                       WHERE identity_id=?""",
                    (identity_id,),
                ).fetchone()[0]
                drill_rows = conn.execute(
                    """SELECT COUNT(*) FROM canonical_events
                       WHERE source_event_key LIKE '__write_drill%'"""
                ).fetchone()[0]
                cutover_rows = conn.execute(
                    """SELECT COUNT(*) FROM authority_cutover_state
                       WHERE mode='CANONICAL'"""
                ).fetchone()[0]
            self.assertEqual(
                source_events_after,
                source_events_before,
            )
            self.assertEqual(
                source_mutations_after,
                source_mutations_before,
            )
            self.assertEqual(
                source_persona_after,
                source_persona_before,
            )
            self.assertEqual(drill_rows, 0)
            self.assertEqual(cutover_rows, 0)

    def test_disposable_write_drill_supports_fresh_canonical_only_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = Database(root / "fresh.sqlite3")
            apply_migrations(db)
            identity_id = "fish-fresh-canonical"
            SelfAuthorityService(db).initialize(
                identity_id=identity_id,
                persona={
                    "name": "小鱼",
                    "identity_commitments": ["诚实"],
                    "style": {"language": "zh-CN"},
                    "growth_notes": [],
                    "bond_description": "fresh",
                },
                created_at=T0,
                reason="fresh-install",
            )

            with db.transaction() as conn:
                legacy_tables = {
                    row[0]
                    for row in conn.execute(
                        """SELECT name FROM sqlite_master
                           WHERE type='table'"""
                    ).fetchall()
                }.intersection(
                    {
                        "events",
                        "memories",
                        "memory_proposals",
                        "persona_versions",
                        "settings",
                    }
                )
            self.assertEqual(legacy_tables, set())

            status = CanonicalWriteShadowDrill(
                db,
                root / "fresh-write-readiness.json",
            ).run(
                identity_id=identity_id,
                observed_at=T0,
            )
            self.assertTrue(
                status.candidate_ready,
                status.blockers,
            )

            with db.transaction() as conn:
                self.assertEqual(
                    conn.execute(
                        """SELECT COUNT(*) FROM canonical_events
                           WHERE source_event_key LIKE '__write_drill%'"""
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute(
                        """SELECT COUNT(*) FROM authority_cutover_state
                           WHERE mode='CANONICAL'"""
                    ).fetchone()[0],
                    0,
                )



if __name__ == "__main__":
    unittest.main()
