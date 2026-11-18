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
    """Logical notification + carrier-attempt persistence.

    A logical delivery can have multiple historical carrier attempts, but at most
    one QUEUED/DISPATCHING/UNKNOWN attempt at a time.
    """

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

    def reserve_attempt(
        self,
        conn: sqlite3.Connection,
        *,
        attempt_id: str,
        delivery_id: str,
        identity_id: str,
        logical_notification_id: str,
        effect_id: str,
        purpose_id: Optional[str],
        surface: str,
        created_at: datetime,
    ) -> bool:
        delivery = conn.execute(
            """SELECT state,purpose_id FROM deliveries
               WHERE delivery_id=? AND identity_id=? AND logical_notification_id=?""",
            (delivery_id, identity_id, logical_notification_id),
        ).fetchone()
        if delivery is None:
            raise KeyError("logical delivery not found: %s" % delivery_id)
        if delivery["purpose_id"] != purpose_id:
            raise ValueError(
                "delivery purpose does not match effect purpose"
            )
        if str(delivery["state"]) not in ("PENDING", "FAILED"):
            return False

        timestamp = datetime_to_text(created_at, "created_at")
        try:
            conn.execute(
                """INSERT INTO delivery_attempts(
                       attempt_id,identity_id,delivery_id,logical_notification_id,
                       effect_id,surface,state,external_ref,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,'QUEUED',NULL,?,?)""",
                (
                    attempt_id,
                    identity_id,
                    delivery_id,
                    logical_notification_id,
                    effect_id,
                    surface,
                    timestamp,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError:
            return False

        cur = conn.execute(
            """UPDATE deliveries
               SET surface=?,state='ATTEMPTING',attempt_count=attempt_count+1,updated_at=?
               WHERE delivery_id=? AND identity_id=? AND logical_notification_id=?
                 AND state IN ('PENDING','FAILED')""",
            (
                surface,
                timestamp,
                delivery_id,
                identity_id,
                logical_notification_id,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("delivery changed while reserving attempt")
        return True

    def mark_dispatching(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        updated_at: datetime,
    ) -> None:
        conn.execute(
            """UPDATE delivery_attempts
               SET state='DISPATCHING',updated_at=?
               WHERE effect_id=? AND state='QUEUED'""",
            (datetime_to_text(updated_at, "updated_at"), effect_id),
        )

    def mark_retryable(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        updated_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(updated_at, "updated_at")
        conn.execute(
            """UPDATE delivery_attempts
               SET state='QUEUED',updated_at=?
               WHERE effect_id=? AND state='DISPATCHING'""",
            (timestamp, effect_id),
        )

    def mark_succeeded(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        external_ref: Optional[str],
        updated_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(updated_at, "updated_at")
        row = conn.execute(
            """SELECT delivery_id FROM delivery_attempts
               WHERE effect_id=?""",
            (effect_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            """UPDATE delivery_attempts
               SET state='DELIVERED',external_ref=?,updated_at=?
               WHERE effect_id=?""",
            (external_ref, timestamp, effect_id),
        )
        conn.execute(
            """UPDATE deliveries
               SET state='DELIVERED',external_ref=?,updated_at=?
               WHERE delivery_id=? AND state!='DELIVERED'""",
            (external_ref, timestamp, row["delivery_id"]),
        )

    def mark_failed_final(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        updated_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(updated_at, "updated_at")
        row = conn.execute(
            "SELECT delivery_id FROM delivery_attempts WHERE effect_id=?",
            (effect_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            """UPDATE delivery_attempts
               SET state='FAILED_FINAL',updated_at=?
               WHERE effect_id=?""",
            (timestamp, effect_id),
        )
        conn.execute(
            """UPDATE deliveries SET state='FAILED',updated_at=?
               WHERE delivery_id=? AND state!='DELIVERED'""",
            (timestamp, row["delivery_id"]),
        )

    def mark_unknown(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        updated_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(updated_at, "updated_at")
        row = conn.execute(
            "SELECT delivery_id FROM delivery_attempts WHERE effect_id=?",
            (effect_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            """UPDATE delivery_attempts
               SET state='UNKNOWN',updated_at=?
               WHERE effect_id=? AND state!='DELIVERED'""",
            (timestamp, effect_id),
        )
        conn.execute(
            """UPDATE deliveries
               SET state='NEEDS_RECONCILIATION',updated_at=?
               WHERE delivery_id=? AND state!='DELIVERED'""",
            (timestamp, row["delivery_id"]),
        )

    def mark_cancelled(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        updated_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(updated_at, "updated_at")
        row = conn.execute(
            "SELECT delivery_id FROM delivery_attempts WHERE effect_id=?",
            (effect_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            """UPDATE delivery_attempts
               SET state='CANCELLED',updated_at=?
               WHERE effect_id=? AND state IN ('QUEUED','DISPATCHING')""",
            (timestamp, effect_id),
        )
        conn.execute(
            """UPDATE deliveries
               SET state='CANCELLED',updated_at=?
               WHERE delivery_id=? AND state!='DELIVERED'""",
            (timestamp, row["delivery_id"]),
        )

    def reconcile_stranded(
        self,
        conn: sqlite3.Connection,
        updated_at: datetime,
    ) -> int:
        rows = conn.execute(
            """SELECT da.effect_id
               FROM delivery_attempts da
               JOIN effects e ON e.effect_id=da.effect_id
               WHERE e.dispatch_state='NEEDS_RECONCILIATION'
                 AND da.state IN ('QUEUED','DISPATCHING')"""
        ).fetchall()
        for row in rows:
            self.mark_unknown(conn, str(row["effect_id"]), updated_at)
        return len(rows)
