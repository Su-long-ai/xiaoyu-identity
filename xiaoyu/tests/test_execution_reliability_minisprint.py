from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
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
from xiaoyu.contracts.common import canonical_json
from xiaoyu.core.authorization import AuthorizationPolicy, AuthorizationResult
from xiaoyu.core.effects import (
    DispatchOutcome,
    DispatchStatus,
    EffectBindingError,
    EffectCoordinator,
)
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.execution_auth import DelegationRepository
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime import (
    DeliveryCoordinator,
    DeliveryLedger,
    OutboxDispatcher,
    PurposeScheduler,
)


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
        implementation_digest="sha256:tool-v1",
        provider_id="napcat",
        device_id="laptop",
        trust_tier="first_party",
        authorization_digest="sha256:auth-v1",
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


def action(action_class="message.send", parameters=None):
    return ActionRequest(
        action_class=action_class,
        risk_tier=RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        parameters={"messages": 1} if parameters is None else parameters,
        replayable=True,
        idempotency_key="idem-1",
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


def effect(request=None):
    return EffectIntent(
        effect_id="effect-1",
        intent_id="intent-1",
        purpose_id="purpose-1",
        actor_id="tool:qq",
        action_class="message.send",
        request={"recipient": "owner", "text": "hello"} if request is None else request,
        idempotency_key="idem-1",
        replayable=True,
        created_at=NOW,
        purpose_revision=1,
    )


class ExecutionReliabilityMiniSprintRedTeamTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _insert_purpose(self, db):
        with db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO canonical_events(
                       event_id,identity_id,turn_id,event_type,surface,source_type,
                       principal_id,audience_scope,context_space,trust_class,
                       taint_json,eligible_for_memory,payload_type,payload_json,
                       observed_at,recorded_at,correlation_id,schema_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "source-purpose",
                    "fish-1",
                    None,
                    "conversation.user",
                    "desktop",
                    "text",
                    "owner",
                    "PRIVATE",
                    "PERSONAL",
                    "OWNER_DIRECT",
                    "[]",
                    1,
                    "text/plain",
                    "{}",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    "corr-purpose",
                    1,
                ),
            )
            PurposeRepository().insert(
                conn,
                Purpose(
                    purpose_id="purpose-1",
                    identity_id="fish-1",
                    owner_type=PurposeOwner.USER,
                    owner_id="owner",
                    state=PurposeState.ACTIVE,
                    kind=PurposeKind.TASK_COMPLETION_DELIVERY,
                    source_event_id="source-purpose",
                    payload={},
                    scheduled_wall_time=None,
                    timezone_name=None,
                    resolved_utc_time=None,
                    miss_policy=MissPolicy.RECONCILE,
                    revision=1,
                ),
                NOW,
            )

    def _enqueue(self, db, *, eff=None, act=None):
        eff = eff or effect()
        act = act or action()
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-1",
            outbox_id="outbox-1",
            identity_id="fish-1",
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=act,
            resource=resource(),
            context=context(),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                "del-1",
            ),
            effect=eff,
            destination="qq",
            payload=eff.request,
            created_at=NOW,
        )

    def test_authorized_owner_cannot_send_to_outsider(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            outsider = effect({"recipient": "outsider", "text": "hello"})
            with self.assertRaises(EffectBindingError):
                self._enqueue(db, eff=outsider)

    def test_unknown_action_and_unknown_parameter_are_denied(self):
        policy = AuthorizationPolicy()
        unknown = policy.evaluate(
            principal(),
            actor(),
            delegation(),
            action("message.send.v2"),
            resource(),
            context(),
            NOW,
        )
        self.assertEqual(unknown.decision, AuthorizationDecision.DENY)

        extra = policy.evaluate(
            principal(),
            actor(),
            delegation(),
            action(parameters={"messages": 1, "surprise": 1}),
            resource(),
            context(),
            NOW,
        )
        self.assertEqual(extra.decision, AuthorizationDecision.DENY)

    def test_revocation_after_claim_before_transport_is_revalidated(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            calls = []

            def fault(stage, row):
                if stage == "after_claim":
                    with db.transaction(immediate=True) as conn:
                        DelegationRepository().revoke(
                            conn,
                            "del-1",
                            NOW + timedelta(seconds=1),
                        )

            def transport(payload, idem):
                calls.append(payload)
                return DispatchOutcome(DispatchStatus.SUCCEEDED)

            processed = OutboxDispatcher(
                db,
                {"qq": transport},
                fault_hook=fault,
            ).dispatch_once(now=NOW + timedelta(seconds=2))
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_crash_after_claim_before_dispatch_is_safe_to_requeue(self):
        class SimulatedCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            calls = []

            def fault(stage, row):
                if stage == "after_claim":
                    raise SimulatedCrash()

            def transport(payload, idem):
                calls.append(payload)
                return DispatchOutcome(DispatchStatus.SUCCEEDED)

            dispatcher = OutboxDispatcher(
                db,
                {"qq": transport},
                fault_hook=fault,
            )
            with self.assertRaises(SimulatedCrash):
                dispatcher.dispatch_once(now=NOW)
            self.assertEqual(calls, [])

            recovered = OutboxDispatcher(db, {"qq": transport})
            self.assertEqual(
                recovered.recover_inflight(NOW + timedelta(seconds=1)),
                1,
            )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "PENDING",
                )
                self.assertEqual(
                    conn.execute("SELECT dispatch_state FROM effects").fetchone()[0],
                    "QUEUED",
                )
            finally:
                conn.close()

            self.assertEqual(
                recovered.dispatch_once(now=NOW + timedelta(seconds=2)),
                1,
            )
            self.assertEqual(len(calls), 1)

    def test_cancel_after_unknown_result_stays_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)

            def transport(payload, idem):
                raise TimeoutError("ack lost")

            OutboxDispatcher(db, {"qq": transport}).dispatch_once(now=NOW)
            with db.transaction(immediate=True) as conn:
                cancelled = PurposeRepository().cancel(
                    conn,
                    "purpose-1",
                    NOW + timedelta(seconds=1),
                )
            self.assertFalse(cancelled)
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT state,revision FROM purposes WHERE purpose_id='purpose-1'"
                ).fetchone()
                self.assertEqual(
                    tuple(row),
                    ("NEEDS_RECONCILIATION", 1),
                )
            finally:
                conn.close()

    def test_provider_interface_digest_change_blocks_queued_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """INSERT INTO provider_registry(
                           provider_id,capability,descriptor_json,artifact_digest,
                           descriptor_digest,interface_digest,tool_schema_digest,
                           lifecycle_state,health_state_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "napcat",
                        "message.send",
                        "{}",
                        "sha256:provider-v1",
                        "sha256:descriptor-v1",
                        "sha256:interface-v1",
                        "sha256:schema-v1",
                        "ACTIVE",
                        '{"liveness":"UP","readiness":"READY"}',
                        NOW.isoformat(),
                    ),
                )
            self._enqueue(db)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE provider_registry
                       SET interface_digest='sha256:interface-v2',
                           updated_at=?
                       WHERE provider_id='napcat'""",
                    ((NOW + timedelta(seconds=1)).isoformat(),),
                )

            calls = []
            processed = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: (
                        calls.append(payload)
                        or DispatchOutcome(DispatchStatus.SUCCEEDED)
                    )
                },
            ).dispatch_once(now=NOW + timedelta(seconds=2))
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_cancel_after_claim_before_transport_blocks_send(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            calls = []

            def fault(stage, row):
                if stage == "after_claim":
                    with db.transaction(immediate=True) as conn:
                        self.assertTrue(
                            PurposeRepository().cancel(
                                conn,
                                "purpose-1",
                                NOW + timedelta(seconds=1),
                            )
                        )

            processed = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: (
                        calls.append(payload)
                        or DispatchOutcome(DispatchStatus.SUCCEEDED)
                    )
                },
                fault_hook=fault,
            ).dispatch_once(now=NOW + timedelta(seconds=2))
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])
            conn = db.connect()
            try:
                self.assertEqual(
                    tuple(
                        conn.execute(
                            "SELECT state,revision FROM purposes"
                        ).fetchone()
                    ),
                    ("CANCELLED", 2),
                )
            finally:
                conn.close()

    def test_missed_reschedule_has_durable_limit(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            first_due = NOW - timedelta(minutes=2)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purposes
                       SET state='SCHEDULED',
                           scheduled_wall_time=?,
                           timezone='UTC',
                           resolved_utc_time=?,
                           miss_policy='RESCHEDULE',
                           payload_json=?
                       WHERE purpose_id='purpose-1'""",
                    (
                        first_due.isoformat(timespec="microseconds"),
                        first_due.isoformat(timespec="microseconds"),
                        '{"max_auto_reschedules":1,"reschedule_seconds":30}',
                    ),
                )

            first = PurposeScheduler(db, "fish-1").reconcile_due(NOW)
            self.assertEqual(first[0].reason, "MISSED_RESCHEDULED")
            conn = db.connect()
            try:
                row = conn.execute(
                    """SELECT state,revision,auto_reschedule_count
                       FROM purposes WHERE purpose_id='purpose-1'"""
                ).fetchone()
                self.assertEqual(tuple(row), ("SCHEDULED", 2, 1))
            finally:
                conn.close()

            second = PurposeScheduler(db, "fish-1").reconcile_due(
                NOW + timedelta(minutes=2)
            )
            self.assertEqual(second[0].reason, "RESCHEDULE_LIMIT_REACHED")
            self.assertEqual(
                second[0].new_state,
                PurposeState.NEEDS_RECONCILIATION,
            )

    def test_full_execution_e2e_reaches_terminal_purpose_and_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            due = NOW - timedelta(seconds=1)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purposes
                       SET state='SCHEDULED',scheduled_wall_time=?,
                           timezone='UTC',resolved_utc_time=?
                       WHERE purpose_id='purpose-1'""",
                    (
                        due.isoformat(timespec="microseconds"),
                        due.isoformat(timespec="microseconds"),
                    ),
                )
                scheduled = PurposeRepository().get(conn, "purpose-1")
                occurrence_id = PurposeRepository().activate_occurrence(
                    conn,
                    scheduled,
                    NOW,
                )

            DeliveryLedger(db).create(
                delivery_id="delivery-1",
                identity_id="fish-1",
                logical_notification_id="notice-1",
                purpose_id="purpose-1",
                preferred_surface="qq",
                created_at=NOW,
            )
            eff = replace(
                effect(),
                purpose_occurrence_id=occurrence_id,
            )
            DeliveryCoordinator(db).enqueue_attempt(
                attempt_id="attempt-1",
                delivery_id="delivery-1",
                logical_notification_id="notice-1",
                decision_id="auth-1",
                outbox_id="outbox-1",
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
                effect=eff,
                surface="qq",
                created_at=NOW,
            )

            calls = []
            self.assertEqual(
                OutboxDispatcher(
                    db,
                    {
                        "qq": lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(
                                DispatchStatus.SUCCEEDED,
                                external_ref="msg-1",
                                result={"ok": True},
                            )
                        )
                    },
                ).dispatch_once(now=NOW + timedelta(seconds=1)),
                1,
            )
            self.assertEqual(calls, [eff.request])

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM purposes WHERE purpose_id='purpose-1'"
                    ).fetchone()[0],
                    "COMPLETED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM purpose_occurrences"
                    ).fetchone()[0],
                    "COMPLETED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "SUCCEEDED",
                )
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "SENT",
                )
                self.assertEqual(
                    conn.execute("SELECT state FROM deliveries").fetchone()[0],
                    "DELIVERED",
                )
                receipt = conn.execute(
                    "SELECT request_digest FROM action_receipts"
                ).fetchone()[0]
                expected = "sha256:" + hashlib.sha256(
                    canonical_json(eff.request).encode("utf-8")
                ).hexdigest()
                self.assertEqual(receipt, expected)
            finally:
                conn.close()

    def test_receipt_digest_uses_transport_boundary_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            original = effect().request
            expected = "sha256:" + hashlib.sha256(
                canonical_json(original).encode("utf-8")
            ).hexdigest()

            def mutating_transport(payload, idem):
                payload["recipient"] = "mutated-after-call"
                payload["text"] = "mutated"
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="msg-mutating",
                )

            self.assertEqual(
                OutboxDispatcher(
                    db, {"qq": mutating_transport}
                ).dispatch_once(now=NOW),
                1,
            )
            conn = db.connect()
            try:
                receipt = conn.execute(
                    "SELECT request_digest FROM action_receipts"
                ).fetchone()[0]
                persisted = conn.execute(
                    "SELECT payload_json FROM outbox"
                ).fetchone()[0]
                self.assertEqual(receipt, expected)
                self.assertEqual(persisted, canonical_json(original))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
