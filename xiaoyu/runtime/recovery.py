from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from xiaoyu.contracts.common import datetime_to_text
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.effects import OutboxRepository
from xiaoyu.persistence.repositories.receipts import DeliveryRepository


@dataclass(frozen=True)
class RecoveryItem:
    kind: str
    item_id: str
    state: str
    recovery_path: str


STATE_RECOVERY_PATHS = {
    "QUEUED": "dispatcher claims durable outbox work",
    "CLAIMED": "restart requeues if pre-dispatch; otherwise reconciles",
    "DISPATCHING": "restart requires reconciliation before replay",
    "ATTEMPTING": "carrier effect/outbox drives terminal delivery state",
    "ACTIVE": "durable purpose occurrence is executable work",
    "WAITING": "owner decision is required",
    "NEEDS_RECONCILIATION": "manual/provider reconciliation is required",
}


class ExecutionRecoveryQueue:
    """Visibility + deterministic restart recovery for execution work.

    It never guesses whether an unknown external side effect happened.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.outbox_repo = OutboxRepository()
        self.delivery_repo = DeliveryRepository()

    def recover_restart(
        self,
        now: Optional[datetime] = None,
    ) -> dict:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            claimed = self.outbox_repo.recover_claimed(
                conn, current
            )
            self.delivery_repo.reconcile_stranded(conn, current)
            rebuilt = self._recover_active_without_work(
                conn, current
            )
        return {
            "claimed_recovered": claimed,
            "active_work_rebuilt": rebuilt,
        }

    @staticmethod
    def _recover_active_without_work(conn, now: datetime) -> int:
        rows = conn.execute(
            """SELECT p.purpose_id,p.identity_id,p.revision,
                      p.resolved_utc_time
               FROM purposes p
               WHERE p.state='ACTIVE'
                 AND p.resolved_utc_time IS NOT NULL
                 AND NOT EXISTS(
                     SELECT 1 FROM purpose_occurrences po
                     WHERE po.purpose_id=p.purpose_id
                       AND po.purpose_revision=p.revision
                 )
                 AND NOT EXISTS(
                     SELECT 1 FROM effects e
                     WHERE e.purpose_id=p.purpose_id
                       AND e.purpose_revision=p.revision
                 )"""
        ).fetchall()
        stamp = datetime_to_text(
            now.astimezone(timezone.utc), "updated_at"
        )
        rebuilt = 0
        for row in rows:
            occurrence_id = "%s:r%d" % (
                row["purpose_id"],
                int(row["revision"]),
            )
            conn.execute(
                """INSERT OR IGNORE INTO purpose_occurrences(
                       occurrence_id,identity_id,purpose_id,purpose_revision,
                       scheduled_for_utc,state,effect_id,activated_at,updated_at
                   ) VALUES(?,?,?,?,?,'READY',NULL,?,?)""",
                (
                    occurrence_id,
                    row["identity_id"],
                    row["purpose_id"],
                    int(row["revision"]),
                    row["resolved_utc_time"],
                    stamp,
                    stamp,
                ),
            )
            rebuilt += 1
        return rebuilt

    def list_open(
        self,
        identity_id: str,
    ) -> List[RecoveryItem]:
        items: List[RecoveryItem] = []
        with self.db.transaction() as conn:
            for row in conn.execute(
                """SELECT effect_id,dispatch_state FROM effects
                   WHERE identity_id=?
                     AND dispatch_state='NEEDS_RECONCILIATION'
                   ORDER BY updated_at,effect_id""",
                (identity_id,),
            ).fetchall():
                items.append(
                    RecoveryItem(
                        "effect",
                        str(row["effect_id"]),
                        str(row["dispatch_state"]),
                        STATE_RECOVERY_PATHS["NEEDS_RECONCILIATION"],
                    )
                )

            for row in conn.execute(
                """SELECT delivery_id,state FROM deliveries
                   WHERE identity_id=?
                     AND state='NEEDS_RECONCILIATION'
                   ORDER BY updated_at,delivery_id""",
                (identity_id,),
            ).fetchall():
                items.append(
                    RecoveryItem(
                        "delivery",
                        str(row["delivery_id"]),
                        str(row["state"]),
                        STATE_RECOVERY_PATHS["NEEDS_RECONCILIATION"],
                    )
                )

            for row in conn.execute(
                """SELECT attempt_id,state FROM delivery_attempts
                   WHERE identity_id=? AND state='UNKNOWN'
                   ORDER BY updated_at,attempt_id""",
                (identity_id,),
            ).fetchall():
                items.append(
                    RecoveryItem(
                        "delivery_attempt",
                        str(row["attempt_id"]),
                        str(row["state"]),
                        "manual/provider reconciliation is required",
                    )
                )

            for row in conn.execute(
                """SELECT purpose_id,state FROM purposes
                   WHERE identity_id=?
                     AND state IN ('WAITING','NEEDS_RECONCILIATION')
                   ORDER BY updated_at,purpose_id""",
                (identity_id,),
            ).fetchall():
                state = str(row["state"])
                items.append(
                    RecoveryItem(
                        "purpose",
                        str(row["purpose_id"]),
                        state,
                        STATE_RECOVERY_PATHS[state],
                    )
                )
        return items
