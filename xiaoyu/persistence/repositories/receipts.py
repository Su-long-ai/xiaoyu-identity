from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from xiaoyu.contracts import ActionReceipt
from xiaoyu.contracts.common import canonical_json, datetime_to_text


class ActionReceiptRepository:
    def insert(self, conn: sqlite3.Connection, identity_id: str, receipt: ActionReceipt) -> None:
        conn.execute(
            """INSERT INTO action_receipts(
                   receipt_id,identity_id,effect_id,actor_id,provider_id,
                   authorization_decision_id,result_class,request_digest,result_digest,
                   external_ref,observed_at,receipt_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                receipt.receipt_id,
                identity_id,
                receipt.effect_id,
                receipt.actor_id,
                receipt.provider_id,
                receipt.authorization_decision_id,
                receipt.result_class,
                receipt.request_digest,
                receipt.result_digest,
                receipt.external_ref,
                datetime_to_text(receipt.observed_at, "observed_at"),
                canonical_json(receipt.to_dict()),
            ),
        )
        cur = conn.execute(
            "UPDATE effects SET receipt_id=? WHERE effect_id=? AND receipt_id IS NULL",
            (receipt.receipt_id, receipt.effect_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                "effect already has receipt or does not exist: %s" % receipt.effect_id
            )


class DeliveryRepository:
    """One durable row per logical notification across carrier attempts."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        delivery_id: str,
        identity_id: str,
        logical_notification_id: str,
        purpose_id: Optional[str],
        surface: str,
        created_at: datetime,
    ) -> bool:
        timestamp = datetime_to_text(created_at, "created_at")
        try:
            conn.execute(
                """INSERT INTO deliveries(
                       delivery_id,identity_id,logical_notification_id,purpose_id,
                       surface,state,attempt_count,external_ref,created_at,updated_at
                   ) VALUES(?,?,?,?,?,'PENDING',0,NULL,?,?)""",
                (
                    delivery_id,
                    identity_id,
                    logical_notification_id,
                    purpose_id,
                    surface,
                    timestamp,
                    timestamp,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT delivery_id FROM deliveries "
                "WHERE identity_id=? AND logical_notification_id=?",
                (identity_id, logical_notification_id),
            ).fetchone()
            if row is None:
                raise
            return False

    def begin_attempt(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        logical_notification_id: str,
        surface: str,
        updated_at: datetime,
    ) -> bool:
        cur = conn.execute(
            """UPDATE deliveries
               SET surface=?,state='ATTEMPTING',attempt_count=attempt_count+1,updated_at=?
               WHERE identity_id=? AND logical_notification_id=?
                 AND state!='DELIVERED'""",
            (
                surface,
                datetime_to_text(updated_at, "updated_at"),
                identity_id,
                logical_notification_id,
            ),
        )
        return cur.rowcount == 1

    def mark_failed(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        logical_notification_id: str,
        updated_at: datetime,
    ) -> None:
        conn.execute(
            """UPDATE deliveries SET state='FAILED',updated_at=?
               WHERE identity_id=? AND logical_notification_id=? AND state!='DELIVERED'""",
            (
                datetime_to_text(updated_at, "updated_at"),
                identity_id,
                logical_notification_id,
            ),
        )

    def mark_delivered(
        self,
        conn: sqlite3.Connection,
        *,
        identity_id: str,
        logical_notification_id: str,
        surface: str,
        external_ref: Optional[str],
        updated_at: datetime,
    ) -> bool:
        cur = conn.execute(
            """UPDATE deliveries
               SET surface=?,state='DELIVERED',external_ref=?,updated_at=?
               WHERE identity_id=? AND logical_notification_id=?
                 AND state!='DELIVERED'""",
            (
                surface,
                external_ref,
                datetime_to_text(updated_at, "updated_at"),
                identity_id,
                logical_notification_id,
            ),
        )
        return cur.rowcount == 1
