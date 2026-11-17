from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from xiaoyu.contracts import InputSourceEnvelope, Taint, TrustClass
from xiaoyu.core.claims import ClaimAdmissionError, ClaimProposalService
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.temporal import (
    DeletedFactReplay,
    FactCardinality,
    FactMutationOperation,
    FactMutationRequest,
    FactRevisionConflict,
    MutationIdConflict,
    StaleSourceEvent,
    TemporalFactService,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import (
    CanonicalEventConflict,
    CanonicalEventRepository,
)


UTC = timezone.utc
JAN = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
JUN = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
NOV = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
DEC = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


class R9TemporalShadowTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _event(
        self,
        db,
        *,
        source_key,
        observed_at,
        text,
        trust=TrustClass.OWNER_DIRECT,
        principal_id="owner",
        eligible=True,
        context_space="PERSONAL",
        taint=(),
    ):
        envelope = InputSourceEnvelope(
            event_id="raw:" + source_key,
            surface="test",
            source_type="text",
            principal_hint=principal_id,
            audience_scope="PRIVATE",
            context_space=context_space,
            trust_class=trust,
            taint=tuple(taint),
            eligible_for_memory=eligible,
            correlation_id="corr:" + source_key,
            observed_at=observed_at,
            payload_type="text/plain",
            payload={"text": text},
        )
        event = CanonicalEvent.from_envelope(
            identity_id="fish-1",
            event_type="conversation.user",
            envelope=envelope,
            principal_id=principal_id,
            recorded_at=observed_at,
            source_namespace="test",
            source_event_key=source_key,
            event_id_override=stable_event_id(
                "fish-1", "test", source_key
            ),
        )
        with db.transaction(immediate=True) as conn:
            return CanonicalEventRepository().append_or_get(
                conn, event
            )

    def _mutate(
        self,
        db,
        *,
        mutation_id,
        event,
        subject,
        predicate,
        operation,
        expected_revision,
        value=None,
        cardinality=FactCardinality.SINGLE,
        valid_from=None,
    ):
        return TemporalFactService(db).apply(
            FactMutationRequest(
                mutation_id=mutation_id,
                source_event_id=event.event_id,
                authenticated_principal_id="owner",
                subject=subject,
                predicate=predicate,
                operation=operation,
                expected_revision=expected_revision,
                value=value,
                cardinality=cardinality,
                valid_from=valid_from,
            ),
            created_at=event.observed_at,
        )

    def test_stable_source_retry_keeps_first_persisted_event(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            first = self._event(
                db,
                source_key="msg-1",
                observed_at=JAN,
                text="same",
            )
            envelope = InputSourceEnvelope(
                event_id="raw-retry",
                surface="test",
                source_type="text",
                principal_hint="owner",
                audience_scope="PRIVATE",
                context_space="PERSONAL",
                trust_class=TrustClass.OWNER_DIRECT,
                taint=(),
                eligible_for_memory=True,
                correlation_id="different-correlation",
                observed_at=NOV,
                payload_type="text/plain",
                payload={"text": "same"},
            )
            retry = CanonicalEvent.from_envelope(
                identity_id="fish-1",
                event_type="conversation.user",
                envelope=envelope,
                principal_id="owner",
                recorded_at=NOV,
                source_namespace="test",
                source_event_key="msg-1",
                event_id_override=stable_event_id(
                    "fish-1", "test", "msg-1"
                ),
            )
            with db.transaction(immediate=True) as conn:
                persisted = CanonicalEventRepository().append_or_get(
                    conn, retry
                )
                count = conn.execute(
                    "SELECT COUNT(*) FROM canonical_events"
                ).fetchone()[0]
                ingest = conn.execute(
                    "SELECT COUNT(*) FROM canonical_event_ingest"
                ).fetchone()[0]
            self.assertEqual(persisted.recorded_at, first.recorded_at)
            self.assertEqual(count, 1)
            self.assertEqual(ingest, 1)

    def test_same_source_key_with_different_semantics_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._event(
                db,
                source_key="msg-1",
                observed_at=JAN,
                text="one",
            )
            with self.assertRaises(CanonicalEventConflict):
                self._event(
                    db,
                    source_key="msg-1",
                    observed_at=NOV,
                    text="different",
                )

    def test_model_candidate_does_not_mutate_truth(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            event = self._event(
                db,
                source_key="model-1",
                observed_at=JAN,
                text="inferred city",
                trust=TrustClass.MODEL_DERIVED,
                principal_id="owner",
                eligible=True,
                taint=(Taint.MODEL_INFERRED,),
            )
            ClaimProposalService(db).propose(
                claim_id="claim-model",
                source_event_id=event.event_id,
                subject="owner",
                predicate="city",
                value="Nanjing",
                confidence=0.99,
                created_at=JAN,
            )
            with self.assertRaises(ClaimAdmissionError):
                self._mutate(
                    db,
                    mutation_id="mut-model",
                    event=event,
                    subject="owner",
                    predicate="city",
                    operation=FactMutationOperation.ASSERT,
                    expected_revision=0,
                    value="Nanjing",
                    valid_from=JAN,
                )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM temporal_facts"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT status FROM claims WHERE claim_id='claim-model'"
                    ).fetchone()[0],
                    "CANDIDATE",
                )
            finally:
                conn.close()

    def test_single_fact_temporal_evolution_preserves_history(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            first_event = self._event(
                db,
                source_key="city-1",
                observed_at=JAN,
                text="I live in Nanjing",
            )
            first = self._mutate(
                db,
                mutation_id="mut-city-1",
                event=first_event,
                subject="owner",
                predicate="city",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="Nanjing",
                valid_from=JAN,
            )
            second_event = self._event(
                db,
                source_key="city-2",
                observed_at=NOV,
                text="I moved to Suzhou",
            )
            second = self._mutate(
                db,
                mutation_id="mut-city-2",
                event=second_event,
                subject="owner",
                predicate="city",
                operation=FactMutationOperation.ASSERT,
                expected_revision=1,
                value="Suzhou",
                valid_from=NOV,
            )
            self.assertEqual(first.fact_key, second.fact_key)
            service = TemporalFactService(db)
            june = service.get_fact_at_time(
                identity_id="fish-1",
                fact_key=first.fact_key,
                at=JUN,
            )
            december = service.get_fact_at_time(
                identity_id="fish-1",
                fact_key=first.fact_key,
                at=DEC,
            )
            self.assertEqual(
                json.loads(june[0]["value_json"]),
                "Nanjing",
            )
            self.assertEqual(
                json.loads(december[0]["value_json"]),
                "Suzhou",
            )

    def test_correction_replaces_wrong_history(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            one = self._event(
                db,
                source_key="color-1",
                observed_at=JAN,
                text="favorite is red",
            )
            result = self._mutate(
                db,
                mutation_id="mut-color-1",
                event=one,
                subject="owner",
                predicate="favorite_color",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="red",
                valid_from=JAN,
            )
            two = self._event(
                db,
                source_key="color-2",
                observed_at=NOV,
                text="correction, it has always been blue",
            )
            corrected = self._mutate(
                db,
                mutation_id="mut-color-2",
                event=two,
                subject="owner",
                predicate="favorite_color",
                operation=FactMutationOperation.CORRECT,
                expected_revision=1,
                value="blue",
            )
            old_time = TemporalFactService(db).get_fact_at_time(
                identity_id="fish-1",
                fact_key=result.fact_key,
                at=JUN,
            )
            self.assertEqual(len(old_time), 1)
            self.assertEqual(
                json.loads(old_time[0]["value_json"]),
                "blue",
            )
            self.assertEqual(corrected.revision, 2)

    def test_retract_stops_current_use_but_keeps_prior_valid_time(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            one = self._event(
                db,
                source_key="lang-1",
                observed_at=JAN,
                text="use Chinese",
            )
            result = self._mutate(
                db,
                mutation_id="mut-lang-1",
                event=one,
                subject="owner",
                predicate="preferred_language",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="Chinese",
                valid_from=JAN,
            )
            two = self._event(
                db,
                source_key="lang-2",
                observed_at=JUN,
                text="stop using that preference",
            )
            self._mutate(
                db,
                mutation_id="mut-lang-2",
                event=two,
                subject="owner",
                predicate="preferred_language",
                operation=FactMutationOperation.RETRACT,
                expected_revision=1,
                valid_from=JUN,
            )
            service = TemporalFactService(db)
            before = service.get_fact_at_time(
                identity_id="fish-1",
                fact_key=result.fact_key,
                at=datetime(2026, 3, 1, tzinfo=UTC),
            )
            after = service.get_fact_at_time(
                identity_id="fish-1",
                fact_key=result.fact_key,
                at=NOV,
            )
            self.assertEqual(
                json.loads(before[0]["value_json"]),
                "Chinese",
            )
            self.assertEqual(after, [])

    def test_delete_fence_blocks_old_source_replay_but_allows_new_source(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            old = self._event(
                db,
                source_key="secret-old",
                observed_at=JAN,
                text="remember secret",
            )
            first = self._mutate(
                db,
                mutation_id="mut-secret-1",
                event=old,
                subject="owner",
                predicate="secret_pref",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="A",
                valid_from=JAN,
            )
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO projections(
                           identity_id,projection_key,projection_type,value_json,
                           source_fact_ids_json,builder_version,built_at,
                           source_revision,erasure_generation
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        "fish-1",
                        first.fact_key,
                        "PROFILE_SUMMARY",
                        '{"secret_pref":"A"}',
                        json.dumps([first.fact_id]),
                        "test-builder",
                        JAN.isoformat(),
                        1,
                        0,
                    ),
                )
                conn.execute(
                    """INSERT INTO relationship_state(
                           identity_id,principal_id,state,value_json,
                           source_fact_ids_json,effective_from,updated_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        "fish-1",
                        "owner",
                        "ESTABLISHED",
                        '{"derived":"A"}',
                        json.dumps([first.fact_id]),
                        JAN.isoformat(),
                        JAN.isoformat(),
                    ),
                )

            delete_event = self._event(
                db,
                source_key="secret-delete",
                observed_at=JUN,
                text="delete it",
            )
            deleted = self._mutate(
                db,
                mutation_id="mut-secret-delete",
                event=delete_event,
                subject="owner",
                predicate="secret_pref",
                operation=FactMutationOperation.DELETE,
                expected_revision=1,
            )
            with db.transaction() as conn:
                old_claim = conn.execute(
                    "SELECT status FROM claims WHERE claim_id='claim:mut-secret-1'"
                ).fetchone()
                deletion_claim = conn.execute(
                    "SELECT status FROM claims WHERE claim_id='claim:mut-secret-delete'"
                ).fetchone()
                projections = conn.execute(
                    "SELECT COUNT(*) FROM projections WHERE identity_id='fish-1'"
                ).fetchone()[0]
                relationship = conn.execute(
                    """SELECT 1 FROM relationship_state
                       WHERE identity_id='fish-1' AND principal_id='owner'"""
                ).fetchone()
            self.assertEqual(old_claim[0], "ERASED")
            self.assertEqual(deletion_claim[0], "CONFIRMED")
            self.assertEqual(projections, 0)
            self.assertIsNone(relationship)
            with self.assertRaises(DeletedFactReplay):
                self._mutate(
                    db,
                    mutation_id="mut-secret-replay",
                    event=old,
                    subject="owner",
                    predicate="secret_pref",
                    operation=FactMutationOperation.ASSERT,
                    expected_revision=2,
                    value="A",
                    valid_from=JAN,
                )

            newer = self._event(
                db,
                source_key="secret-new",
                observed_at=NOV,
                text="new preference",
            )
            reintroduced = self._mutate(
                db,
                mutation_id="mut-secret-new",
                event=newer,
                subject="owner",
                predicate="secret_pref",
                operation=FactMutationOperation.ASSERT,
                expected_revision=2,
                value="B",
                valid_from=NOV,
            )
            self.assertEqual(
                reintroduced.erasure_generation,
                deleted.erasure_generation,
            )
            rows = TemporalFactService(db).get_fact_at_time(
                identity_id="fish-1",
                fact_key=first.fact_key,
                at=DEC,
            )
            self.assertEqual(
                json.loads(rows[0]["value_json"]),
                "B",
            )

    def test_expected_revision_and_source_revision_prevent_stale_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            one = self._event(
                db,
                source_key="project-1",
                observed_at=JAN,
                text="project A",
            )
            result = self._mutate(
                db,
                mutation_id="mut-project-1",
                event=one,
                subject="owner",
                predicate="active_project",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="A",
                valid_from=JAN,
            )
            with self.assertRaises(FactRevisionConflict):
                self._mutate(
                    db,
                    mutation_id="mut-project-badrev",
                    event=one,
                    subject="owner",
                    predicate="active_project",
                    operation=FactMutationOperation.CORRECT,
                    expected_revision=0,
                    value="B",
                )

            older = self._event(
                db,
                source_key="project-older",
                observed_at=JUN,
                text="project B",
            )
            newer = self._event(
                db,
                source_key="project-newer",
                observed_at=NOV,
                text="project C",
            )
            self._mutate(
                db,
                mutation_id="mut-project-new",
                event=newer,
                subject="owner",
                predicate="active_project",
                operation=FactMutationOperation.CORRECT,
                expected_revision=1,
                value="C",
            )
            with self.assertRaises(StaleSourceEvent):
                self._mutate(
                    db,
                    mutation_id="mut-project-old",
                    event=older,
                    subject="owner",
                    predicate="active_project",
                    operation=FactMutationOperation.ASSERT,
                    expected_revision=2,
                    value="B",
                    valid_from=JUN,
                )
            self.assertEqual(
                TemporalFactService(db).freshness(
                    identity_id="fish-1",
                    fact_key=result.fact_key,
                )["current_revision"],
                2,
            )

    def test_mutation_id_is_idempotent_but_cannot_change_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            event = self._event(
                db,
                source_key="idem-1",
                observed_at=JAN,
                text="city Nanjing",
            )
            request = FactMutationRequest(
                mutation_id="mut-idem",
                source_event_id=event.event_id,
                authenticated_principal_id="owner",
                subject="owner",
                predicate="city",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="Nanjing",
                valid_from=JAN,
            )
            service = TemporalFactService(db)
            first = service.apply(request, created_at=JAN)
            second = service.apply(request, created_at=NOV)
            self.assertEqual(first.revision, second.revision)
            self.assertEqual(first.fact_id, second.fact_id)
            with self.assertRaises(MutationIdConflict):
                service.apply(
                    replace(request, value="Suzhou"),
                    created_at=NOV,
                )

    def test_set_cardinality_allows_multiple_current_values(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            one = self._event(
                db,
                source_key="hobby-1",
                observed_at=JAN,
                text="I like music",
            )
            first = self._mutate(
                db,
                mutation_id="mut-hobby-1",
                event=one,
                subject="owner",
                predicate="hobby",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="music",
                cardinality=FactCardinality.SET,
                valid_from=JAN,
            )
            two = self._event(
                db,
                source_key="hobby-2",
                observed_at=JUN,
                text="I also like games",
            )
            self._mutate(
                db,
                mutation_id="mut-hobby-2",
                event=two,
                subject="owner",
                predicate="hobby",
                operation=FactMutationOperation.ASSERT,
                expected_revision=1,
                value="games",
                cardinality=FactCardinality.SET,
                valid_from=JUN,
            )
            rows = TemporalFactService(db).get_fact_at_time(
                identity_id="fish-1",
                fact_key=first.fact_key,
                at=NOV,
            )
            self.assertEqual(
                sorted(json.loads(row["value_json"]) for row in rows),
                ["games", "music"],
            )

    def test_full_rebuild_matches_incremental_authority_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = Database(root / "source.sqlite3")
            apply_migrations(source)

            city1 = self._event(
                source,
                source_key="rebuild-city-1",
                observed_at=JAN,
                text="I live in Nanjing",
            )
            city = self._mutate(
                source,
                mutation_id="rebuild-mut-city-1",
                event=city1,
                subject="owner",
                predicate="city",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="Nanjing",
                valid_from=JAN,
            )
            city2 = self._event(
                source,
                source_key="rebuild-city-2",
                observed_at=NOV,
                text="I moved to Suzhou",
            )
            self._mutate(
                source,
                mutation_id="rebuild-mut-city-2",
                event=city2,
                subject="owner",
                predicate="city",
                operation=FactMutationOperation.ASSERT,
                expected_revision=1,
                value="Suzhou",
                valid_from=NOV,
            )

            pref1 = self._event(
                source,
                source_key="rebuild-pref-1",
                observed_at=JAN,
                text="prefer local",
            )
            pref = self._mutate(
                source,
                mutation_id="rebuild-mut-pref-1",
                event=pref1,
                subject="owner",
                predicate="tool_preference",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="local",
                valid_from=JAN,
            )
            retract = self._event(
                source,
                source_key="rebuild-pref-retract",
                observed_at=JUN,
                text="stop using that preference",
            )
            self._mutate(
                source,
                mutation_id="rebuild-mut-pref-retract",
                event=retract,
                subject="owner",
                predicate="tool_preference",
                operation=FactMutationOperation.RETRACT,
                expected_revision=1,
                valid_from=JUN,
            )

            secret1 = self._event(
                source,
                source_key="rebuild-secret-1",
                observed_at=JAN,
                text="remember A",
            )
            secret = self._mutate(
                source,
                mutation_id="rebuild-mut-secret-1",
                event=secret1,
                subject="owner",
                predicate="secret_pref",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="A",
                valid_from=JAN,
            )
            deletion = self._event(
                source,
                source_key="rebuild-secret-delete",
                observed_at=JUN,
                text="delete it",
            )
            self._mutate(
                source,
                mutation_id="rebuild-mut-secret-delete",
                event=deletion,
                subject="owner",
                predicate="secret_pref",
                operation=FactMutationOperation.DELETE,
                expected_revision=1,
            )
            secret2 = self._event(
                source,
                source_key="rebuild-secret-2",
                observed_at=NOV,
                text="new preference B",
            )
            self._mutate(
                source,
                mutation_id="rebuild-mut-secret-2",
                event=secret2,
                subject="owner",
                predicate="secret_pref",
                operation=FactMutationOperation.ASSERT,
                expected_revision=2,
                value="B",
                valid_from=NOV,
            )

            service = TemporalFactService(source)
            source_snapshot = service.authority_snapshot(
                identity_id="fish-1"
            )
            target = Database(root / "rebuilt.sqlite3")
            report = service.rebuild_into(
                target,
                identity_id="fish-1",
            )
            self.assertEqual(
                report["snapshot"],
                source_snapshot,
            )
            self.assertEqual(report["mutations"], 7)
            self.assertGreaterEqual(report["events"], 7)

            rebuilt = TemporalFactService(target)
            self.assertEqual(
                json.loads(
                    rebuilt.get_fact_at_time(
                        identity_id="fish-1",
                        fact_key=city.fact_key,
                        at=DEC,
                    )[0]["value_json"]
                ),
                "Suzhou",
            )
            self.assertEqual(
                rebuilt.get_fact_at_time(
                    identity_id="fish-1",
                    fact_key=pref.fact_key,
                    at=NOV,
                ),
                [],
            )
            self.assertEqual(
                json.loads(
                    rebuilt.get_fact_at_time(
                        identity_id="fish-1",
                        fact_key=secret.fact_key,
                        at=DEC,
                    )[0]["value_json"]
                ),
                "B",
            )

    def test_mutation_invalidates_projection_with_revision_and_erasure_generation(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            event = self._event(
                db,
                source_key="profile-1",
                observed_at=JAN,
                text="prefers local",
            )
            result = self._mutate(
                db,
                mutation_id="mut-profile-1",
                event=event,
                subject="owner",
                predicate="tool_preference",
                operation=FactMutationOperation.ASSERT,
                expected_revision=0,
                value="local",
                valid_from=JAN,
            )
            conn = db.connect()
            try:
                row = conn.execute(
                    """SELECT source_revision,erasure_generation,mutation_id
                       FROM projection_invalidations
                       WHERE identity_id='fish-1' AND fact_key=?""",
                    (result.fact_key,),
                ).fetchone()
                self.assertEqual(
                    tuple(row),
                    (1, 0, "mut-profile-1"),
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
