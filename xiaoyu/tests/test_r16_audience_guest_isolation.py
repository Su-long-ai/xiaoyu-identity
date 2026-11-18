from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from send_guard import FreshnessChanged, dual_guarded_chat
from xiaoyu.contracts import InputSourceEnvelope, TrustClass
from xiaoyu.core.events import CanonicalEvent, stable_event_id
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime.context import ContextAssembler, ContextRequest
from xiaoyu.runtime.provider_registry import (
    PrivacyClass,
    ProviderAttemptContext,
    ProviderDescriptor,
    apply_audience_reset,
    audience_reset_decision,
    evaluate_provider,
    provider_session_namespace,
)


UTC = timezone.utc
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
STAMP = NOW.isoformat(timespec="microseconds")


class R16AudienceGuestIsolationTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _event(
        self,
        db,
        *,
        key,
        audience,
        context_space,
        principal="owner",
        text="event",
    ):
        envelope = InputSourceEnvelope(
            event_id="raw:" + key,
            surface="test",
            source_type="text",
            principal_hint=principal,
            audience_scope=audience,
            context_space=context_space,
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            correlation_id="corr:" + key,
            observed_at=NOW,
            payload_type="text/plain",
            payload={"text": text},
        )
        event = CanonicalEvent.from_envelope(
            identity_id="fish-1",
            event_type="conversation.user",
            envelope=envelope,
            principal_id=principal,
            recorded_at=NOW,
            source_namespace="r16-test",
            source_event_key=key,
            event_id_override=stable_event_id(
                "fish-1", "r16-test", key
            ),
        )
        with db.transaction(immediate=True) as conn:
            return CanonicalEventRepository().append_or_get(conn, event)

    def _purpose(self, db, purpose_id, event, payload):
        purpose = Purpose(
            purpose_id=purpose_id,
            identity_id="fish-1",
            owner_type=PurposeOwner.USER,
            owner_id="owner",
            state=PurposeState.ACTIVE,
            kind=PurposeKind.FOLLOW_UP,
            source_event_id=event.event_id,
            payload=dict(payload),
            scheduled_wall_time=None,
            timezone_name=None,
            resolved_utc_time=None,
            miss_policy=MissPolicy.RECONCILE,
        )
        with db.transaction(immediate=True) as conn:
            PurposeRepository().insert(conn, purpose, NOW)

    def _execution_scope(
        self,
        db,
        *,
        suffix,
        audience,
        context_space,
        purpose_id,
        secret,
    ):
        delegation_id = "delegation-" + suffix
        decision_id = "auth-" + suffix
        effect_id = "effect-" + suffix
        actor_id = "tool:" + suffix
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO delegations(
                       delegation_id,identity_id,principal_id,actor_id,
                       purpose_id,scope_json,valid_from,expires_at,
                       revoked_at,delegation_digest,revocable
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    delegation_id,
                    "fish-1",
                    "owner",
                    actor_id,
                    purpose_id,
                    json.dumps(
                        {
                            "scope": suffix,
                            "secret_marker": secret,
                        },
                        separators=(",", ":"),
                    ),
                    (NOW - timedelta(minutes=1)).isoformat(
                        timespec="microseconds"
                    ),
                    (NOW + timedelta(hours=1)).isoformat(
                        timespec="microseconds"
                    ),
                    None,
                    "sha256:delegation-" + suffix,
                    1,
                ),
            )
            conn.execute(
                """INSERT INTO authorization_decisions(
                       decision_id,identity_id,principal_id,actor_id,
                       purpose_id,action_class,resource_json,decision,
                       reason_code,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id,
                    "fish-1",
                    "owner",
                    actor_id,
                    purpose_id,
                    "message.send",
                    "{}",
                    "ALLOW",
                    "R16_TEST",
                    STAMP,
                ),
            )
            conn.execute(
                """INSERT INTO execution_authorizations(
                       authorization_decision_id,identity_id,principal_id,
                       principal_expires_at,actor_id,
                       actor_implementation_digest,
                       actor_authorization_digest,delegation_id,purpose_id,
                       action_class,action_digest,resource_digest,
                       context_digest,request_digest,destination,
                       audience_scope,context_space,created_at,
                       purpose_revision,purpose_occurrence_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id,
                    "fish-1",
                    "owner",
                    None,
                    actor_id,
                    "sha256:impl-" + suffix,
                    "sha256:schema-" + suffix,
                    delegation_id,
                    purpose_id,
                    "message.send",
                    "sha256:action-" + suffix,
                    "sha256:resource-" + suffix,
                    "sha256:context-" + suffix,
                    "sha256:request-" + suffix,
                    "test",
                    audience,
                    context_space,
                    STAMP,
                    1,
                    None,
                ),
            )
            conn.execute(
                """INSERT INTO effects(
                       effect_id,identity_id,intent_id,purpose_id,actor_id,
                       action_class,idempotency_key,replayable,
                       dispatch_state,request_json,receipt_id,
                       verifier_state,created_at,updated_at,
                       authorization_decision_id,purpose_revision,
                       purpose_occurrence_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    effect_id,
                    "fish-1",
                    "intent-" + suffix,
                    purpose_id,
                    actor_id,
                    "message.send",
                    "idem-" + suffix,
                    1,
                    "NEEDS_RECONCILIATION",
                    json.dumps(
                        {"secret_marker": secret},
                        separators=(",", ":"),
                    ),
                    None,
                    None,
                    STAMP,
                    STAMP,
                    decision_id,
                    1,
                    None,
                ),
            )
        return delegation_id, effect_id

    @staticmethod
    def _blocks(context):
        return {block.kind: block for block in context.blocks}

    def _seed_scoped_runtime(self, db):
        private_event = self._event(
            db,
            key="private-purpose",
            audience="PRIVATE",
            context_space="PERSONAL",
            text="private follow-up",
        )
        group_event = self._event(
            db,
            key="group-purpose",
            audience="GROUP",
            context_space="GROUP",
            text="group follow-up",
        )
        self._purpose(
            db,
            "purpose-private",
            private_event,
            {"secret_marker": "PRIVATE_PURPOSE_SECRET"},
        )
        self._purpose(
            db,
            "purpose-group",
            group_event,
            {"shared_marker": "GROUP_PURPOSE"},
        )
        self._execution_scope(
            db,
            suffix="private",
            audience="PRIVATE",
            context_space="PERSONAL",
            purpose_id="purpose-private",
            secret="PRIVATE_EFFECT_SECRET",
        )
        self._execution_scope(
            db,
            suffix="group",
            audience="GROUP",
            context_space="GROUP",
            purpose_id="purpose-group",
            secret="GROUP_EFFECT",
        )

    def test_group_context_recomputes_exact_state_instead_of_redacting_private_rows(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._seed_scoped_runtime(db)
            context = ContextAssembler(db).assemble(
                ContextRequest(
                    identity_id="fish-1",
                    principal_id="owner",
                    audience_scope="GROUP",
                    context_space="GROUP",
                    viewer_principal_ids=("owner", "guest-1"),
                    turn_text="继续",
                    identity_block={
                        "identity_id": "fish-1",
                        "private_persona": "OWNER_ONLY_PERSONA",
                    },
                    shared_identity_block={
                        "display_name": "XiaoYu",
                    },
                    continuation=True,
                ),
                now=NOW,
            )
            blocks = self._blocks(context)

            self.assertEqual(
                blocks["IDENTITY"].payload,
                {
                    "identity_id": "fish-1",
                    "display_name": "XiaoYu",
                },
            )
            self.assertEqual(
                blocks["AUDIENCE_BOUNDARY"].payload[
                    "viewer_principal_ids"
                ],
                ["guest-1", "owner"],
            )

            purposes = blocks["ACTIVE_PURPOSES"].payload
            self.assertEqual(
                [item["purpose_id"] for item in purposes],
                ["purpose-group"],
            )
            self.assertNotIn("payload", purposes[0])

            permissions = blocks["PERMISSIONS"].payload
            self.assertEqual(
                [item["delegation_id"] for item in permissions],
                ["delegation-group"],
            )
            self.assertEqual(
                permissions[0]["scope"]["secret_marker"],
                "GROUP_EFFECT",
            )

            effects = blocks["UNRESOLVED_EFFECTS"].payload
            self.assertEqual(
                [item["effect_id"] for item in effects],
                ["effect-group"],
            )
            self.assertNotIn("request", effects[0])

            encoded = json.dumps(
                [block.payload for block in context.blocks],
                ensure_ascii=False,
                sort_keys=True,
            )
            for secret in (
                "OWNER_ONLY_PERSONA",
                "PRIVATE_PURPOSE_SECRET",
                "PRIVATE_EFFECT_SECRET",
                "delegation-private",
                "effect-private",
                "purpose-private",
            ):
                self.assertNotIn(secret, encoded)

    def test_private_context_rejects_mixed_or_missing_viewer_set_before_assembly(self):
        with self.assertRaisesRegex(
            ValueError,
            "viewer_principal_ids",
        ):
            ContextRequest(
                identity_id="fish-1",
                principal_id="owner",
                audience_scope="PRIVATE",
                context_space="PERSONAL",
                viewer_principal_ids=("owner", "guest-1"),
                turn_text="hello",
                identity_block={
                    "identity_id": "fish-1",
                    "private_persona": "OWNER_ONLY_PERSONA",
                },
            )
        with self.assertRaisesRegex(
            ValueError,
            "viewer_principal_ids",
        ):
            ContextRequest(
                identity_id="fish-1",
                principal_id="owner",
                audience_scope="PRIVATE",
                context_space="PERSONAL",
                viewer_principal_ids=(),
                turn_text="hello",
                identity_block={
                    "identity_id": "fish-1",
                    "private_persona": "OWNER_ONLY_PERSONA",
                },
            )

    def test_private_context_does_not_inherit_group_bound_execution_state(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._seed_scoped_runtime(db)
            context = ContextAssembler(db).assemble(
                ContextRequest(
                    identity_id="fish-1",
                    principal_id="owner",
                    audience_scope="PRIVATE",
                    context_space="PERSONAL",
                    turn_text="hello",
                    identity_block={
                        "identity_id": "fish-1",
                        "private_persona": "OWNER_ONLY_PERSONA",
                    },
                    viewer_principal_ids=("owner",),
                ),
                now=NOW,
            )
            blocks = self._blocks(context)
            self.assertEqual(
                blocks["IDENTITY"].payload["private_persona"],
                "OWNER_ONLY_PERSONA",
            )
            self.assertEqual(
                [
                    item["purpose_id"]
                    for item in blocks["ACTIVE_PURPOSES"].payload
                ],
                ["purpose-private"],
            )
            self.assertEqual(
                [
                    item["delegation_id"]
                    for item in blocks["PERMISSIONS"].payload
                ],
                ["delegation-private"],
            )
            self.assertEqual(
                [
                    item["effect_id"]
                    for item in blocks["UNRESOLVED_EFFECTS"].payload
                ],
                ["effect-private"],
            )

    def test_guest_context_gets_no_owner_private_runtime_or_identity_projection(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._seed_scoped_runtime(db)
            context = ContextAssembler(db).assemble(
                ContextRequest(
                    identity_id="fish-1",
                    principal_id="guest-1",
                    audience_scope="GUEST",
                    context_space="GUEST",
                    viewer_principal_ids=("guest-1",),
                    turn_text="hello",
                    identity_block={
                        "identity_id": "fish-1",
                        "private_persona": "OWNER_ONLY_PERSONA",
                    },
                ),
                now=NOW,
            )
            blocks = self._blocks(context)
            self.assertEqual(
                blocks["IDENTITY"].payload,
                {"identity_id": "fish-1"},
            )
            for forbidden in (
                "RELATIONSHIP_POLICY",
                "PERMISSIONS",
                "ACTIVE_PURPOSES",
                "CURRENT_CORRECTIONS",
                "UNRESOLVED_EFFECTS",
                "PROFILE",
                "MEMORY_FACTS",
                "SUMMARY",
            ):
                self.assertNotIn(forbidden, blocks)

    def test_non_private_context_requires_explicit_viewer_set(self):
        with self.assertRaisesRegex(
            ValueError,
            "viewer_principal_ids",
        ):
            ContextRequest(
                identity_id="fish-1",
                principal_id="owner",
                audience_scope="GROUP",
                context_space="GROUP",
                turn_text="hello",
                identity_block={"identity_id": "fish-1"},
            )

        with self.assertRaises(FreshnessChanged):
            dual_guarded_chat(
                lambda *args, **kwargs: ("should-not-run", {}),
                {},
                [],
                "not-opened.sqlite3",
                "not-opened-r47.sqlite3",
                0,
                [],
                audience_scope="GROUP",
                context_space="GROUP",
                required_privacy_class="PUBLIC",
            )

    @staticmethod
    def _descriptor():
        return ProviderDescriptor(
            provider_id="provider-a",
            capability="chat.completion",
            descriptor_digest="sha256:descriptor",
            capability_digest="sha256:capability",
            implementation_digest="sha256:implementation",
            endpoint_scope="REMOTE",
            privacy_classes=(
                PrivacyClass.PUBLIC,
                PrivacyClass.SHARED,
                PrivacyClass.OWNER_PRIVATE,
            ),
        )

    @classmethod
    def _attempt(
        cls,
        *,
        audience="GROUP",
        context_space="GROUP",
        principal="owner",
        viewers=("owner", "guest-1"),
        privacy=PrivacyClass.SHARED,
    ):
        descriptor = cls._descriptor()
        return ProviderAttemptContext(
            identity_id="fish-1",
            principal_id=principal,
            audience_scope=audience,
            context_space=context_space,
            context_generation="gen-1",
            provider_id=descriptor.provider_id,
            required_capability=descriptor.capability,
            required_privacy_class=privacy,
            provider_descriptor_digest=descriptor.descriptor_digest,
            provider_capability_digest=descriptor.capability_digest,
            provider_implementation_digest=
                descriptor.implementation_digest,
            owner_principal_id="owner",
            viewer_principal_ids=tuple(viewers),
        )

    def test_viewer_set_change_resets_hidden_provider_state_and_namespace(self):
        before = self._attempt(viewers=("owner", "guest-1"))
        after = self._attempt(viewers=("owner", "guest-2"))
        decision = audience_reset_decision(before, after)
        self.assertTrue(decision.required)
        self.assertIn(
            "viewer_principal_ids_changed",
            decision.reasons,
        )
        self.assertNotEqual(
            provider_session_namespace(before),
            provider_session_namespace(after),
        )

        state = {
            "private_retrieval": object(),
            "private_profile": object(),
            "cached_context": object(),
            "provider_session_kv": object(),
            "tool_delegations": object(),
            "retained_messages": object(),
            "surface_state": object(),
            "unrelated_metric": 7,
        }
        applied = apply_audience_reset(state, before, after)
        self.assertTrue(applied.required)
        for component in applied.clear_components:
            self.assertNotIn(component, state)
        self.assertEqual(state["unrelated_metric"], 7)

    def test_owner_private_provider_denies_mixed_viewer_set(self):
        descriptor = self._descriptor()
        attempt = self._attempt(
            audience="PRIVATE",
            context_space="PERSONAL",
            principal="owner",
            viewers=("owner", "guest-1"),
            privacy=PrivacyClass.OWNER_PRIVATE,
        )
        result = evaluate_provider(descriptor, attempt)
        self.assertFalse(result.allowed)
        self.assertIn(
            "owner_private_viewer_set_mismatch",
            result.reasons,
        )


if __name__ == "__main__":
    unittest.main()
