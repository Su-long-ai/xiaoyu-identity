from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import InputSourceEnvelope, TrustClass
from xiaoyu.contracts.common import canonical_json
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.memory import (
    AdaptiveMemoryUseGate,
    FidelityClass,
    MemoryUseDecision,
)
from xiaoyu.core.profile import ProfileService
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
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.persistence.schema import MIGRATIONS, applied_versions
from xiaoyu.runtime.context import (
    ContextAssembler,
    ContextRequest,
    ContextSummaryError,
    ContextSummaryService,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
EXPECTED_VERSIONS = [migration.version for migration in MIGRATIONS]


class R11MemoryContextTests(unittest.TestCase):
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
        audience="PRIVATE",
        context_space="PERSONAL",
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
            audience_scope=audience,
            context_space=context_space,
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
            source_namespace="r11-test",
            source_event_key=key,
            event_id_override=stable_event_id(
                "fish-1", "r11-test", key
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

    def _insert_active_purpose(self, db, source_event_id):
        purpose = Purpose(
            purpose_id="purpose-active",
            identity_id="fish-1",
            owner_type=PurposeOwner.USER,
            owner_id="owner",
            state=PurposeState.ACTIVE,
            kind=PurposeKind.FOLLOW_UP,
            source_event_id=source_event_id,
            payload={"topic": "private project"},
            scheduled_wall_time=None,
            timezone_name=None,
            resolved_utc_time=None,
            miss_policy=MissPolicy.RECONCILE,
        )
        with db.transaction(immediate=True) as conn:
            PurposeRepository().insert(conn, purpose, T0)

    def _insert_delegation(self, db):
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO delegations(
                       delegation_id,identity_id,principal_id,actor_id,
                       purpose_id,scope_json,valid_from,expires_at,
                       revoked_at,delegation_digest,revocable
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "delegation-1",
                    "fish-1",
                    "owner",
                    "tool:test",
                    "purpose-active",
                    canonical_json(
                        {
                            "action_classes": ["test.read"],
                            "resources": ["profile:owner"],
                        }
                    ),
                    (T0 - timedelta(days=1)).isoformat(
                        timespec="microseconds"
                    ),
                    (T2 + timedelta(days=1)).isoformat(
                        timespec="microseconds"
                    ),
                    None,
                    "sha256:test",
                    1,
                ),
            )

    def _insert_unresolved_effect(self, db):
        stamp = T1.isoformat(timespec="microseconds")
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO effects(
                       effect_id,identity_id,intent_id,purpose_id,actor_id,
                       action_class,idempotency_key,replayable,
                       dispatch_state,request_json,receipt_id,verifier_state,
                       created_at,updated_at,authorization_decision_id,
                       purpose_revision,purpose_occurrence_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "effect-unresolved",
                    "fish-1",
                    "intent-unresolved",
                    "purpose-active",
                    "tool:test",
                    "test.write",
                    "idem-unresolved",
                    1,
                    "NEEDS_RECONCILIATION",
                    canonical_json({"private": "payload"}),
                    None,
                    None,
                    stamp,
                    stamp,
                    None,
                    1,
                    None,
                ),
            )

    def _request(
        self,
        text,
        *,
        audience="PRIVATE",
        explicit=False,
        continuation=False,
        viewer=(),
    ):
        return ContextRequest(
            identity_id="fish-1",
            principal_id="owner",
            audience_scope=audience,
            context_space="PERSONAL",
            viewer_principal_ids=tuple(viewer),
            turn_text=text,
            identity_block={
                "identity_id": "fish-1",
                "persona_version": 1,
            },
            explicit_recall=explicit,
            continuation=continuation,
        )

    @staticmethod
    def _by_kind(context):
        return {block.kind: block for block in context.blocks}

    def test_v11_migration_registered(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertEqual(applied_versions(db), EXPECTED_VERSIONS)
            self.assertIn(11, EXPECTED_VERSIONS)

    def test_casual_turn_abstains_without_memory_injection(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            event = self._event(
                db, key="casual-fact", at=T0, text="I prefer tea"
            )
            self._fact(
                db,
                event=event,
                mutation_id="mut-casual",
                predicate="drink_preference",
                value="tea",
                expected_revision=0,
                valid_from=T0,
            )
            ProfileService(db).rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            context = ContextAssembler(db).assemble(
                self._request("你好"),
                now=T1,
            )
            kinds = self._by_kind(context)
            self.assertEqual(
                context.memory_decision, MemoryUseDecision.ABSTAIN
            )
            self.assertIn("IDENTITY", kinds)
            self.assertNotIn("MEMORY_FACTS", kinds)
            self.assertNotIn("PROFILE", kinds)
            self.assertNotIn("SUMMARY", kinds)

    def test_explicit_recall_uses_current_fact_and_fresh_profile(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            event = self._event(
                db, key="recall-fact", at=T0, text="I prefer tea"
            )
            self._fact(
                db,
                event=event,
                mutation_id="mut-recall",
                predicate="drink_preference",
                value="tea",
                expected_revision=0,
                valid_from=T0,
            )
            ProfileService(db).rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            context = ContextAssembler(db).assemble(
                self._request(
                    "你还记得我的偏好吗？",
                    explicit=True,
                ),
                now=T1,
            )
            kinds = self._by_kind(context)
            self.assertEqual(
                context.memory_decision, MemoryUseDecision.USE
            )
            self.assertIn("MEMORY_FACTS", kinds)
            self.assertIn("PROFILE", kinds)
            values = [
                item["value"]
                for item in kinds["MEMORY_FACTS"].payload
            ]
            self.assertIn("tea", values)
            self.assertEqual(
                kinds["PROFILE"].payload["fields"][
                    "drink_preference"
                ],
                "tea",
            )

    def test_correction_makes_old_profile_and_summary_stale(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            first_event = self._event(
                db, key="stale-1", at=T0, text="I prefer tea"
            )
            self._fact(
                db,
                event=first_event,
                mutation_id="mut-stale-1",
                predicate="drink_preference",
                value="tea",
                expected_revision=0,
                valid_from=T0,
            )
            profile = ProfileService(db)
            profile.rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            summaries = ContextSummaryService(db)
            summaries.create(
                summary_id="summary-old",
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
                audience_scope="PRIVATE",
                summary_text="The user prefers tea.",
                source_event_ids=[first_event.event_id],
                created_at=T0,
            )
            self.assertEqual(
                len(
                    summaries.fresh(
                        identity_id="fish-1",
                        principal_scope="owner",
                        context_space="PERSONAL",
                        audience_scope="PRIVATE",
                    )
                ),
                1,
            )

            correction_event = self._event(
                db,
                key="stale-2",
                at=T1,
                text="Correction: I prefer coffee",
            )
            self._fact(
                db,
                event=correction_event,
                mutation_id="mut-stale-2",
                predicate="drink_preference",
                value="coffee",
                expected_revision=1,
                operation=FactMutationOperation.CORRECT,
            )
            self.assertIsNone(
                profile.read_fresh(
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                )
            )
            self.assertEqual(
                summaries.fresh(
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                    audience_scope="PRIVATE",
                ),
                [],
            )

            context = ContextAssembler(db).assemble(
                self._request(
                    "我之前说的饮料偏好是什么？",
                    explicit=True,
                ),
                now=T2,
            )
            kinds = self._by_kind(context)
            self.assertNotIn("PROFILE", kinds)
            self.assertNotIn("SUMMARY", kinds)
            current_values = [
                item["value"]
                for item in kinds["MEMORY_FACTS"].payload
            ]
            self.assertEqual(current_values, ["coffee"])
            self.assertEqual(
                kinds["CURRENT_CORRECTIONS"].payload[0]["value"],
                "coffee",
            )

    def test_private_memory_is_not_injected_into_group_context(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            event = self._event(
                db,
                key="private-1",
                at=T0,
                text="private favorite is tea",
                audience="PRIVATE",
            )
            self._fact(
                db,
                event=event,
                mutation_id="mut-private",
                predicate="private_preference",
                value="tea",
                expected_revision=0,
                valid_from=T0,
            )
            ProfileService(db).rebuild(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
            )
            context = ContextAssembler(db).assemble(
                self._request(
                    "你记得我的偏好吗？",
                    audience="GROUP",
                    viewer=("owner", "guest"),
                    explicit=True,
                ),
                now=T1,
            )
            kinds = self._by_kind(context)
            self.assertEqual(
                context.memory_decision, MemoryUseDecision.USE
            )
            self.assertNotIn("MEMORY_FACTS", kinds)
            self.assertNotIn("PROFILE", kinds)
            self.assertNotIn("RELATIONSHIP_POLICY", kinds)
            self.assertIn("IDENTITY", kinds)

    def test_memory_abstain_never_drops_exact_runtime_invariants(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            first_event = self._event(
                db, key="exact-1", at=T0, text="old preference"
            )
            self._fact(
                db,
                event=first_event,
                mutation_id="mut-exact-1",
                predicate="preference",
                value="old",
                expected_revision=0,
                valid_from=T0,
            )
            correction_event = self._event(
                db, key="exact-2", at=T1, text="correction new"
            )
            self._fact(
                db,
                event=correction_event,
                mutation_id="mut-exact-2",
                predicate="preference",
                value="new",
                expected_revision=1,
                operation=FactMutationOperation.CORRECT,
            )
            self._insert_active_purpose(db, correction_event.event_id)
            self._insert_delegation(db)
            self._insert_unresolved_effect(db)

            context = ContextAssembler(db).assemble(
                self._request("谢谢"),
                now=T1 + timedelta(hours=1),
            )
            kinds = self._by_kind(context)
            self.assertEqual(
                context.memory_decision, MemoryUseDecision.ABSTAIN
            )
            for required in (
                "IDENTITY",
                "PERMISSIONS",
                "ACTIVE_PURPOSES",
                "CURRENT_CORRECTIONS",
                "UNRESOLVED_EFFECTS",
            ):
                self.assertIn(required, kinds)
                self.assertEqual(
                    kinds[required].fidelity,
                    FidelityClass.NEVER_LOSSY,
                )
            self.assertNotIn("MEMORY_FACTS", kinds)
            self.assertNotIn("SUMMARY", kinds)

    def test_summary_cannot_compact_exact_state_or_summary_of_summary(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            source = self._event(
                db, key="summary-source", at=T0, text="old chatter"
            )
            service = ContextSummaryService(db)
            with self.assertRaises(ContextSummaryError):
                service.create(
                    summary_id="summary-bad-fidelity",
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                    audience_scope="PRIVATE",
                    summary_text="Do not compact permissions.",
                    source_event_ids=[source.event_id],
                    fidelity_class=FidelityClass.NEVER_LOSSY,
                    created_at=T0,
                )

            service.create(
                summary_id="summary-1",
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
                audience_scope="PRIVATE",
                summary_text="A compact old conversation detail.",
                source_event_ids=[source.event_id],
                created_at=T0,
            )
            with self.assertRaises(ContextSummaryError):
                service.create(
                    summary_id="summary-2",
                    identity_id="fish-1",
                    principal_scope="owner",
                    context_space="PERSONAL",
                    audience_scope="PRIVATE",
                    summary_text="Summary of another summary.",
                    source_event_ids=["summary-1"],
                    created_at=T1,
                )

    def test_active_purpose_continuation_uses_memory_but_generic_turn_does_not(self):
        gate = AdaptiveMemoryUseGate()
        self.assertEqual(
            gate.decide(
                "继续上次那个",
                active_purpose=True,
            ).decision,
            MemoryUseDecision.USE,
        )
        self.assertEqual(
            gate.decide(
                "给我讲个笑话",
                active_purpose=True,
            ).decision,
            MemoryUseDecision.ABSTAIN,
        )


if __name__ == "__main__":
    unittest.main()
