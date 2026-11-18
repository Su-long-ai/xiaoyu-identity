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
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus, EffectCoordinator
from xiaoyu.core.identity import SelfAuthorityService
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import OutboxDispatcher
from xiaoyu.runtime.product_controls import ProductOffboardingService
from xiaoyu.runtime.product_store import CanonicalProductStore
from xiaoyu.runtime.resource_broker import ResourceBroker, ResourceMode


NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


class R20OffboardingExecutionRedTeamTests(unittest.TestCase):
    def _product(self, td: str):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        SelfAuthorityService(db).initialize(
            identity_id="fish-r20-exec",
            persona={
                "name": "小鱼",
                "identity_commitments": ["诚实", "保持身份连续"],
                "style": {"language": "zh-CN"},
                "growth_notes": [],
                "bond_description": "长期伙伴",
            },
            created_at=NOW,
            reason="r20-exec-redteam",
        )
        return db, CanonicalProductStore(
            db,
            identity_id="fish-r20-exec",
        )

    def _enqueue_purpose_free_effect(self, db: Database) -> None:
        principal = PrincipalContext(
            principal_id="owner",
            authentication_level="OWNER_AUTHENTICATED",
            confidence=1.0,
            evidence_classes=("LOCAL_OS_SESSION",),
            viewer_set=("owner",),
            session_scope="desktop",
            expires_at=NOW + timedelta(hours=1),
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
            delegation_id="del-r20-exec",
            issued_by_principal="owner",
            issued_to_actor="tool:qq",
            purpose_id=None,
            action_classes=("message.send",),
            resources=("qq:owner",),
            max_effect={"messages": 1},
            valid_from=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
            revocable=True,
        )
        action = ActionRequest(
            action_class="message.send",
            risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
            parameters={"messages": 1},
            replayable=True,
            idempotency_key="r20-offboard-effect",
        )
        effect = EffectIntent(
            effect_id="effect-r20-offboard",
            intent_id="intent-r20-offboard",
            purpose_id=None,
            actor_id="tool:qq",
            action_class="message.send",
            request={
                "recipient": "owner",
                "text": "must not send after offboarding",
            },
            idempotency_key="r20-offboard-effect",
            replayable=True,
            created_at=NOW,
        )
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-r20-offboard",
            outbox_id="outbox-r20-offboard",
            identity_id="fish-r20-exec",
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
                "del-r20-exec",
            ),
            effect=effect,
            destination="qq",
            payload=effect.request,
            created_at=NOW,
        )

    def test_successful_offboarding_fences_preexisting_queued_external_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._product(td)
            self._enqueue_purpose_free_effect(db)

            broker = ResourceBroker(mode=ResourceMode.BALANCED)
            report = ProductOffboardingService(
                store,
                resource_broker=broker,
            ).execute(
                source_event_key="offboard-before-dispatch",
                created_at=NOW + timedelta(seconds=1),
            )
            self.assertTrue(report.ok, report.blockers)
            self.assertTrue(report.paused)
            self.assertEqual(broker.mode, ResourceMode.SLEEP)

            calls = []

            def transport(payload, idem):
                calls.append((payload, idem))
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="must-not-exist",
                )

            processed = OutboxDispatcher(
                db,
                {"qq": transport},
            ).dispatch_once(now=NOW + timedelta(seconds=2))

            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects "
                        "WHERE effect_id='effect-r20-offboard'"
                    ).fetchone()[0],
                    "FAILED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM outbox "
                        "WHERE outbox_id='outbox-r20-offboard'"
                    ).fetchone()[0],
                    "FAILED_FINAL",
                )
            finally:
                conn.close()

    def test_offboarding_does_not_claim_pause_when_effect_already_dispatching(self):
        with tempfile.TemporaryDirectory() as td:
            db, store = self._product(td)
            self._enqueue_purpose_free_effect(db)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE effects
                       SET dispatch_state='DISPATCHING'
                       WHERE effect_id='effect-r20-offboard'"""
                )
                conn.execute(
                    """UPDATE outbox SET state='CLAIMED'
                       WHERE outbox_id='outbox-r20-offboard'"""
                )

            report = ProductOffboardingService(
                store,
                resource_broker=ResourceBroker(
                    mode=ResourceMode.BALANCED
                ),
            ).execute(
                source_event_key="offboard-inflight",
                created_at=NOW + timedelta(seconds=1),
            )

            self.assertFalse(report.ok)
            self.assertFalse(report.paused)
            self.assertTrue(
                any(
                    "effect-r20-offboard" in blocker
                    and "reconciliation" in blocker
                    for blocker in report.blockers
                ),
                report.blockers,
            )

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "DISPATCHING",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM outbox"
                    ).fetchone()[0],
                    "CLAIMED",
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
