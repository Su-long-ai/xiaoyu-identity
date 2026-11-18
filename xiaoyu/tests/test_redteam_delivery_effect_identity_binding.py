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
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import DeliveryCoordinator, DeliveryLedger


NOW = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)


def principal():
    return PrincipalContext(
        principal_id="owner",
        authentication_level="OWNER_AUTHENTICATED",
        confidence=1.0,
        evidence_classes=("LOCAL_OS_SESSION",),
        viewer_set=("owner",),
        session_scope="desktop",
        expires_at=NOW + timedelta(hours=1),
    )


def actor():
    return ActorContext(
        actor_id="surface:delivery",
        actor_type="surface",
        implementation_digest="sha256:surface-delivery-v1",
        provider_id=None,
        device_id="laptop",
        trust_tier="first_party",
        authorization_digest="sha256:surface-delivery-schema-v1",
    )


def delegation():
    return Delegation(
        delegation_id="del-delivery-binding",
        issued_by_principal="owner",
        issued_to_actor="surface:delivery",
        purpose_id=None,
        action_classes=("notification.deliver",),
        resources=("notification:owner",),
        max_effect={"messages": 1},
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        revocable=True,
    )


def action(idem: str):
    return ActionRequest(
        action_class="notification.deliver",
        risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        parameters={"messages": 1},
        replayable=True,
        idempotency_key=idem,
    )


def effect(*, logical_id: str, purpose_id=None, suffix="x"):
    idem = "delivery-binding:" + suffix
    return EffectIntent(
        effect_id="effect-binding-" + suffix,
        intent_id="intent-binding-" + suffix,
        purpose_id=purpose_id,
        actor_id="surface:delivery",
        action_class="notification.deliver",
        request={
            "logical_notification_id": logical_id,
            "surface": "qq",
            "recipient": "owner",
            "text": "exactly once",
        },
        idempotency_key=idem,
        replayable=True,
        created_at=NOW,
    )


class DeliveryEffectIdentityBindingRedTeamTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _enqueue(self, db, *, delivery_id, logical_id, eff):
        DeliveryCoordinator(db).enqueue_attempt(
            attempt_id="attempt-" + eff.effect_id,
            delivery_id=delivery_id,
            logical_notification_id=logical_id,
            decision_id="auth-" + eff.effect_id,
            outbox_id="outbox-" + eff.effect_id,
            identity_id="fish-delivery-binding",
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=action(eff.idempotency_key),
            resource=ResourceRef(
                kind="notification",
                identifier="owner",
                attributes={"private": True},
            ),
            context=AuthorizationContext(
                context_space="PERSONAL",
                audience_scope="PRIVATE",
                surface="qq",
                metadata={},
            ),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                "del-delivery-binding",
            ),
            effect=eff,
            surface="qq",
            created_at=NOW,
        )

    def _assert_no_attempt_or_effect(self, db):
        conn = db.connect()
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM delivery_attempts").fetchone()[0],
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

    def test_effect_payload_logical_id_must_match_delivery_identity(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertTrue(
                DeliveryLedger(db).create(
                    delivery_id="delivery-ledger-a",
                    identity_id="fish-delivery-binding",
                    logical_notification_id="notice-ledger-a",
                    purpose_id=None,
                    preferred_surface="qq",
                    created_at=NOW,
                )
            )

            with self.assertRaises(ValueError):
                self._enqueue(
                    db,
                    delivery_id="delivery-ledger-a",
                    logical_id="notice-ledger-a",
                    eff=effect(
                        logical_id="notice-payload-b",
                        suffix="logical-mismatch",
                    ),
                )
            self._assert_no_attempt_or_effect(db)

    def test_effect_purpose_must_match_delivery_parent_purpose(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertTrue(
                DeliveryLedger(db).create(
                    delivery_id="delivery-purpose-a",
                    identity_id="fish-delivery-binding",
                    logical_notification_id="notice-purpose-a",
                    purpose_id="purpose-ledger-a",
                    preferred_surface="qq",
                    created_at=NOW,
                )
            )

            with self.assertRaises(ValueError):
                self._enqueue(
                    db,
                    delivery_id="delivery-purpose-a",
                    logical_id="notice-purpose-a",
                    eff=effect(
                        logical_id="notice-purpose-a",
                        purpose_id=None,
                        suffix="purpose-mismatch",
                    ),
                )
            self._assert_no_attempt_or_effect(db)


if __name__ == "__main__":
    unittest.main()
