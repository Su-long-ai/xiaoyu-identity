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
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus, EffectCoordinator
from xiaoyu.persistence import Database, apply_migrations, applied_versions
from xiaoyu.runtime import DeliveryLedger, OutboxDispatcher

NOW = datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc)


def principal():
    return PrincipalContext(
        "owner", "OWNER_AUTHENTICATED", 1.0, ("LOCAL_OS_SESSION",),
        ("owner",), "desktop", NOW + timedelta(hours=1)
    )


def actor():
    return ActorContext(
        "tool:qq", "tool", "sha256:tool", "napcat", "laptop", "first_party"
    )


def delegation():
    return Delegation(
        "del-r7", "owner", "tool:qq", "purpose-r7",
        ("message.send",), ("qq:owner",), {"messages": 1},
        NOW - timedelta(minutes=1), NOW + timedelta(minutes=10), True,
    )


def action():
    return ActionRequest(
        "message.send", RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE,
        {"messages": 1}, True, "idem-r7"
    )


def effect():
    return EffectIntent(
        "effect-r7", "intent-r7", "purpose-r7", "tool:qq",
        "message.send", {"text": "finished"}, "idem-r7", True, NOW
    )


class ReceiptDeliveryTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def _enqueue(self, db):
        EffectCoordinator(db).enqueue_authorized(
            decision_id="auth-r7",
            outbox_id="outbox-r7",
            identity_id="fish-1",
            principal=principal(),
            actor=actor(),
            delegation=delegation(),
            action=action(),
            resource=ResourceRef("qq", "owner", {"private": True}),
            context=AuthorizationContext(
                "PERSONAL", "PRIVATE", "desktop", {}
            ),
            auth_result=AuthorizationResult(
                AuthorizationDecision.ALLOW, "VALID_DELEGATION", "del-r7"
            ),
            effect=effect(),
            destination="qq",
            payload={"text": "finished"},
            created_at=NOW,
        )

    def test_v2_migration_links_effect_to_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self.assertEqual(applied_versions(db), [1, 2, 3])
            self._enqueue(db)
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT authorization_decision_id FROM effects "
                    "WHERE effect_id='effect-r7'"
                ).fetchone()
                self.assertEqual(row[0], "auth-r7")
            finally:
                conn.close()

    def test_success_dispatch_persists_receipt_and_links_effect(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            self._enqueue(db)

            def transport(payload, idem):
                return DispatchOutcome(
                    DispatchStatus.SUCCEEDED,
                    external_ref="qq-msg-77",
                    result={"ok": True, "message_id": 77},
                )

            OutboxDispatcher(db, {"qq": transport}).dispatch_once(now=NOW)
            conn = db.connect()
            try:
                effect_row = conn.execute(
                    "SELECT receipt_id,dispatch_state FROM effects "
                    "WHERE effect_id='effect-r7'"
                ).fetchone()
                self.assertEqual(effect_row["dispatch_state"], "SUCCEEDED")
                receipt = conn.execute(
                    "SELECT * FROM action_receipts WHERE receipt_id=?",
                    (effect_row["receipt_id"],),
                ).fetchone()
                self.assertEqual(receipt["authorization_decision_id"], "auth-r7")
                self.assertEqual(receipt["external_ref"], "qq-msg-77")
                self.assertTrue(receipt["request_digest"].startswith("sha256:"))
                self.assertTrue(receipt["result_digest"].startswith("sha256:"))
                body = json.loads(receipt["receipt_json"])
                self.assertEqual(body["metadata"]["attempt_count"], 1)
            finally:
                conn.close()

    def test_logical_delivery_is_unique_after_success(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            calls = []
            ledger = DeliveryLedger(
                db,
                {
                    "desktop": lambda payload: calls.append("desktop") or "desktop-1",
                    "qq": lambda payload: calls.append("qq") or "qq-1",
                },
            )
            self.assertTrue(ledger.create(
                delivery_id="delivery-1", identity_id="fish-1",
                logical_notification_id="notice-1", purpose_id="purpose-r7",
                preferred_surface="desktop", created_at=NOW,
            ))
            self.assertFalse(ledger.create(
                delivery_id="delivery-duplicate", identity_id="fish-1",
                logical_notification_id="notice-1", purpose_id="purpose-r7",
                preferred_surface="qq", created_at=NOW,
            ))
            self.assertTrue(ledger.attempt(
                identity_id="fish-1", logical_notification_id="notice-1",
                surface="desktop", payload={"text": "done"}, now=NOW,
            ))
            self.assertFalse(ledger.attempt(
                identity_id="fish-1", logical_notification_id="notice-1",
                surface="qq", payload={"text": "done"},
                now=NOW + timedelta(seconds=1),
            ))
            self.assertEqual(calls, ["desktop"])

    def test_failed_desktop_falls_back_to_qq_once(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            calls = []

            def desktop(payload):
                calls.append("desktop")
                raise RuntimeError("desktop unavailable")

            def qq(payload):
                calls.append("qq")
                return "qq-2"

            ledger = DeliveryLedger(db, {"desktop": desktop, "qq": qq})
            ledger.create(
                delivery_id="delivery-2", identity_id="fish-1",
                logical_notification_id="notice-2", purpose_id="purpose-r7",
                preferred_surface="desktop", created_at=NOW,
            )
            self.assertFalse(ledger.attempt(
                identity_id="fish-1", logical_notification_id="notice-2",
                surface="desktop", payload={"text": "done"}, now=NOW,
            ))
            self.assertTrue(ledger.attempt(
                identity_id="fish-1", logical_notification_id="notice-2",
                surface="qq", payload={"text": "done"},
                now=NOW + timedelta(seconds=1),
            ))
            self.assertFalse(ledger.attempt(
                identity_id="fish-1", logical_notification_id="notice-2",
                surface="qq", payload={"text": "again"},
                now=NOW + timedelta(seconds=2),
            ))
            self.assertEqual(calls, ["desktop", "qq"])
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT state,surface,attempt_count,external_ref FROM deliveries "
                    "WHERE logical_notification_id='notice-2'"
                ).fetchone()
                self.assertEqual(tuple(row), ("DELIVERED", "qq", 2, "qq-2"))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
