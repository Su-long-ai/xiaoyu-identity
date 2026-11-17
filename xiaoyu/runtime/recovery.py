from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Dict, List, Optional
import uuid

from xiaoyu.contracts import ActionReceipt
from xiaoyu.contracts.common import canonical_json, datetime_to_text
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.effects import OutboxRepository
from xiaoyu.persistence.repositories.receipts import (
    ActionReceiptRepository,
    DeliveryRepository,
)


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


class ExecutionReconciler:
    """Evidence-required convergence for effects with unknown external outcome."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.outbox_repo = OutboxRepository()
        self.receipt_repo = ActionReceiptRepository()
        self.delivery_repo = DeliveryRepository()

    def reconcile_effect(
        self,
        *,
        effect_id: str,
        outcome: str,
        evidence: Dict[str, object],
        external_ref: Optional[str] = None,
        observed_at: Optional[datetime] = None,
    ) -> ActionReceipt:
        if outcome not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("reconciliation outcome must be SUCCEEDED or FAILED")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("reconciliation requires non-empty external evidence")
        current = observed_at or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        with self.db.transaction(immediate=True) as conn:
            row = conn.execute(
                """SELECT e.identity_id,e.actor_id,e.authorization_decision_id,
                          e.purpose_id,e.purpose_revision,
                          e.purpose_occurrence_id,e.dispatch_state,
                          o.outbox_id,o.state AS outbox_state,o.payload_json,
                          ea.actor_provider_id,ea.authorized_request_digest
                   FROM effects e
                   JOIN outbox o ON o.effect_id=e.effect_id
                   JOIN execution_authorizations ea
                     ON ea.authorization_decision_id=e.authorization_decision_id
                   WHERE e.effect_id=?""",
                (effect_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown effect_id %s" % effect_id)
            if str(row["dispatch_state"]) != "NEEDS_RECONCILIATION":
                raise ValueError("effect is not awaiting reconciliation")
            if str(row["outbox_state"]) != "NEEDS_RECONCILIATION":
                raise ValueError("outbox is not awaiting reconciliation")

            payload = json.loads(str(row["payload_json"]))
            request_digest = "sha256:" + hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest()
            result_payload = {
                "outcome": outcome,
                "evidence": evidence,
            }
            result_digest = "sha256:" + hashlib.sha256(
                canonical_json(result_payload).encode("utf-8")
            ).hexdigest()
            receipt = ActionReceipt(
                receipt_id="reconcile:" + str(uuid.uuid4()),
                effect_id=effect_id,
                actor_id=str(row["actor_id"]),
                provider_id=row["actor_provider_id"],
                authorization_decision_id=str(
                    row["authorization_decision_id"]
                ),
                request_digest=request_digest,
                result_class="RECONCILED_" + outcome,
                result_digest=result_digest,
                external_ref=external_ref,
                observed_at=current,
                metadata={
                    "reconciliation": True,
                    "evidence": evidence,
                    "authorized_request_digest": row[
                        "authorized_request_digest"
                    ],
                },
            )
            self.receipt_repo.insert(
                conn,
                str(row["identity_id"]),
                receipt,
            )

            stamp = datetime_to_text(current, "updated_at")
            purpose_id = row["purpose_id"]
            purpose_revision = row["purpose_revision"]
            occurrence_id = row["purpose_occurrence_id"]

            if outcome == "SUCCEEDED":
                self.outbox_repo.mark(
                    conn,
                    str(row["outbox_id"]),
                    "SENT",
                    current,
                )
                conn.execute(
                    """UPDATE effects
                       SET dispatch_state='SUCCEEDED',
                           verifier_state=?,updated_at=?
                       WHERE effect_id=?""",
                    (
                        "RECONCILED_SUCCEEDED:" + result_digest,
                        stamp,
                        effect_id,
                    ),
                )
                self.delivery_repo.mark_succeeded(
                    conn,
                    effect_id,
                    external_ref,
                    current,
                )
                if occurrence_id is not None:
                    conn.execute(
                        """UPDATE purpose_occurrences
                           SET state='COMPLETED',effect_id=?,updated_at=?
                           WHERE occurrence_id=? AND purpose_id=?
                             AND purpose_revision=?
                             AND state='NEEDS_RECONCILIATION'""",
                        (
                            effect_id,
                            stamp,
                            occurrence_id,
                            purpose_id,
                            purpose_revision,
                        ),
                    )
                    conn.execute(
                        """UPDATE purposes
                           SET state='COMPLETED',updated_at=?,
                               last_evaluated_at=?
                           WHERE purpose_id=? AND revision=?
                             AND state='NEEDS_RECONCILIATION'""",
                        (
                            stamp,
                            stamp,
                            purpose_id,
                            purpose_revision,
                        ),
                    )
            else:
                self.outbox_repo.mark(
                    conn,
                    str(row["outbox_id"]),
                    "FAILED_FINAL",
                    current,
                )
                conn.execute(
                    """UPDATE effects
                       SET dispatch_state='FAILED',
                           verifier_state=?,updated_at=?
                       WHERE effect_id=?""",
                    (
                        "RECONCILED_FAILED:" + result_digest,
                        stamp,
                        effect_id,
                    ),
                )
                self.delivery_repo.mark_failed_final(
                    conn,
                    effect_id,
                    current,
                )
                if occurrence_id is not None:
                    conn.execute(
                        """UPDATE purpose_occurrences
                           SET state='FAILED_FINAL',effect_id=?,updated_at=?
                           WHERE occurrence_id=? AND purpose_id=?
                             AND purpose_revision=?
                             AND state='NEEDS_RECONCILIATION'""",
                        (
                            effect_id,
                            stamp,
                            occurrence_id,
                            purpose_id,
                            purpose_revision,
                        ),
                    )
                    # The external effect is now known to have failed, but the
                    # Purpose is still unmet.  Return it to an explicit owner
                    # decision rather than inventing a retry/reschedule.
                    conn.execute(
                        """UPDATE purposes
                           SET state='WAITING',updated_at=?,
                               last_evaluated_at=?
                           WHERE purpose_id=? AND revision=?
                             AND state='NEEDS_RECONCILIATION'""",
                        (
                            stamp,
                            stamp,
                            purpose_id,
                            purpose_revision,
                        ),
                    )

            return receipt
