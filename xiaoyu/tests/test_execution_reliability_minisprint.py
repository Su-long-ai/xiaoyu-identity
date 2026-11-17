from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    AuthorizationDecision,
    CapabilityDescriptor,
    Delegation,
    EffectIntent,
    IsolationMode,
    PrincipalContext,
    ProviderHealth,
    ProviderLifecycle,
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
from xiaoyu.persistence.repositories.execution_auth import (
    DelegationRepository,
    PrincipalExecutionRepository,
)
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.persistence.repositories.provider_execution import ProviderExecutionRegistry
from xiaoyu.runtime import (
    DeliveryCoordinator,
    DeliveryLedger,
    OutboxDispatcher,
    PurposeScheduler,
)
from xiaoyu.runtime.outbox import TransportBinding
from xiaoyu.runtime.recovery import (
    ExecutionReconciler,
    ExecutionRecoveryQueue,
)
from xiaoyu.runtime.execution_resources import ExecutionResourceBroker


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


    def _register_provider(self, db):
        registry = ProviderExecutionRegistry(db)
        registry.register(
            CapabilityDescriptor(
                provider_id="napcat",
                capability="message.send",
                implementation_version="1.0",
                contract_name="message.send",
                contract_min_version="1",
                contract_max_exclusive="2",
                artifact_digest="sha256:provider-v1",
                descriptor_digest="sha256:descriptor-v1",
                interface_digest="sha256:interface-v1",
                tool_schema_digest="sha256:schema-v1",
                isolation=IsolationMode.SIDECAR,
                features={},
                data_classes=("message",),
                permissions_required=("message.send",),
                fallback_group=None,
                lifecycle=ProviderLifecycle.ACTIVE,
                resource_profile={},
            ),
            ProviderHealth(
                liveness="UP",
                readiness="READY",
                capability_health={"message.send": "READY"},
                reason=None,
                since=NOW,
                retry_after_ms=None,
                details={},
            ),
            NOW,
        )
        return registry

    @staticmethod
    def _bound_transport(send, **overrides):
        values = {
            "actor_id": "tool:qq",
            "provider_id": "napcat",
            "actor_implementation_digest": "sha256:tool-v1",
            "actor_authorization_digest": "sha256:auth-v1",
            "artifact_digest": "sha256:provider-v1",
            "interface_digest": "sha256:interface-v1",
            "tool_schema_digest": "sha256:schema-v1",
            "capability": "message.send",
        }
        values.update(overrides)
        return TransportBinding(send=send, **values)

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

        for bad_parameters in (
            {},
            {"messages": True},
            {"messages": "1000"},
            {"messages": float("nan")},
            {"messages": float("inf")},
        ):
            with self.subTest(parameters=bad_parameters):
                result = policy.evaluate(
                    principal(),
                    actor(),
                    delegation(),
                    action(parameters=bad_parameters),
                    resource(),
                    context(),
                    NOW,
                )
                self.assertEqual(
                    result.decision,
                    AuthorizationDecision.DENY,
                )

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
                    "qq": self._bound_transport(
                        lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(DispatchStatus.SUCCEEDED)
                        )
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

    def test_manual_reschedule_starts_fresh_auto_reschedule_budget(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            due = NOW - timedelta(minutes=1)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purposes
                       SET state='SCHEDULED',
                           scheduled_wall_time=?,
                           timezone='UTC',
                           resolved_utc_time=?,
                           auto_reschedule_count=1
                       WHERE purpose_id='purpose-1'""",
                    (
                        due.isoformat(timespec="microseconds"),
                        due.isoformat(timespec="microseconds"),
                    ),
                )
                self.assertTrue(
                    PurposeRepository().reschedule(
                        conn,
                        "purpose-1",
                        (NOW + timedelta(hours=1)).isoformat(
                            timespec="minutes"
                        ),
                        "UTC",
                        NOW + timedelta(hours=1),
                        NOW,
                    )
                )
            conn = db.connect()
            try:
                row = conn.execute(
                    """SELECT revision,auto_reschedule_count,state
                       FROM purposes WHERE purpose_id='purpose-1'"""
                ).fetchone()
                self.assertEqual(tuple(row), (2, 0, "SCHEDULED"))
            finally:
                conn.close()

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
                    """SELECT request_digest,provider_id,receipt_json
                       FROM action_receipts"""
                ).fetchone()
                expected = "sha256:" + hashlib.sha256(
                    canonical_json(eff.request).encode("utf-8")
                ).hexdigest()
                self.assertEqual(receipt["request_digest"], expected)
                self.assertEqual(receipt["provider_id"], "napcat")
                auth_digest = conn.execute(
                    """SELECT authorized_request_digest
                       FROM execution_authorizations"""
                ).fetchone()[0]
                receipt_body = json.loads(receipt["receipt_json"])
                self.assertEqual(
                    receipt_body["metadata"]["authorized_request_digest"],
                    auth_digest,
                )
            finally:
                conn.close()

    def test_post_preflight_payload_mutation_cannot_change_transport_request(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            sent = []

            def fault(stage, row):
                if stage == "before_dispatch":
                    row.payload["recipient"] = "outsider"
                    row.payload["text"] = "tampered"

            def transport(payload, idem):
                sent.append(dict(payload))
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="msg-frozen",
                )

            self.assertEqual(
                OutboxDispatcher(
                    db,
                    {"qq": transport},
                    fault_hook=fault,
                ).dispatch_once(now=NOW),
                1,
            )
            self.assertEqual(
                sent,
                [{"recipient": "owner", "text": "hello"}],
            )
            conn = db.connect()
            try:
                receipt = conn.execute(
                    "SELECT request_digest FROM action_receipts"
                ).fetchone()[0]
                expected = "sha256:" + hashlib.sha256(
                    canonical_json(
                        {"recipient": "owner", "text": "hello"}
                    ).encode("utf-8")
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

    def test_principal_revocation_after_enqueue_blocks_transport(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            with db.transaction(immediate=True) as conn:
                self.assertTrue(
                    PrincipalExecutionRepository().revoke(
                        conn,
                        identity_id="fish-1",
                        principal_id="owner",
                        session_scope="desktop",
                        revoked_at=NOW + timedelta(seconds=1),
                    )
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

    def test_principal_viewer_change_invalidates_old_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            changed = PrincipalContext(
                principal_id="owner",
                authentication_level="OWNER_AUTHENTICATED",
                confidence=1.0,
                evidence_classes=("LOCAL_OS_SESSION",),
                viewer_set=("owner", "guest"),
                session_scope="desktop",
                expires_at=NOW + timedelta(hours=1),
            )
            with db.transaction(immediate=True) as conn:
                PrincipalExecutionRepository().register(
                    conn,
                    "fish-1",
                    changed,
                    NOW + timedelta(seconds=1),
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

    def test_provider_health_change_blocks_queued_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            registry = self._register_provider(db)
            self._enqueue(db)
            registry.update_health(
                "napcat",
                ProviderHealth(
                    liveness="UP",
                    readiness="NOT_READY",
                    capability_health={"message.send": "NOT_READY"},
                    reason="maintenance",
                    since=NOW + timedelta(seconds=1),
                    retry_after_ms=1000,
                    details={},
                ),
                NOW + timedelta(seconds=1),
            )
            calls = []
            processed = OutboxDispatcher(
                db,
                {
                    "qq": self._bound_transport(
                        lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(DispatchStatus.SUCCEEDED)
                        )
                    )
                },
            ).dispatch_once(now=NOW + timedelta(seconds=2))
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_provider_lifecycle_change_blocks_standing_approval(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            registry = self._register_provider(db)
            self._enqueue(db)
            self.assertTrue(
                registry.set_lifecycle(
                    "napcat",
                    ProviderLifecycle.DISABLED,
                    NOW + timedelta(seconds=1),
                )
            )
            calls = []
            processed = OutboxDispatcher(
                db,
                {
                    "qq": self._bound_transport(
                        lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(DispatchStatus.SUCCEEDED)
                        )
                    )
                },
            ).dispatch_once(now=NOW + timedelta(seconds=2))
            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_versioned_provider_requires_bound_transport(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._register_provider(db)
            self._enqueue(db)
            calls = []

            processed = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: (
                        calls.append(payload)
                        or DispatchOutcome(DispatchStatus.SUCCEEDED)
                    )
                },
            ).dispatch_once(now=NOW)

            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "FAILED_FINAL",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "FAILED",
                )
            finally:
                conn.close()

    def test_transport_actor_swap_is_blocked_even_with_same_digests(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._register_provider(db)
            self._enqueue(db)
            calls = []

            processed = OutboxDispatcher(
                db,
                {
                    "qq": self._bound_transport(
                        lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(DispatchStatus.SUCCEEDED)
                        ),
                        actor_id="tool:other",
                    )
                },
            ).dispatch_once(now=NOW)

            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_transport_implementation_digest_change_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._register_provider(db)
            self._enqueue(db)
            calls = []

            processed = OutboxDispatcher(
                db,
                {
                    "qq": self._bound_transport(
                        lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(DispatchStatus.SUCCEEDED)
                        ),
                        actor_implementation_digest="sha256:tool-v2",
                    )
                },
            ).dispatch_once(now=NOW)

            self.assertEqual(processed, 0)
            self.assertEqual(calls, [])

    def test_exact_transport_binding_can_dispatch_versioned_provider(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._register_provider(db)
            self._enqueue(db)
            calls = []

            processed = OutboxDispatcher(
                db,
                {
                    "qq": self._bound_transport(
                        lambda payload, idem: (
                            calls.append(payload)
                            or DispatchOutcome(
                                DispatchStatus.SUCCEEDED,
                                external_ref="msg-versioned",
                            )
                        )
                    )
                },
            ).dispatch_once(now=NOW)

            self.assertEqual(processed, 1)
            self.assertEqual(len(calls), 1)
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "SUCCEEDED",
                )
            finally:
                conn.close()

    def test_reconciliation_success_requires_evidence_and_closes_occurrence(self):
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

            self._enqueue(
                db,
                eff=replace(
                    effect(),
                    purpose_occurrence_id=occurrence_id,
                ),
            )

            def unknown(payload, idem):
                raise TimeoutError("provider ack lost")

            OutboxDispatcher(db, {"qq": unknown}).dispatch_once(now=NOW)

            reconciler = ExecutionReconciler(db)
            with self.assertRaises(ValueError):
                reconciler.reconcile_effect(
                    effect_id="effect-1",
                    outcome="SUCCEEDED",
                    evidence={},
                    observed_at=NOW + timedelta(seconds=2),
                )

            receipt = reconciler.reconcile_effect(
                effect_id="effect-1",
                outcome="SUCCEEDED",
                evidence={
                    "provider_query_id": "query-1",
                    "provider_status": "DELIVERED",
                },
                external_ref="msg-confirmed",
                observed_at=NOW + timedelta(seconds=3),
            )
            self.assertEqual(
                receipt.result_class,
                "RECONCILED_SUCCEEDED",
            )
            conn = db.connect()
            try:
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
                    conn.execute(
                        "SELECT state FROM purpose_occurrences"
                    ).fetchone()[0],
                    "COMPLETED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM purposes"
                    ).fetchone()[0],
                    "COMPLETED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM action_receipts"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_reconciliation_confirmed_failure_returns_purpose_to_waiting(self):
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

            self._enqueue(
                db,
                eff=replace(
                    effect(),
                    purpose_occurrence_id=occurrence_id,
                ),
            )

            def unknown(payload, idem):
                raise TimeoutError("provider ack lost")

            OutboxDispatcher(db, {"qq": unknown}).dispatch_once(now=NOW)
            receipt = ExecutionReconciler(db).reconcile_effect(
                effect_id="effect-1",
                outcome="FAILED",
                evidence={
                    "provider_query_id": "query-2",
                    "provider_status": "NOT_FOUND",
                },
                observed_at=NOW + timedelta(seconds=3),
            )
            self.assertEqual(
                receipt.result_class,
                "RECONCILED_FAILED",
            )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "FAILED",
                )
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "FAILED_FINAL",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM purpose_occurrences"
                    ).fetchone()[0],
                    "FAILED_FINAL",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM purposes"
                    ).fetchone()[0],
                    "WAITING",
                )
            finally:
                conn.close()

    def test_dispatch_terminal_path_releases_registered_resource(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            broker = ExecutionResourceBroker()
            calls = []
            broker.acquire(
                lease_id="lease-effect-1",
                effect_id="effect-1",
                resource_id="socket:qq",
                release=lambda: calls.append("release"),
            )

            processed = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: DispatchOutcome(
                        DispatchStatus.SUCCEEDED,
                        external_ref="msg-resource",
                    )
                },
                resource_broker=broker,
            ).dispatch_once(now=NOW)

            self.assertEqual(processed, 1)
            self.assertEqual(calls, ["release"])
            self.assertEqual(
                broker.list_effect("effect-1")[0].state,
                "RELEASED",
            )

    def test_cancel_before_transport_cancels_and_releases_resource(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            broker = ExecutionResourceBroker()
            resource_calls = []
            transport_calls = []
            broker.acquire(
                lease_id="lease-effect-1",
                effect_id="effect-1",
                resource_id="provider-session:qq",
                cancel=lambda: resource_calls.append("cancel"),
                release=lambda: resource_calls.append("release"),
            )

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
                        transport_calls.append(payload)
                        or DispatchOutcome(DispatchStatus.SUCCEEDED)
                    )
                },
                fault_hook=fault,
                resource_broker=broker,
            ).dispatch_once(now=NOW + timedelta(seconds=2))

            self.assertEqual(processed, 0)
            self.assertEqual(transport_calls, [])
            self.assertEqual(resource_calls, ["cancel", "release"])
            self.assertEqual(
                broker.list_effect("effect-1")[0].state,
                "RELEASED",
            )

    def test_retryable_effect_reaches_failed_after_retry_budget(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            calls = []

            def retryable(payload, idem):
                calls.append(payload)
                return DispatchOutcome(
                    DispatchStatus.FAILED_RETRYABLE,
                    retry_after_s=0,
                )

            dispatcher = OutboxDispatcher(
                db,
                {"qq": retryable},
                max_attempts=2,
            )
            self.assertEqual(dispatcher.dispatch_once(now=NOW), 1)
            self.assertEqual(
                dispatcher.dispatch_once(
                    now=NOW + timedelta(seconds=2)
                ),
                1,
            )
            self.assertEqual(len(calls), 2)

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "FAILED_FINAL",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "FAILED",
                )
            finally:
                conn.close()

    def test_receipt_commit_failure_recovers_to_reconciliation(self):
        class BrokenReceiptRepository:
            def insert(self, conn, identity_id, receipt):
                raise RuntimeError("synthetic receipt commit failure")

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)

            dispatcher = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: DispatchOutcome(
                        DispatchStatus.SUCCEEDED,
                        external_ref="msg-receipt-failure",
                    )
                },
                receipt_repo=BrokenReceiptRepository(),
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic receipt commit failure",
            ):
                dispatcher.dispatch_once(now=NOW)

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "CLAIMED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "DISPATCHING",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM action_receipts"
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

            recovered = OutboxDispatcher(db, {"qq": lambda p, i: None})
            self.assertEqual(
                recovered.recover_inflight(
                    NOW + timedelta(seconds=1)
                ),
                1,
            )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute("SELECT state FROM outbox").fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
            finally:
                conn.close()

    def test_receipt_commit_crash_reconciles_stranded_delivery_attempt(self):
        class BrokenReceiptRepository:
            def insert(self, conn, identity_id, receipt):
                raise RuntimeError("synthetic receipt commit failure")

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            DeliveryLedger(db).create(
                delivery_id="delivery-crash",
                identity_id="fish-1",
                logical_notification_id="notice-crash",
                purpose_id="purpose-1",
                preferred_surface="qq",
                created_at=NOW,
            )
            DeliveryCoordinator(db).enqueue_attempt(
                attempt_id="attempt-crash",
                delivery_id="delivery-crash",
                logical_notification_id="notice-crash",
                decision_id="auth-crash",
                outbox_id="outbox-crash",
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
                effect=replace(
                    effect(),
                    effect_id="effect-crash",
                ),
                surface="qq",
                created_at=NOW,
            )

            dispatcher = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: DispatchOutcome(
                        DispatchStatus.SUCCEEDED,
                        external_ref="msg-crash",
                    )
                },
                receipt_repo=BrokenReceiptRepository(),
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic receipt commit failure",
            ):
                dispatcher.dispatch_once(now=NOW)

            recovery = ExecutionRecoveryQueue(db)
            self.assertEqual(
                recovery.recover_restart(
                    NOW + timedelta(seconds=1)
                )["claimed_recovered"],
                1,
            )
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        """SELECT state FROM delivery_attempts
                           WHERE attempt_id='attempt-crash'"""
                    ).fetchone()[0],
                    "UNKNOWN",
                )
                self.assertEqual(
                    conn.execute(
                        """SELECT state FROM deliveries
                           WHERE delivery_id='delivery-crash'"""
                    ).fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
                self.assertEqual(
                    conn.execute(
                        """SELECT dispatch_state FROM effects
                           WHERE effect_id='effect-crash'"""
                    ).fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
            finally:
                conn.close()

    def test_duplicate_dispatchers_cross_transport_boundary_once(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            calls = []

            def transport(payload, idem):
                calls.append((payload, idem))
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="msg-once",
                )

            def run(_):
                return OutboxDispatcher(
                    db, {"qq": transport}
                ).dispatch_once(now=NOW)

            with ThreadPoolExecutor(max_workers=2) as pool:
                processed = list(pool.map(run, (1, 2)))

            self.assertEqual(sum(processed), 1)
            self.assertEqual(len(calls), 1)

    def test_cancel_while_transport_in_flight_never_claims_cancelled(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            cancel_results = []

            def fault(stage, row):
                if stage == "before_dispatch":
                    with db.transaction(immediate=True) as conn:
                        cancel_results.append(
                            PurposeRepository().cancel(
                                conn,
                                "purpose-1",
                                NOW + timedelta(seconds=1),
                            )
                        )

            dispatcher = OutboxDispatcher(
                db,
                {
                    "qq": lambda payload, idem: DispatchOutcome(
                        DispatchStatus.SUCCEEDED,
                        external_ref="msg-raced",
                    )
                },
                fault_hook=fault,
            )
            self.assertEqual(
                dispatcher.dispatch_once(
                    now=NOW + timedelta(seconds=2)
                ),
                1,
            )
            self.assertEqual(cancel_results, [False])
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM purposes"
                    ).fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT dispatch_state FROM effects"
                    ).fetchone()[0],
                    "SUCCEEDED",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM action_receipts"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_restart_rebuilds_active_scheduled_purpose_missing_work(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            due = NOW - timedelta(seconds=10)
            with db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE purposes
                       SET resolved_utc_time=?,scheduled_wall_time=?,
                           timezone='UTC'
                       WHERE purpose_id='purpose-1'""",
                    (
                        due.isoformat(timespec="microseconds"),
                        due.isoformat(timespec="microseconds"),
                    ),
                )
            report = ExecutionRecoveryQueue(db).recover_restart(NOW)
            self.assertEqual(report["active_work_rebuilt"], 1)
            conn = db.connect()
            try:
                row = conn.execute(
                    """SELECT state,purpose_revision
                       FROM purpose_occurrences"""
                ).fetchone()
                self.assertEqual(tuple(row), ("READY", 1))
            finally:
                conn.close()

    def test_reconciliation_queue_makes_unknown_effect_visible(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)

            def transport(payload, idem):
                raise TimeoutError("unknown result")

            OutboxDispatcher(
                db, {"qq": transport}
            ).dispatch_once(now=NOW)
            items = ExecutionRecoveryQueue(db).list_open("fish-1")
            self.assertTrue(
                any(
                    item.kind == "effect"
                    and item.state == "NEEDS_RECONCILIATION"
                    for item in items
                )
            )
            self.assertTrue(
                any(
                    item.kind == "purpose"
                    and item.state == "NEEDS_RECONCILIATION"
                    for item in items
                )
            )

    def test_authorization_decision_audit_contains_exact_action(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db)
            conn = db.connect()
            try:
                body = json.loads(
                    conn.execute(
                        """SELECT resource_json
                           FROM authorization_decisions"""
                    ).fetchone()[0]
                )
                self.assertEqual(
                    body["action"],
                    action().to_dict(),
                )
                self.assertEqual(
                    body["resource"],
                    resource().to_dict(),
                )
            finally:
                conn.close()

    def test_effect_request_rejects_missing_unknown_and_wrong_types(self):
        with tempfile.TemporaryDirectory() as td:
            for bad_request in (
                {"recipient": "owner"},
                {"text": "hello"},
                {
                    "recipient": "owner",
                    "text": "hello",
                    "surprise": "x",
                },
                {"recipient": "owner", "text": 123},
            ):
                with self.subTest(request=bad_request):
                    db = self._db(td)
                    self._insert_purpose(db)
                    with self.assertRaises(EffectBindingError):
                        self._enqueue(
                            db,
                            eff=effect(bad_request),
                        )
                    # subtests share td; clean the DB for the next case
                    Path(td, "identity.sqlite3").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
