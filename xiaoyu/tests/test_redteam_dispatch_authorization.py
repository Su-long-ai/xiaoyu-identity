from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    AuthorizationDecision,
    Delegation,
    EffectIntent,
    PrincipalContext,
    ResourceRef,
    RiskTier,
)
from xiaoyu.core.authorization import AuthorizationResult
from xiaoyu.core.effects import (
    DispatchOutcome,
    DispatchStatus,
    EffectCoordinator,
    EffectNotAuthorized,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.execution_auth import (
    ActorRegistryRepository,
    DelegationRepository,
)
from xiaoyu.runtime import OutboxDispatcher


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def principal():
    return PrincipalContext(
        principal_id="owner",
        authentication_level="OWNER_AUTHENTICATED",
        confidence=1.0,
        evidence_classes=("LOCAL_OS_SESSION",),
        viewer_set=("owner",),
        session_scope="desktop",
        expires_at=NOW + timedelta(minutes=5),
    )


def actor(
    implementation_digest="sha256:impl-v1",
    authorization_digest="sha256:schema-v1",
):
    return ActorContext(
        actor_id="tool:qq",
        actor_type="tool",
        implementation_digest=implementation_digest,
        provider_id="napcat",
        device_id="laptop",
        trust_tier="first_party",
        authorization_digest=authorization_digest,
    )


def delegation(expires_at=None):
    return Delegation(
        delegation_id="del-auth",
        issued_by_principal="owner",
        issued_to_actor="tool:qq",
        purpose_id="purpose-auth",
        action_classes=("message.send",),
        resources=("qq:owner",),
        max_effect={"messages": 1},
        valid_from=NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(minutes=10),
        revocable=True,
    )


def action():
    return ActionRequest(
        action_class="message.send",
        risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        parameters={"messages": 1},
        replayable=True,
        idempotency_key="idem-auth",
    )


def resource():
    return ResourceRef(
        kind="qq",
        identifier="owner",
        attributes={"private": True},
    )


def context():
    return AuthorizationContext(
        context_space="PERSONAL",
        audience_scope="PRIVATE",
        surface="qq",
        metadata={},
    )


def effect():
    return EffectIntent(
        effect_id="effect-auth",
        intent_id="intent-auth",
        purpose_id="purpose-auth",
        actor_id="tool:qq",
        action_class="message.send",
        request={"recipient": "owner", "text": "private"},
        idempotency_key="idem-auth",
        replayable=True,
        created_at=NOW,
    )


class DispatchAuthorizationRedTeamTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _enqueue(self, db, current_actor=None, current_delegation=None):
        current_actor = current_actor or actor()
        current_delegation = current_delegation or delegation()
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-decision",
            outbox_id="outbox-auth",
            identity_id="fish-1",
            principal=principal(),
            actor=current_actor,
            delegation=current_delegation,
            action=action(),
            resource=resource(),
            context=context(),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                current_delegation.delegation_id,
            ),
            effect=effect(),
            destination="qq",
            payload=effect().request,
            created_at=NOW,
        )

    def _dispatch(self, db, when):
        calls = []

        def transport(payload, idem):
            calls.append(payload)
            return DispatchOutcome(
                DispatchStatus.SUCCEEDED,
                external_ref="msg-1",
            )

        processed = OutboxDispatcher(
            db, {"qq": transport}
        ).dispatch_once(now=when)
        return processed, calls

    def test_expired_delegation_blocks_transport(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)
            processed, calls = self._dispatch(
                db, NOW + timedelta(minutes=11)
            )
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT dispatch_state,verifier_state FROM effects"
                ).fetchone()
                self.assertEqual(row["dispatch_state"], "FAILED")
                self.assertIn("delegation expired", row["verifier_state"])
            finally:
                conn.close()

    def test_revoked_delegation_blocks_transport(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)
            with db.transaction(immediate=True) as conn:
                self.assertTrue(
                    DelegationRepository().revoke(
                        conn,
                        "del-auth",
                        NOW + timedelta(seconds=1),
                    )
                )
            processed, calls = self._dispatch(
                db, NOW + timedelta(seconds=2)
            )
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_actor_implementation_or_schema_change_invalidates_queued_effect(self):
        variants = (
            actor(
                implementation_digest="sha256:impl-v2",
                authorization_digest="sha256:schema-v1",
            ),
            actor(
                implementation_digest="sha256:impl-v1",
                authorization_digest="sha256:schema-v2",
            ),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                with tempfile.TemporaryDirectory() as td:
                    db = self._db(td)
                    self._enqueue(db)
                    with db.transaction(immediate=True) as conn:
                        ActorRegistryRepository().register(
                            conn,
                            changed,
                            NOW + timedelta(seconds=1),
                        )
                    processed, calls = self._dispatch(
                        db, NOW + timedelta(seconds=2)
                    )
                    self.assertEqual(processed, 0)
                    self.assertEqual(calls, [])

    def test_same_standing_delegation_cannot_silently_authorize_changed_actor(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)
            with self.assertRaises(Exception):
                EffectCoordinator(db).enqueue_authorized(
                    decision_id="auth-decision-2",
                    outbox_id="outbox-auth-2",
                    identity_id="fish-1",
                    principal=principal(),
                    actor=actor(
                        implementation_digest="sha256:impl-v2"
                    ),
                    delegation=delegation(),
                    action=ActionRequest(
                        action_class="message.send",
                        risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
                        parameters={"messages": 1},
                        replayable=True,
                        idempotency_key="idem-auth-2",
                    ),
                    resource=resource(),
                    context=context(),
                    auth_result=AuthorizationResult(
                        AuthorizationDecision.ALLOW,
                        "VALID_DELEGATION",
                        "del-auth",
                    ),
                    effect=EffectIntent(
                        effect_id="effect-auth-2",
                        intent_id="intent-auth-2",
                        purpose_id="purpose-auth",
                        actor_id="tool:qq",
                        action_class="message.send",
                        request={"recipient": "owner", "text": "second"},
                        idempotency_key="idem-auth-2",
                        replayable=True,
                        created_at=NOW,
                    ),
                    destination="qq",
                    payload={"recipient": "owner", "text": "second"},
                    created_at=NOW,
                )

    def test_forged_allow_does_not_override_private_group_policy(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            grouped = AuthorizationContext(
                context_space="PERSONAL",
                audience_scope="GROUP",
                surface="qq",
                metadata={},
            )
            with self.assertRaises(EffectNotAuthorized):
                EffectCoordinator(db).enqueue_authorized(
                    decision_id="auth-forged",
                    outbox_id="outbox-forged",
                    identity_id="fish-1",
                    principal=principal(),
                    actor=actor(),
                    delegation=delegation(),
                    action=action(),
                    resource=resource(),
                    context=grouped,
                    auth_result=AuthorizationResult(
                        AuthorizationDecision.ALLOW,
                        "FORGED",
                        "del-auth",
                    ),
                    effect=effect(),
                    destination="qq",
                    payload=effect().request,
                    created_at=NOW,
                )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM effects"
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
