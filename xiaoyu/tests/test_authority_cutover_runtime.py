from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from identity_core import (
    IdentityStore,
    LegacyAuthorityFenced,
)
from xiaoyu.contracts import InputSourceEnvelope, TrustClass
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.core.temporal import (
    FactMutationOperation,
    FactMutationRequest,
    TemporalFactService,
)
from xiaoyu.persistence import (
    Database,
    apply_migrations,
    applied_versions,
)
from xiaoyu.persistence.backfill import LegacyShadowBackfill
from xiaoyu.persistence.repositories.events import (
    CanonicalEventRepository,
)
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.release.migration import (
    AuthorityCutoverBlocked,
    AuthorityCutoverController,
    AuthorityCutoverEvidence,
    AuthorityMode,
    AuthorityRollbackForbidden,
)


UTC = timezone.utc
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class AuthorityCutoverRuntimeTests(unittest.TestCase):
    def test_v12_migrates_canonical_only_database_without_legacy_tables(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "canonical.sqlite3")
            apply_migrations(db)
            self.assertIn(12, applied_versions(db))
            controller = AuthorityCutoverController(db)
            self.assertTrue(controller.writer_fence_installed())

    @staticmethod
    def _canonical_owner_event(
        db: Database,
        *,
        identity_id: str,
        key: str,
        text: str,
        at: datetime,
    ) -> CanonicalEvent:
        envelope = InputSourceEnvelope(
            event_id="raw:" + key,
            surface="desktop",
            source_type="text",
            principal_hint="owner",
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            correlation_id="corr:" + key,
            observed_at=at,
            payload_type="text/plain",
            payload={"text": text},
        )
        event = CanonicalEvent.from_envelope(
            identity_id=identity_id,
            event_type="conversation.user",
            envelope=envelope,
            principal_id="owner",
            recorded_at=at,
            source_namespace="canonical-cutover-test",
            source_event_key=key,
            event_id_override=stable_event_id(
                identity_id,
                "canonical-cutover-test",
                key,
            ),
        )
        with db.transaction(immediate=True) as conn:
            return CanonicalEventRepository().append_or_get(
                conn, event
            )

    @staticmethod
    def _mutate(
        db: Database,
        *,
        event: CanonicalEvent,
        mutation_id: str,
        operation: FactMutationOperation,
        expected_revision: int,
        value=None,
    ):
        return TemporalFactService(db).apply(
            FactMutationRequest(
                mutation_id=mutation_id,
                source_event_id=event.event_id,
                authenticated_principal_id="owner",
                subject="owner",
                predicate="cutover_preference",
                operation=operation,
                expected_revision=expected_revision,
                value=value,
                valid_from=event.observed_at,
            ),
            created_at=event.observed_at,
        )

    def test_forward_only_cutover_fences_legacy_writer_but_canonical_work_continues(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = IdentityStore(root)
            identity_id = str(store.persona()["id"])
            legacy_event_id = store.record(
                "conversation.user",
                "user",
                "I prefer tea",
                {
                    "principal_id": "owner",
                    "surface": "desktop",
                    "source_type": "text",
                    "audience_scope": "PRIVATE",
                    "context_space": "PERSONAL",
                },
            )
            store.add_memory(
                "I prefer tea",
                category="preference",
                source_event=legacy_event_id,
            )
            store.close()

            db = Database(root / "identity" / "identity.sqlite3")
            apply_migrations(db)
            backfill = LegacyShadowBackfill(db)
            report = backfill.run_batch(identity_id, limit=1000)
            self.assertTrue(report.converged)
            self.assertTrue(report.source_order_ok)
            self.assertEqual(
                report.progress.state,
                "CAUGHT_UP",
            )

            controller = AuthorityCutoverController(
                db,
                backfill=backfill,
            )
            blocked = AuthorityCutoverEvidence(
                shadow_caught_up=True,
                rebuild_equal=True,
                unresolved_conflicts=0,
                erasure_generation_source=0,
                erasure_generation_shadow=0,
                source_order_ok=True,
                old_writer_fenced=False,
                canonical_read_path_ready=False,
                canonical_write_path_ready=False,
            )
            with self.assertRaisesRegex(
                AuthorityCutoverBlocked,
                "CANONICAL_READ_PATH_NOT_READY",
            ):
                controller.activate(
                    identity_id=identity_id,
                    evidence=blocked,
                    activated_at=T0,
                )
            self.assertEqual(
                controller.state(identity_id).mode,
                AuthorityMode.SHADOW,
            )

            ready = AuthorityCutoverEvidence(
                shadow_caught_up=True,
                rebuild_equal=True,
                unresolved_conflicts=0,
                erasure_generation_source=0,
                erasure_generation_shadow=0,
                source_order_ok=True,
                old_writer_fenced=False,
                canonical_read_path_ready=True,
                canonical_write_path_ready=True,
            )
            state = controller.activate(
                identity_id=identity_id,
                evidence=ready,
                activated_at=T0,
            )
            self.assertEqual(state.mode, AuthorityMode.CANONICAL)
            self.assertTrue(state.forward_only)
            self.assertTrue(state.activation_digest)
            self.assertGreaterEqual(
                state.legacy_event_high_watermark,
                legacy_event_id,
            )
            self.assertGreaterEqual(
                state.legacy_memory_change_seq,
                1,
            )

            # A completely unaware old writer is stopped by SQLite itself.
            raw = sqlite3.connect(str(db.path))
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    raw.execute(
                        """INSERT INTO events(
                               at,kind,actor,content,extra
                           ) VALUES(?,?,?,?,?)""",
                        (
                            T0.isoformat(),
                            "conversation.user",
                            "user",
                            "stale binary write",
                            "{}",
                        ),
                    )
                raw.rollback()
                with self.assertRaises(sqlite3.DatabaseError):
                    raw.execute(
                        """UPDATE memories SET text='tampered'
                           WHERE memory_id=1"""
                    )
                raw.rollback()
                with self.assertRaises(sqlite3.DatabaseError):
                    raw.execute(
                        """UPDATE settings SET value='0'
                           WHERE key='memory_change_seq'"""
                    )
                raw.rollback()
            finally:
                raw.close()

            # New legacy facade fails immediately, before it can mutate.
            with self.assertRaises(LegacyAuthorityFenced):
                IdentityStore(root)

            # Canonical authority remains writable after the fence.
            e1 = self._canonical_owner_event(
                db,
                identity_id=identity_id,
                key="assert",
                text="I prefer A",
                at=T0 + timedelta(minutes=1),
            )
            first = self._mutate(
                db,
                event=e1,
                mutation_id="cutover-assert",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="A",
            )
            self.assertEqual(first.revision, 1)

            e2 = self._canonical_owner_event(
                db,
                identity_id=identity_id,
                key="correct",
                text="Correction: I prefer B",
                at=T0 + timedelta(minutes=2),
            )
            corrected = self._mutate(
                db,
                event=e2,
                mutation_id="cutover-correct",
                operation=FactMutationOperation.CORRECT,
                expected_revision=1,
                value="B",
            )
            self.assertEqual(corrected.revision, 2)

            e3 = self._canonical_owner_event(
                db,
                identity_id=identity_id,
                key="retract",
                text="Retract that preference",
                at=T0 + timedelta(minutes=3),
            )
            retracted = self._mutate(
                db,
                event=e3,
                mutation_id="cutover-retract",
                operation=FactMutationOperation.RETRACT,
                expected_revision=2,
            )
            self.assertEqual(retracted.revision, 3)

            e4 = self._canonical_owner_event(
                db,
                identity_id=identity_id,
                key="reassert",
                text="I now prefer C",
                at=T0 + timedelta(minutes=4),
            )
            reasserted = self._mutate(
                db,
                event=e4,
                mutation_id="cutover-reassert",
                operation=FactMutationOperation.ASSERT,
                expected_revision=3,
                value="C",
            )
            self.assertEqual(reasserted.revision, 4)

            e5 = self._canonical_owner_event(
                db,
                identity_id=identity_id,
                key="delete",
                text="Delete that preference",
                at=T0 + timedelta(minutes=5),
            )
            deleted = self._mutate(
                db,
                event=e5,
                mutation_id="cutover-delete",
                operation=FactMutationOperation.DELETE,
                expected_revision=4,
            )
            self.assertEqual(deleted.revision, 5)
            self.assertGreater(deleted.erasure_generation, 0)

            purpose = Purpose(
                purpose_id="purpose-after-cutover",
                identity_id=identity_id,
                owner_type=PurposeOwner.USER,
                owner_id="owner",
                state=PurposeState.CONFIRMED,
                kind=PurposeKind.FOLLOW_UP,
                source_event_id=e5.event_id,
                payload={"topic": "post-cutover"},
                scheduled_wall_time=None,
                timezone_name=None,
                resolved_utc_time=None,
                miss_policy=MissPolicy.RECONCILE,
            )
            with db.transaction(immediate=True) as conn:
                PurposeRepository().insert(
                    conn,
                    purpose,
                    T0 + timedelta(minutes=6),
                )
                mutation_count = conn.execute(
                    """SELECT COUNT(*) FROM fact_mutations
                       WHERE identity_id=? AND mutation_id LIKE 'cutover-%'""",
                    (identity_id,),
                ).fetchone()[0]
                purpose_state = conn.execute(
                    """SELECT state FROM purposes
                       WHERE purpose_id='purpose-after-cutover'"""
                ).fetchone()[0]
            self.assertEqual(mutation_count, 5)
            self.assertEqual(purpose_state, "CONFIRMED")
            self.assertTrue(
                controller.verify_legacy_writer_frozen(identity_id)
            )

            with self.assertRaises(AuthorityRollbackForbidden):
                controller.rollback_to_shadow(identity_id)


if __name__ == "__main__":
    unittest.main()
