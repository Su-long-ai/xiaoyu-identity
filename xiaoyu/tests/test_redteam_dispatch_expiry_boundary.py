from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus, EffectCoordinator
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import OutboxDispatcher
import xiaoyu.runtime.outbox as outbox_runtime


START = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)


class AdvancingDateTime(datetime):
    calls = 0

    @classmethod
    def now(cls, tz=None):
        cls.calls += 1
        value = START if cls.calls == 1 else START + timedelta(seconds=2)
        if tz is None:
            return value
        return value.astimezone(tz)


class DispatchExpiryBoundaryRedTeamTests(unittest.TestCase):
    def test_delegation_expiring_after_claim_is_rechecked_at_send_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)

            principal = PrincipalContext(
                principal_id="owner",
                authentication_level="OWNER_AUTHENTICATED",
                confidence=1.0,
                evidence_classes=("LOCAL_OS_SESSION",),
                viewer_set=("owner",),
                session_scope="desktop",
                expires_at=START + timedelta(hours=1),
            )
            actor = ActorContext(
                actor_id="tool:qq",
                actor_type="tool",
                implementation_digest="sha256:qq-v1",
                provider_id=None,
                device_id="laptop",
                trust_tier="first_party",
                authorization_digest="sha256:qq-schema-v1",
            )
            delegation = Delegation(
                delegation_id="del-expiring",
                issued_by_principal="owner",
                issued_to_actor="tool:qq",
                purpose_id=None,
                action_classes=("message.send",),
                resources=("qq:owner",),
                max_effect={"messages": 1},
                valid_from=START - timedelta(minutes=1),
                expires_at=START + timedelta(seconds=1),
                revocable=True,
            )
            action = ActionRequest(
                action_class="message.send",
                risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
                parameters={"messages": 1},
                replayable=True,
                idempotency_key="idem-expiring",
            )
            effect = EffectIntent(
                effect_id="effect-expiring",
                intent_id="intent-expiring",
                purpose_id=None,
                actor_id="tool:qq",
                action_class="message.send",
                request={"recipient": "owner", "text": "hello"},
                idempotency_key="idem-expiring",
                replayable=True,
                created_at=START,
            )
            EffectCoordinator(db).enqueue_authorized(
                decision_id="auth-expiring",
                outbox_id="outbox-expiring",
                identity_id="fish-1",
                principal=principal,
                actor=actor,
                delegation=delegation,
                action=action,
                resource=ResourceRef(
                    kind="qq",
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
                    "del-expiring",
                ),
                effect=effect,
                destination="qq",
                payload=effect.request,
                created_at=START,
            )

            calls = []

            def transport(payload, idem):
                calls.append((payload, idem))
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="msg-should-not-send",
                )

            AdvancingDateTime.calls = 0
            with patch.object(outbox_runtime, "datetime", AdvancingDateTime):
                processed = OutboxDispatcher(
                    db,
                    {"qq": transport},
                ).dispatch_once()

            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

            conn = db.connect()
            try:
                row = conn.execute(
                    """SELECT dispatch_state,verifier_state
                       FROM effects WHERE effect_id='effect-expiring'"""
                ).fetchone()
                self.assertEqual(row["dispatch_state"], "FAILED")
                self.assertIn("delegation expired", row["verifier_state"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
