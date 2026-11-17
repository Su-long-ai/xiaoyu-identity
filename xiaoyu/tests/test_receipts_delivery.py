from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xiaoyu.contracts import (
    ActionRequest, ActorContext, AuthorizationContext, AuthorizationDecision,
    Delegation, EffectIntent, PrincipalContext, ResourceRef, RiskTier,
)
from xiaoyu.core.authorization import AuthorizationResult
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus
from xiaoyu.persistence import Database, apply_migrations, applied_versions
from xiaoyu.runtime import DeliveryCoordinator, DeliveryLedger, OutboxDispatcher

NOW = datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc)


def principal():
    return PrincipalContext(
        "owner", "OWNER_AUTHENTICATED", 1.0, ("LOCAL_OS_SESSION",),
        ("owner",), "desktop", NOW + timedelta(hours=1)
    )


def actor():
    return ActorContext(
        "tool:notify", "tool", "sha256:tool", "notification", "laptop", "first_party"
    )


def delegation():
    return Delegation(
        "del-r7", "owner", "tool:notify", "purpose-r7",
        ("notification.deliver",), ("notification:owner",), {"messages": 1},
        NOW - timedelta(minutes=1), NOW + timedelta(minutes=10), True,
    )


def action(idem="notice-r7:desktop"):
    return ActionRequest(
        "notification.deliver", RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        {"messages": 1}, True, idem
    )


def effect(surface="desktop", idem="notice-r7:desktop"):
    return EffectIntent(
        "effect-r7-" + surface,
        "intent-r7-" + surface,
        "purpose-r7",
        "tool:notify",
        "notification.deliver",
        {
            "logical_notification_id": "notice-r7",
            "surface": surface,
            "text": "finished",
        },
        idem,
        True,
        NOW,
    )


class ReceiptDeliveryTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _create_delivery(self, db):
        return DeliveryLedger(db).create(
            delivery_id="delivery-r7",
            identity_id="fish-1",
            logical_notification_id="notice-r7",
            purpose_id="purpose-r7",
            preferred_surface="desktop",
            created_at=NOW,
        )

    def _enqueue(self, db, surface="desktop"):
        idem = "notice-r7:" + surface
        DeliveryCoordinator(db).enqueue_attempt(
            attempt_id="attempt-r7-" + surface,
            delivery_id="delivery-r7",
            logical_notification_id="notice-r7",
            decision_id="auth-r7-" + surface,
            outbox_id="outbox-r7-" + surface,
            identity_id="fish-1",
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=action(idem),
            resource=ResourceRef(
                "notification", "owner", {"private": True}
            ),
            context=AuthorizationContext(
                "PERSONAL", "PRIVATE", "desktop", {}
            ),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                "del-r7",
            ),
            effect=effect(surface, idem),
            surface=surface,
            created_at=NOW,
        )

    def test_v4_migration_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertEqual(applied_versions(db), [1, 2, 3, 4, 5])

    def test_logical_delivery_create_is_unique(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertTrue(self._create_delivery(db))
            self.assertFalse(
                DeliveryLedger(db).create(
                    delivery_id="delivery-duplicate",
                    identity_id="fish-1",
                    logical_notification_id="notice-r7",
                    purpose_id="purpose-r7",
                    preferred_surface="qq",
                    created_at=NOW,
                )
            )

    def test_success_dispatch_persists_receipt_and_delivery_outcome(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._create_delivery(db)
            self._enqueue(db, "desktop")

            def transport(payload, idem):
                self.assertEqual(payload["surface"], "desktop")
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="desktop-msg-77",
                    result={"ok": True, "message_id": 77},
                )

            self.assertEqual(
                OutboxDispatcher(
                    db, {"desktop": transport}
                ).dispatch_once(now=NOW),
                1,
            )
            conn = db.connect()
            try:
                effect_row = conn.execute(
                    """SELECT receipt_id,dispatch_state
                       FROM effects WHERE effect_id='effect-r7-desktop'"""
                ).fetchone()
                self.assertEqual(effect_row["dispatch_state"], "SUCCEEDED")
                receipt = conn.execute(
                    "SELECT * FROM action_receipts WHERE receipt_id=?",
                    (effect_row["receipt_id"],),
                ).fetchone()
                self.assertEqual(
                    receipt["authorization_decision_id"],
                    "auth-r7-desktop",
                )
                self.assertEqual(
                    receipt["external_ref"],
                    "desktop-msg-77",
                )
                body = json.loads(receipt["receipt_json"])
                self.assertEqual(body["metadata"]["attempt_count"], 1)

                delivery = conn.execute(
                    """SELECT state,surface,attempt_count,external_ref
                       FROM deliveries
                       WHERE logical_notification_id='notice-r7'"""
                ).fetchone()
                self.assertEqual(
                    tuple(delivery),
                    ("DELIVERED", "desktop", 1, "desktop-msg-77"),
                )
                attempt = conn.execute(
                    """SELECT state,external_ref FROM delivery_attempts
                       WHERE effect_id='effect-r7-desktop'"""
                ).fetchone()
                self.assertEqual(
                    tuple(attempt),
                    ("DELIVERED", "desktop-msg-77"),
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
