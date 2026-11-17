from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import InputSourceEnvelope, TrustClass
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.profile import ProfileService
from xiaoyu.core.promise import (
    PromiseAdmissionError,
    PromiseLedger,
    PromiseState,
)
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.core.relationship import (
    RelationshipLifecycle,
    RelationshipService,
    RelationshipTransitionError,
)
from xiaoyu.core.temporal import (
    FactMutationOperation,
    FactMutationRequest,
    TemporalFactService,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.persistence.schema import MIGRATIONS, applied_versions


UTC = timezone.utc
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
EXPECTED_VERSIONS = [migration.version for migration in MIGRATIONS]


class R10ProfileRelationshipPromiseTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _event(
        self,
        db,
        *,
        key,
        at,
        text,
        principal="owner",
        event_type="conversation.user",
        trust=TrustClass.OWNER_DIRECT,
        eligible=True,
    ):
        envelope = InputSourceEnvelope(
            event_id="raw:" + key,
            surface="test",
            source_type="text",
            principal_hint=principal,
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=trust,
            taint=(),
            eligible_for_memory=eligible,
            correlation_id="corr:" + key,
            observed_at=at,
            payload_type="text/plain",
            payload={"text": text},
        )
        event = CanonicalEvent.from_envelope(
            identity_id="fish-1",
            event_type=event_type,
            envelope=envelope,
            principal_id=principal,
            recorded_at=at,
            source_namespace="r10-test",
            source_event_key=key,
            event_id_override=stable_event_id(
                "fish-1", "r10-test", key
            ),
        )
        with db.transaction(immediate=True) as conn:
            return CanonicalEventRepository().append_or_get(conn, event)

    def _fact(
        self,
        db,
        *,
        event,
        mutation_id,
        predicate,
        value,
        expected_revision,
        operation=FactMutationOperation.ASSERT,
        valid_from=None,
    ):
        return TemporalFactService(db).apply(
            FactMutationRequest(
                mutation_id=mutation_id,
                source_event_id=event.event_id,
                authenticated_principal_id="owner",
                subject="owner",
                predicate=predicate,
                operation=operation,
                expected_revision=expected_revision,
                value=value,
                valid_from=valid_from,
            ),
            created_at=event.observed_at,
        )

    def _purpose(self, db, source_event_id):
        purpose = Purpose(
            purpose_id="purpose-promise",
            identity_id="fish-1",
            owner_type=PurposeOwner.XIAOYU,
            owner_id="xiaoyu:core",
            state=PurposeState.CONFIRMED,
            kind=PurposeKind.FOLLOW_UP,
            source_event_id=source_event_id,
            payload={"topic": "follow up"},
            scheduled_wall_time=None,
            timezone_name=None,
            resolved_utc_time=None,
            miss_policy=MissPolicy.RECONCILE,
        )
        with db.transaction(immediate=True) as conn:
            PurposeRepository().insert(conn, purpose, T1)

    def test_v10_migration_is_registered_after_execution_v8_v9(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertEqual(applied_versions(db), EXPECTED_VERSIONS)
            self.assertIn(8, EXPECTED_VERSIONS)
            self.assertIn(9, EXPECTED_VERSIONS)
            self.assertIn(10, EXPECTED_VERSIONS)
            self.assertLess(
                EXPECTED_VERSIONS.index(9),
                EXPECTED_VERSIONS.index(10),
            )

    def test_profile_shock_marks_old_projection_stale_then_rebuilds(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            first_event = self._event(
                db, key="pref-1", at=T0, text="I prefer tea"
            )
            first = self._fact(
                db,
                event=first_event,
                mutation_id="mut-pref-1",
                predicate="drink_preference",
                value="tea",
                expected_revision=0,
                valid_from=T0,
            )
            service = ProfileService(db)
            built = service.rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            self.assertEqual(
                built.fields["drink_preference"], "tea"
            )
            self.assertIsNotNone(
                service.read_fresh(
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                )
            )

            shock_event = self._event(
                db,
                key="pref-2",
                at=T1,
                text="Correction: I prefer coffee",
            )
            self._fact(
                db,
                event=shock_event,
                mutation_id="mut-pref-2",
                predicate="drink_preference",
                value="coffee",
                expected_revision=1,
                operation=FactMutationOperation.CORRECT,
            )

            self.assertIsNone(
                service.read_fresh(
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                )
            )
            rebuilt = service.rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            self.assertEqual(
                rebuilt.fields["drink_preference"], "coffee"
            )
            self.assertGreater(
                rebuilt.source_revision, built.source_revision
            )
            self.assertNotEqual(
                rebuilt.source_fact_ids, built.source_fact_ids
            )
            self.assertEqual(first.fact_key.split(":")[0], "fact")

    def test_profile_delete_rebuilds_to_empty_and_advances_erasure_generation(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            first_event = self._event(
                db, key="delete-1", at=T0, text="remember preference"
            )
            self._fact(
                db,
                event=first_event,
                mutation_id="mut-delete-1",
                predicate="private_preference",
                value="A",
                expected_revision=0,
                valid_from=T0,
            )
            profile = ProfileService(db)
            before = profile.rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            self.assertEqual(before.fields["private_preference"], "A")

            delete_event = self._event(
                db, key="delete-2", at=T1, text="delete that preference"
            )
            self._fact(
                db,
                event=delete_event,
                mutation_id="mut-delete-2",
                predicate="private_preference",
                value=None,
                expected_revision=1,
                operation=FactMutationOperation.DELETE,
            )
            self.assertIsNone(
                profile.read_fresh(
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                )
            )
            after = profile.rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            self.assertEqual(after.fields, {})
            self.assertEqual(after.source_fact_ids, ())
            self.assertGreater(after.erasure_generation, 0)

    def test_relationship_is_per_principal_and_rebuildable(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            owner_one = self._event(
                db, key="rel-owner-1", at=T0, text="known owner"
            )
            owner_two = self._event(
                db, key="rel-owner-2", at=T1, text="established owner"
            )
            guest_event = self._event(
                db,
                key="rel-guest-1",
                at=T0,
                text="known guest",
                principal="guest",
                trust=TrustClass.KNOWN_CONTACT,
            )
            service = RelationshipService(db)
            owner = service.transition(
                transition_id="rel-t1",
                identity_id="fish-1",
                principal_id="owner",
                expected_state=RelationshipLifecycle.NEW,
                to_state=RelationshipLifecycle.FAMILIAR,
                source_event_id=owner_one.event_id,
                reason="repeated authenticated interaction",
                value_patch={
                    "boundaries": {"private_memory": True},
                    "proactivity_policy": {"mode": "normal"},
                },
                created_at=T0,
            )
            owner = service.transition(
                transition_id="rel-t2",
                identity_id="fish-1",
                principal_id="owner",
                expected_state=RelationshipLifecycle.FAMILIAR,
                to_state=RelationshipLifecycle.ESTABLISHED,
                source_event_id=owner_two.event_id,
                reason="stable shared history",
                value_patch={
                    "interaction_norms": {"language": "zh"}
                },
                created_at=T1,
            )
            guest = service.transition(
                transition_id="rel-g1",
                identity_id="fish-1",
                principal_id="guest",
                expected_state=RelationshipLifecycle.NEW,
                to_state=RelationshipLifecycle.FAMILIAR,
                source_event_id=guest_event.event_id,
                reason="known contact",
                created_at=T0,
            )
            self.assertEqual(
                owner.state, RelationshipLifecycle.ESTABLISHED
            )
            self.assertEqual(
                guest.state, RelationshipLifecycle.FAMILIAR
            )
            self.assertNotIn(
                "boundaries", service.get(
                    identity_id="fish-1", principal_id="guest"
                ).value
            )

            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE relationship_state
                       SET state='PAUSED',value_json='{}',revision=99
                       WHERE identity_id='fish-1' AND principal_id='owner'"""
                )
            rebuilt = service.rebuild(
                identity_id="fish-1",
                principal_id="owner",
            )
            self.assertEqual(
                rebuilt.state, RelationshipLifecycle.ESTABLISHED
            )
            self.assertEqual(rebuilt.revision, 2)
            self.assertEqual(
                rebuilt.value["boundaries"]["private_memory"], True
            )
            self.assertEqual(
                service.get(
                    identity_id="fish-1", principal_id="guest"
                ).state,
                RelationshipLifecycle.FAMILIAR,
            )

    def test_model_derived_evidence_cannot_move_relationship_state(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            inferred = self._event(
                db,
                key="rel-model",
                at=T0,
                text="model guesses relationship",
                event_type="conversation.assistant",
                trust=TrustClass.MODEL_DERIVED,
                eligible=False,
            )
            with self.assertRaises(RelationshipTransitionError):
                RelationshipService(db).transition(
                    transition_id="rel-model-t",
                    identity_id="fish-1",
                    principal_id="owner",
                    expected_state=RelationshipLifecycle.NEW,
                    to_state=RelationshipLifecycle.FAMILIAR,
                    source_event_id=inferred.event_id,
                    reason="model guess",
                    created_at=T0,
                )

    def test_promise_requires_explicit_xiaoyu_commitment(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            source = self._event(
                db,
                key="promise-implicit",
                at=T0,
                text="maybe I can do that",
                event_type="conversation.assistant",
                trust=TrustClass.MODEL_DERIVED,
                eligible=False,
            )
            ledger = PromiseLedger(db)
            ledger.propose_candidate(
                candidate_id="candidate-implicit",
                source_event_id=source.event_id,
                speaker_actor="xiaoyu:core",
                commitment_text="Maybe I can do that",
                explicit_commitment=False,
                created_at=T0,
            )
            with self.assertRaises(PromiseAdmissionError):
                ledger.promote(
                    candidate_id="candidate-implicit",
                    promise_id="promise-implicit",
                    transition_id="promise-create-implicit",
                    created_at=T0,
                )

    def test_promise_links_to_purpose_without_authorizing_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            source = self._event(
                db,
                key="promise-explicit",
                at=T0,
                text="I will follow up tomorrow",
                event_type="conversation.assistant",
                trust=TrustClass.MODEL_DERIVED,
                eligible=False,
            )
            ledger = PromiseLedger(db)
            ledger.propose_candidate(
                candidate_id="candidate-1",
                source_event_id=source.event_id,
                speaker_actor="xiaoyu:core",
                commitment_text="I will follow up tomorrow",
                explicit_commitment=True,
                due_window={"kind": "tomorrow"},
                created_at=T0,
            )
            promise = ledger.promote(
                candidate_id="candidate-1",
                promise_id="promise-1",
                transition_id="promise-create-1",
                created_at=T0,
            )
            self.assertEqual(promise.state, PromiseState.OPEN)

            self._purpose(db, source.event_id)
            linked = ledger.link_purpose(
                promise_id="promise-1",
                purpose_id="purpose-promise",
                transition_id="promise-link-1",
                source_event_id=source.event_id,
                created_at=T1,
            )
            self.assertEqual(
                linked.linked_purpose_id, "purpose-promise"
            )

            waiting = ledger.transition(
                promise_id="promise-1",
                transition_id="promise-wait-1",
                expected_state=PromiseState.OPEN,
                to_state=PromiseState.WAITING,
                source_event_id=source.event_id,
                created_at=T1 + timedelta(minutes=1),
            )
            self.assertEqual(waiting.state, PromiseState.WAITING)

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM authorization_decisions"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    0,
                )
            finally:
                conn.close()

            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE promises
                       SET state='BROKEN',linked_purpose_id=NULL,revision=99
                       WHERE promise_id='promise-1'"""
                )
            rebuilt = ledger.rebuild(promise_id="promise-1")
            self.assertEqual(rebuilt.state, PromiseState.WAITING)
            self.assertEqual(
                rebuilt.linked_purpose_id, "purpose-promise"
            )
            self.assertEqual(rebuilt.revision, 3)

    def test_relationship_and_promise_logs_are_append_only_rebuild_sources(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            rel_event = self._event(
                db, key="rebuild-rel", at=T0, text="familiar"
            )
            rel_service = RelationshipService(db)
            expected_rel = rel_service.transition(
                transition_id="rebuild-rel-t",
                identity_id="fish-1",
                principal_id="owner",
                expected_state=RelationshipLifecycle.NEW,
                to_state=RelationshipLifecycle.FAMILIAR,
                source_event_id=rel_event.event_id,
                reason="evidence",
                value_patch={"interaction_norms": {"tone": "direct"}},
                created_at=T0,
            )
            rebuilt_rel = rel_service.rebuild(
                identity_id="fish-1", principal_id="owner"
            )
            self.assertEqual(rebuilt_rel, expected_rel)

            promise_event = self._event(
                db,
                key="rebuild-promise",
                at=T1,
                text="I will remember to follow up",
                event_type="conversation.assistant",
                trust=TrustClass.MODEL_DERIVED,
                eligible=False,
            )
            ledger = PromiseLedger(db)
            ledger.propose_candidate(
                candidate_id="rebuild-candidate",
                source_event_id=promise_event.event_id,
                speaker_actor="xiaoyu:core",
                commitment_text="I will remember to follow up",
                explicit_commitment=True,
                created_at=T1,
            )
            expected_promise = ledger.promote(
                candidate_id="rebuild-candidate",
                promise_id="rebuild-promise",
                transition_id="rebuild-promise-create",
                created_at=T1,
            )
            rebuilt_promise = ledger.rebuild(
                promise_id="rebuild-promise"
            )
            self.assertEqual(rebuilt_promise, expected_promise)


if __name__ == "__main__":
    unittest.main()
