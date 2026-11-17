from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from xiaoyu.contracts import EffectIntent
from xiaoyu.contracts.common import canonical_json, datetime_to_text


@dataclass(frozen=True)
class ClaimedOutbox:
    outbox_id: str
    identity_id: str
    effect_id: str
    destination: str
    payload: Dict[str, Any]
    attempt_count: int
    replayable: bool
    idempotency_key: Optional[str]
    actor_id: str
    authorization_decision_id: str
    request: Dict[str, Any]
    purpose_id: Optional[str]
    action_class: str


class EffectRepository:
    def insert(
        self,
        conn: sqlite3.Connection,
        identity_id: str,
        effect: EffectIntent,
        state: str,
        updated_at: datetime,
        authorization_decision_id: str,
    ) -> None:
        conn.execute(
            """INSERT INTO effects(
                   effect_id,identity_id,intent_id,purpose_id,actor_id,action_class,
                   idempotency_key,replayable,dispatch_state,request_json,receipt_id,
                   verifier_state,created_at,updated_at,authorization_decision_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                effect.effect_id,
                identity_id,
                effect.intent_id,
                effect.purpose_id,
                effect.actor_id,
                effect.action_class,
                effect.idempotency_key,
                1 if effect.replayable else 0,
                state,
                canonical_json(effect.request),
                None,
                None,
                datetime_to_text(effect.created_at, "created_at"),
                datetime_to_text(updated_at, "updated_at"),
                authorization_decision_id,
            ),
        )

    def set_authorization_failed(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        reason: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            """UPDATE effects
               SET dispatch_state='FAILED',verifier_state=?,updated_at=?
               WHERE effect_id=?""",
            (
                "AUTH_DENIED:" + reason,
                datetime_to_text(updated_at, "updated_at"),
                effect_id,
            ),
        )
        if cur.rowcount != 1:
            raise KeyError("unknown effect_id %s" % effect_id)

    def set_state(
        self,
        conn: sqlite3.Connection,
        effect_id: str,
        state: str,
        updated_at: datetime,
    ) -> None:
        cur = conn.execute(
            "UPDATE effects SET dispatch_state=?,updated_at=? WHERE effect_id=?",
            (state, datetime_to_text(updated_at, "updated_at"), effect_id),
        )
        if cur.rowcount != 1:
            raise KeyError("unknown effect_id %s" % effect_id)


class OutboxRepository:
    def enqueue(
        self,
        conn: sqlite3.Connection,
        *,
        outbox_id: str,
        identity_id: str,
        effect_id: str,
        destination: str,
        payload: Dict[str, Any],
        created_at: datetime,
    ) -> None:
        timestamp = datetime_to_text(created_at, "created_at")
        conn.execute(
            """INSERT INTO outbox(
                   outbox_id,identity_id,effect_id,destination,payload_json,state,
                   attempt_count,next_attempt_at,created_at,updated_at
               ) VALUES(?,?,?,?,?,'PENDING',0,NULL,?,?)""",
            (
                outbox_id,
                identity_id,
                effect_id,
                destination,
                canonical_json(payload),
                timestamp,
                timestamp,
            ),
        )

    def claim_due(
        self,
        conn: sqlite3.Connection,
        now: datetime,
        limit: int = 20,
    ) -> List[ClaimedOutbox]:
        now_text = datetime_to_text(now, "now")
        rows = conn.execute(
            """SELECT o.outbox_id,o.identity_id,o.effect_id,o.destination,o.payload_json,
                      o.attempt_count,e.replayable,e.idempotency_key,e.actor_id,
                      e.authorization_decision_id,e.request_json,e.purpose_id,
                      e.action_class
               FROM outbox o
               JOIN effects e ON e.effect_id=o.effect_id
               WHERE o.state IN ('PENDING','FAILED_RETRYABLE')
                 AND (o.next_attempt_at IS NULL OR o.next_attempt_at<=?)
               ORDER BY o.created_at,o.outbox_id
               LIMIT ?""",
            (now_text, max(1, min(int(limit), 100))),
        ).fetchall()
        claimed = []
        for row in rows:
            cur = conn.execute(
                """UPDATE outbox
                   SET state='CLAIMED',attempt_count=attempt_count+1,updated_at=?
                   WHERE outbox_id=? AND state IN ('PENDING','FAILED_RETRYABLE')""",
                (now_text, row["outbox_id"]),
            )
            if cur.rowcount != 1:
                continue
            claimed.append(
                ClaimedOutbox(
                    outbox_id=str(row["outbox_id"]),
                    identity_id=str(row["identity_id"]),
                    effect_id=str(row["effect_id"]),
                    destination=str(row["destination"]),
                    payload=json.loads(row["payload_json"]),
                    attempt_count=int(row["attempt_count"]) + 1,
                    replayable=bool(row["replayable"]),
                    idempotency_key=row["idempotency_key"],
                    actor_id=str(row["actor_id"]),
                    authorization_decision_id=str(row["authorization_decision_id"]),
                    request=json.loads(row["request_json"]),
                    purpose_id=row["purpose_id"],
                    action_class=str(row["action_class"]),
                )
            )
        return claimed

    def mark(
        self,
        conn: sqlite3.Connection,
        outbox_id: str,
        state: str,
        updated_at: datetime,
        next_attempt_at: Optional[datetime] = None,
    ) -> None:
        cur = conn.execute(
            """UPDATE outbox SET state=?,next_attempt_at=?,updated_at=?
               WHERE outbox_id=?""",
            (
                state,
                None if next_attempt_at is None else datetime_to_text(next_attempt_at, "next_attempt_at"),
                datetime_to_text(updated_at, "updated_at"),
                outbox_id,
            ),
        )
        if cur.rowcount != 1:
            raise KeyError("unknown outbox_id %s" % outbox_id)

    def recover_claimed_as_reconciliation(self, conn: sqlite3.Connection, now: datetime) -> int:
        timestamp = datetime_to_text(now, "now")
        rows = conn.execute(
            "SELECT outbox_id,effect_id FROM outbox WHERE state='CLAIMED'"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE outbox SET state='NEEDS_RECONCILIATION',updated_at=? WHERE outbox_id=?",
                (timestamp, row["outbox_id"]),
            )
            conn.execute(
                "UPDATE effects SET dispatch_state='NEEDS_RECONCILIATION',updated_at=? WHERE effect_id=?",
                (timestamp, row["effect_id"]),
            )
        return len(rows)
