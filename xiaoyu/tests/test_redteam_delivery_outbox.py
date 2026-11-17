from __future__ import annotations

import tempfile
from dataclasses import replace
import unittest
from concurrent.futures import ThreadPoolExecutor
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
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus
from xiaoyu.core.purpose import (
    MissPolicy,
    Purpose,
    PurposeKind,
    PurposeOwner,
    PurposeState,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.purposes import PurposeRepository
from xiaoyu.runtime import (
    DeliveryAttemptAlreadyActive,
    DeliveryCoordinator,
    DeliveryLedger,
    OutboxDispatcher,
)


NOW = datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)


def principal():
    return PrincipalContext(
        "owner",
        "OWNER_AUTHENTICATED",
        1.0,
        ("LOCAL_OS_SESSION",),
        ("owner",),
        "desktop",
        NOW + timedelta(hours=1),
    )


def actor():
    return ActorContext(
        "tool:notify",
        "tool",
        "sha256:notify-v1",
        "notification",
        "laptop",
        "first_party",
    )


def delegation():
    return Delegation(
        "del-notify",
        "owner",
        "tool:notify",
        "purpose-1",
        ("notification.deliver",),
        ("notification:owner",),
        {"messages": 1},
        NOW - timedelta(minutes=1),
        NOW + timedelta(minutes=10),
        True,
    )


def action(idem):
    return ActionRequest(
        "notification.deliver",
        RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        {"messages": 1},
        True,
        idem,
    )


def effect(surface, suffix):
    idem = "notice-1:" + suffix
    return EffectIntent(
        "effect-" + suffix,
        "intent-" + suffix,
        "purpose-1",
        "tool:notify",
        "notification.deliver",
        {
            "logical_notification_id": "notice-1",
            "surface": surface,
            "recipient": "owner",
            "text": "done",
        },
        idem,
        True,
        NOW,
    )


class DeliveryOutboxRedTeamTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        DeliveryLedger(db).create(
            delivery_id="delivery-1",
            identity_id="fish-1",
            logical_notification_id="notice-1",
            purpose_id="purpose-1",
            preferred_surface="desktop",
            created_at=NOW,
        )
        return db

    def _enqueue(self, db, surface, suffix):
        eff = effect(surface, suffix)
        conn = db.connect()
        try:
            purpose_row = conn.execute(
                "SELECT revision FROM purposes WHERE purpose_id=?",
                (eff.purpose_id,),
            ).fetchone()
        finally:
            conn.close()
        if purpose_row is not None:
            eff = replace(
                eff,
                purpose_revision=int(purpose_row["revision"]),
            )
        DeliveryCoordinator(db).enqueue_attempt(
            attempt_id="attempt-" + suffix,
            delivery_id="delivery-1",
            logical_notification_id="notice-1",
            decision_id="auth-" + suffix,
            outbox_id="outbox-" + suffix,
            identity_id="fish-1",
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=action(eff.idempotency_key),
            resource=ResourceRef(
                "notification",
                "owner",
                {"private": True},
            ),
            context=AuthorizationContext(
                "PERSONAL",
                "PRIVATE",
                "desktop",
                {},
            ),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                "del-notify",
            ),
            effect=eff,
            surface=surface,
            created_at=NOW,
        )

    def _insert_purpose(self, db):
        with db.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO canonical_events(
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
                ),
                NOW,
            )

    def test_two_workers_can_reserve_only_one_active_carrier_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)

            def queue(item):
                surface, suffix = item
                try:
                    self._enqueue(db, surface, suffix)
                    return "queued"
                except DeliveryAttemptAlreadyActive:
                    return "blocked"

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        queue,
                        (("desktop", "a"), ("qq", "b")),
                    )
                )

            self.assertEqual(sorted(results), ["blocked", "queued"])
            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM delivery_attempts"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM effects"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM outbox"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_ack_loss_becomes_reconciliation_and_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db, "desktop", "desktop")
            calls = []

            def desktop(payload, idem):
                calls.append("desktop delivered")
                raise TimeoutError("ack lost after delivery")

            OutboxDispatcher(
                db,
                {"desktop": desktop},
            ).dispatch_once(now=NOW)
            self.assertEqual(calls, ["desktop delivered"])

            with self.assertRaises(DeliveryAttemptAlreadyActive):
                self._enqueue(db, "qq", "qq")

            conn = db.connect()
            try:
                delivery = conn.execute(
                    """SELECT state FROM deliveries
                       WHERE logical_notification_id='notice-1'"""
                ).fetchone()[0]
                attempt = conn.execute(
                    """SELECT state FROM delivery_attempts
                       WHERE effect_id='effect-desktop'"""
                ).fetchone()[0]
                self.assertEqual(delivery, "NEEDS_RECONCILIATION")
                self.assertEqual(attempt, "UNKNOWN")
            finally:
                conn.close()

    def test_crash_after_send_recovers_to_unknown_and_blocks_fallback(self):
        class SimulatedCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db, "desktop", "desktop")
            calls = []

            def desktop(payload, idem):
                calls.append("desktop delivered")
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="desktop-1",
                )

            def crash(stage, row):
                if stage == "after_dispatch":
                    raise SimulatedCrash()

            dispatcher = OutboxDispatcher(
                db,
                {"desktop": desktop},
                fault_hook=crash,
            )
            with self.assertRaises(SimulatedCrash):
                dispatcher.dispatch_once(now=NOW)
            self.assertEqual(calls, ["desktop delivered"])

            recovered = OutboxDispatcher(db, {"desktop": desktop})
            self.assertEqual(
                recovered.recover_inflight(
                    now=NOW + timedelta(seconds=1)
                ),
                1,
            )
            with self.assertRaises(DeliveryAttemptAlreadyActive):
                self._enqueue(db, "qq", "qq")

            conn = db.connect()
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM deliveries"
                    ).fetchone()[0],
                    "NEEDS_RECONCILIATION",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM delivery_attempts"
                    ).fetchone()[0],
                    "UNKNOWN",
                )
            finally:
                conn.close()

    def test_cancelled_purpose_is_blocked_before_transport(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._insert_purpose(db)
            self._enqueue(db, "desktop", "desktop")
            with db.transaction() as conn:
                self.assertTrue(
                    PurposeRepository().cancel(
                        conn,
                        "purpose-1",
                        NOW + timedelta(seconds=1),
                    )
                )

            calls = []

            def desktop(payload, idem):
                calls.append("sent")
                return DispatchOutcome(DispatchStatus.SUCCEEDED)

            self.assertEqual(
                OutboxDispatcher(
                    db, {"desktop": desktop}
                ).dispatch_once(
                    now=NOW + timedelta(seconds=2)
                ),
                0,
            )
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
                self.assertEqual(
                    conn.execute(
                        "SELECT state FROM deliveries"
                    ).fetchone()[0],
                    "CANCELLED",
                )
            finally:
                conn.close()

    def test_definite_failure_allows_one_later_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db, "desktop", "desktop")
            calls = []

            def desktop(payload, idem):
                calls.append("desktop")
                return DispatchOutcome(
                    DispatchStatus.FAILED_FINAL,
                    result={"not_sent": True},
                )

            OutboxDispatcher(
                db,
                {"desktop": desktop},
            ).dispatch_once(now=NOW)
            self._enqueue(db, "qq", "qq")

            def qq(payload, idem):
                calls.append("qq")
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="qq-1",
                )

            OutboxDispatcher(
                db,
                {"qq": qq},
            ).dispatch_once(
                now=NOW + timedelta(seconds=1)
            )
            self.assertEqual(calls, ["desktop", "qq"])
            conn = db.connect()
            try:
                delivery = conn.execute(
                    """SELECT state,attempt_count,external_ref
                       FROM deliveries"""
                ).fetchone()
                self.assertEqual(
                    tuple(delivery),
                    ("DELIVERED", 2, "qq-1"),
                )
                states = [
                    row[0]
                    for row in conn.execute(
                        """SELECT state FROM delivery_attempts
                           ORDER BY created_at,attempt_id"""
                    ).fetchall()
                ]
                self.assertEqual(
                    sorted(states),
                    ["DELIVERED", "FAILED_FINAL"],
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
