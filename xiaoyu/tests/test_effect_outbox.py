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
    EffectBindingError,
    EffectNotAuthorized,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.effects import OutboxRepository
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
        expires_at=NOW + timedelta(hours=1),
    )


def actor():
    return ActorContext(
        actor_id="tool:qq",
        actor_type="tool",
        implementation_digest="sha256:tool",
        provider_id="napcat",
        device_id="laptop",
        trust_tier="first_party",
    )


def delegation():
    return Delegation(
        delegation_id="del-1",
        issued_by_principal="owner",
        issued_to_actor="tool:qq",
        purpose_id="purpose-1",
        action_classes=("message.send",),
        resources=("qq:owner",),
        max_effect={"messages": 1},
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        revocable=True,
    )


def action(replayable=True, idempotency_key="idem-1"):
    return ActionRequest(
        action_class="message.send",
        risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        parameters={"messages": 1},
        replayable=replayable,
        idempotency_key=idempotency_key,
    )


def resource():
    return ResourceRef(kind="qq", identifier="owner", attributes={"private": True})


def context():
    return AuthorizationContext(
        context_space="PERSONAL",
        audience_scope="PRIVATE",
        surface="desktop",
        metadata={},
    )


def effect(replayable=True, idempotency_key="idem-1"):
    return EffectIntent(
        effect_id="effect-1",
        intent_id="intent-1",
        purpose_id="purpose-1",
        actor_id="tool:qq",
        action_class="message.send",
        request={"recipient": "owner", "text": "done"},
        idempotency_key=idempotency_key,
        replayable=replayable,
        created_at=NOW,
    )


class EffectOutboxTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _enqueue(self, db, auth_result=None, coordinator=None, eff=None, act=None):
        coordinator = coordinator or EffectCoordinator(db)
        coordinator.enqueue_authorized(
            decision_id="auth-1",
            outbox_id="outbox-1",
            identity_id="fish-1",
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=act or action(),
            resource=resource(),
            context=context(),
            auth_result=auth_result
            or AuthorizationResult(
                AuthorizationDecision.ALLOW, "VALID_DELEGATION", "del-1"
            ),
            effect=eff or effect(),
            destination="qq",
            payload={"recipient": "owner", "text": "done"},
            created_at=NOW,
        )

    def test_authorization_effect_and_outbox_are_atomic(self):
        class BrokenOutbox(OutboxRepository):
            def enqueue(self, *args, **kwargs):
                raise RuntimeError("synthetic outbox failure")

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            coordinator = EffectCoordinator(db, outbox_repo=BrokenOutbox())
            with self.assertRaisesRegex(RuntimeError, "synthetic outbox failure"):
                self._enqueue(db, coordinator=coordinator)
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM authorization_decisions"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0], 0
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_payload_must_match_effect_request(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            coordinator = EffectCoordinator(db)
            with self.assertRaises(EffectBindingError):
                coordinator.enqueue_authorized(
                    decision_id="auth-bind",
                    outbox_id="outbox-bind",
                    identity_id="fish-1",
                    principal=principal(),
                    actor=actor(),
                    delegation=delegation(),
                    action=action(),
                    resource=resource(),
                    context=context(),
                    auth_result=AuthorizationResult(
                        AuthorizationDecision.ALLOW,
                        "VALID_DELEGATION",
                        "del-1",
                    ),
                    effect=effect(),
                    destination="qq",
                    payload={"recipient": "outsider", "text": "done"},
                    created_at=NOW,
                )
            conn = db.connect()
            try:
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

    def test_non_allow_decision_cannot_enqueue_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            with self.assertRaises(EffectNotAuthorized):
                self._enqueue(
                    db,
                    auth_result=AuthorizationResult(
                        AuthorizationDecision.ASK, "CONFIRM"
                    ),
                )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0], 0
                )
            finally:
                conn.close()

    def test_successful_dispatch_marks_sent_and_succeeded(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)
            calls = []

            def transport(payload, idem):
                calls.append((payload, idem))
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED, external_ref="msg-1"
                )

            dispatcher = OutboxDispatcher(db, {"qq": transport})
            self.assertEqual(dispatcher.dispatch_once(now=NOW), 1)
            self.assertEqual(len(calls), 1)
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0], "SENT"
                )
                self.assertEqual(
                    conn.execute("SELECT dispatch_state FROM effects").fetchone()[0],
                    "SUCCEEDED",
                )
            finally:
                conn.close()

    def test_unclassified_transport_exception_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)

            def transport(payload, idem):
                raise TimeoutError("ambiguous timeout")

            OutboxDispatcher(db, {"qq": transport}).dispatch_once(now=NOW)
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
                self.assertEqual(
                    conn.execute("SELECT dispatch_state FROM effects").fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
            finally:
                conn.close()

    def test_explicit_retryable_outcome_requeues_only_idempotent_replayable_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)

            def transport(payload, idem):
                return DispatchOutcome(
                    DispatchStatus.FAILED_RETRYABLE, retry_after_s=2
                )

            OutboxDispatcher(db, {"qq": transport}).dispatch_once(now=NOW)
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT state,next_attempt_at FROM outbox"
                ).fetchone()
                self.assertEqual(row["state"], "FAILED_RETRYABLE")
                self.assertIsNotNone(row["next_attempt_at"])
                self.assertEqual(
                    conn.execute("SELECT dispatch_state FROM effects").fetchone()[0],
                    "QUEUED",
                )
            finally:
                conn.close()

    def test_crash_after_external_call_is_not_blindly_retried(self):
        class SimulatedCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)
            calls = []

            def transport(payload, idem):
                calls.append(1)
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED, external_ref="msg-1"
                )

            def fault(stage, row):
                if stage == "after_dispatch":
                    raise SimulatedCrash()

            dispatcher = OutboxDispatcher(
                db, {"qq": transport}, fault_hook=fault
            )
            with self.assertRaises(SimulatedCrash):
                dispatcher.dispatch_once(now=NOW)
            self.assertEqual(len(calls), 1)

            recovered = OutboxDispatcher(db, {"qq": transport})
            self.assertEqual(
                recovered.recover_inflight(now=NOW + timedelta(seconds=1)), 1
            )
            self.assertEqual(
                recovered.dispatch_once(now=NOW + timedelta(seconds=2)), 0
            )
            self.assertEqual(len(calls), 1)
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
                self.assertEqual(
                    conn.execute("SELECT dispatch_state FROM effects").fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
