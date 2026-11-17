from __future__ import annotations

import json
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
    PrincipalContext,
    ResourceRef,
    RiskTier,
)
from xiaoyu.core.authorization import AuthorizationPolicy
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.grants import AuthorizationDecisionRepository


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def principal(level="OWNER_AUTHENTICATED", expires=None):
    return PrincipalContext(
        principal_id="owner",
        authentication_level=level,
        confidence=1.0 if level == "OWNER_AUTHENTICATED" else 0.3,
        evidence_classes=("LOCAL_OS_SESSION",),
        viewer_set=("owner",),
        session_scope="desktop",
        expires_at=expires,
    )


def actor(actor_id="tool:qq"):
    return ActorContext(
        actor_id=actor_id,
        actor_type="tool",
        implementation_digest="sha256:tool",
        provider_id="napcat",
        device_id="laptop",
        trust_tier="first_party",
    )


def context():
    return AuthorizationContext(
        context_space="PERSONAL",
        audience_scope="PRIVATE",
        surface="desktop",
        metadata={},
    )


def resource(private=False, identifier="owner"):
    return ResourceRef(kind="qq", identifier=identifier, attributes={"private": private})


def action(risk, messages=1):
    return ActionRequest(
        action_class="message.send",
        risk_tier=risk,
        parameters={"messages": messages},
        replayable=True,
        idempotency_key="idem-1",
    )


def delegation(**overrides):
    values = dict(
        delegation_id="del-1",
        issued_by_principal="owner",
        issued_to_actor="tool:qq",
        purpose_id="purpose-1",
        action_classes=("message.send",),
        resources=("qq:owner",),
        max_effect={"messages": 1},
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        revocable=True,
    )
    values.update(overrides)
    return Delegation(**values)


class AuthorizationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = AuthorizationPolicy()

    def evaluate(self, p=None, a=None, d=None, act=None, r=None):
        return self.policy.evaluate(
            p or principal(), a or actor(), d,
            act or action(RiskTier.T0_OBSERVE), r or resource(), context(), NOW,
        )

    def test_observe_is_allowed_but_private_observe_requires_strong_owner(self):
        self.assertEqual(self.evaluate().decision, AuthorizationDecision.ALLOW)
        result = self.evaluate(
            p=principal("UNKNOWN"),
            r=resource(private=True),
        )
        self.assertEqual(result.decision, AuthorizationDecision.DENY)

    def test_t1_owner_local_reversible_is_allowed(self):
        result = self.evaluate(act=action(RiskTier.T1_LOCAL_REVERSIBLE))
        self.assertEqual(result.decision, AuthorizationDecision.ALLOW)

    def test_t2_t3_require_confirmation_without_delegation(self):
        for tier in (RiskTier.T2_OWNER_STATE_MUTATION, RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE):
            result = self.evaluate(act=action(tier))
            self.assertEqual(result.decision, AuthorizationDecision.ASK)

    def test_valid_delegation_allows_t3(self):
        result = self.evaluate(
            d=delegation(),
            act=action(RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE),
        )
        self.assertEqual(result.decision, AuthorizationDecision.ALLOW)
        self.assertEqual(result.matched_delegation_id, "del-1")

    def test_wrong_actor_resource_expiry_and_limit_do_not_auto_allow(self):
        cases = (
            dict(a=actor("tool:other"), d=delegation()),
            dict(r=resource(identifier="friend"), d=delegation()),
            dict(d=delegation(expires_at=NOW)),
            dict(d=delegation(), act=action(RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE, messages=2)),
        )
        for kwargs in cases:
            kwargs.setdefault("act", action(RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE))
            result = self.evaluate(**kwargs)
            self.assertEqual(result.decision, AuthorizationDecision.ASK)
            self.assertTrue(result.reason_code.startswith("DELEGATION_INVALID_"))

    def test_expired_principal_is_denied_even_for_observe(self):
        result = self.evaluate(p=principal(expires=NOW))
        self.assertEqual(result.decision, AuthorizationDecision.DENY)
        self.assertEqual(result.reason_code, "PRINCIPAL_EXPIRED")

    def test_decision_repository_records_audit_context(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "identity.sqlite3")
            apply_migrations(db)
            result = self.evaluate(
                d=delegation(),
                act=action(RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE),
            )
            with db.transaction() as conn:
                AuthorizationDecisionRepository().record(
                    conn=conn,
                    decision_id="auth-1",
                    identity_id="fish-1",
                    principal=principal(),
                    actor=actor(),
                    delegation=delegation(),
                    action=action(RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE),
                    resource=resource(),
                    context=context(),
                    result=result,
                    created_at=NOW,
                )
                row = conn.execute(
                    "SELECT decision,reason_code,resource_json FROM authorization_decisions WHERE decision_id='auth-1'"
                ).fetchone()
                self.assertEqual(row["decision"], "ALLOW")
                audit = json.loads(row["resource_json"])
                self.assertEqual(audit["matched_delegation_id"], "del-1")
                self.assertEqual(audit["surface"], "desktop")


if __name__ == "__main__":
    unittest.main()
