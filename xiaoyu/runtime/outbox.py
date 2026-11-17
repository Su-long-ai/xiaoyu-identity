from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from typing import Callable, Dict, Optional

from xiaoyu.contracts import ActionReceipt
from xiaoyu.contracts.common import canonical_json
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.effects import EffectRepository, OutboxRepository
from xiaoyu.persistence.repositories.receipts import (
    ActionReceiptRepository,
    DeliveryRepository,
)


Transport = Callable[[dict, Optional[str]], DispatchOutcome]


class OutboxDispatcher:
    def __init__(
        self,
        db: Database,
        transports: Dict[str, Transport],
        effect_repo=None,
        outbox_repo=None,
        fault_hook=None,
        receipt_repo=None,
        delivery_repo=None,
    ) -> None:
        self.db = db
        self.transports = dict(transports)
        self.effect_repo = effect_repo or EffectRepository()
        self.outbox_repo = outbox_repo or OutboxRepository()
        self.fault_hook = fault_hook
        self.receipt_repo = receipt_repo or ActionReceiptRepository()
        self.delivery_repo = delivery_repo or DeliveryRepository()

    def recover_inflight(self, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            recovered = self.outbox_repo.recover_claimed_as_reconciliation(
                conn, current
            )
            self.delivery_repo.reconcile_stranded(conn, current)
            return recovered

    def dispatch_once(self, limit: int = 20, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            claimed = self.outbox_repo.claim_due(conn, current, limit)
            ready = []
            for row in claimed:
                if self._purpose_is_terminal(conn, row.purpose_id):
                    self.outbox_repo.mark(
                        conn, row.outbox_id, "FAILED_FINAL", current
                    )
                    self.effect_repo.set_state(
                        conn, row.effect_id, "FAILED", current
                    )
                    self.delivery_repo.mark_cancelled(
                        conn, row.effect_id, current
                    )
                    continue
                self.effect_repo.set_state(
                    conn, row.effect_id, "DISPATCHING", current
                )
                self.delivery_repo.mark_dispatching(
                    conn, row.effect_id, current
                )
                ready.append(row)

        processed = 0
        for row in ready:
            processed += 1
            if self.fault_hook:
                self.fault_hook("before_dispatch", row)
            transport = self.transports.get(row.destination)
            if transport is None:
                outcome = DispatchOutcome(
                    DispatchStatus.FAILED_FINAL,
                    result={"error": "unknown_destination"},
                )
            else:
                try:
                    outcome = transport(row.payload, row.idempotency_key)
                except Exception as exc:
                    outcome = DispatchOutcome(
                        DispatchStatus.UNKNOWN,
                        result={
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
            if self.fault_hook:
                self.fault_hook("after_dispatch", row)
            self._persist_outcome(row, outcome, current)
        return processed

    @staticmethod
    def _purpose_is_terminal(conn, purpose_id: Optional[str]) -> bool:
        if purpose_id is None:
            return False
        row = conn.execute(
            "SELECT state FROM purposes WHERE purpose_id=?",
            (purpose_id,),
        ).fetchone()
        if row is None:
            # Backward-compatible for effects created before Purpose integration.
            return False
        return str(row["state"]) in {
            "CANCELLED",
            "SUPERSEDED",
            "EXPIRED",
            "COMPLETED",
        }

    def _persist_outcome(
        self,
        row,
        outcome: DispatchOutcome,
        now: datetime,
    ) -> None:
        with self.db.transaction(immediate=True) as conn:
            if outcome.status == DispatchStatus.SUCCEEDED:
                request_digest = "sha256:" + hashlib.sha256(
                    canonical_json(row.payload).encode("utf-8")
                ).hexdigest()
                result_payload = outcome.result or {}
                result_digest = "sha256:" + hashlib.sha256(
                    canonical_json(result_payload).encode("utf-8")
                ).hexdigest()
                receipt = ActionReceipt(
                    receipt_id=str(uuid.uuid4()),
                    effect_id=row.effect_id,
                    actor_id=row.actor_id,
                    provider_id=row.destination,
                    authorization_decision_id=row.authorization_decision_id,
                    request_digest=request_digest,
                    result_class=outcome.status.value,
                    result_digest=result_digest,
                    external_ref=outcome.external_ref,
                    observed_at=now,
                    metadata={"attempt_count": row.attempt_count},
                )
                self.receipt_repo.insert(
                    conn, row.identity_id, receipt
                )
                self.outbox_repo.mark(
                    conn, row.outbox_id, "SENT", now
                )
                self.effect_repo.set_state(
                    conn, row.effect_id, "SUCCEEDED", now
                )
                self.delivery_repo.mark_succeeded(
                    conn,
                    row.effect_id,
                    outcome.external_ref,
                    now,
                )
                return

            if outcome.status == DispatchStatus.FAILED_RETRYABLE:
                if row.replayable and row.idempotency_key:
                    delay = max(
                        0.0,
                        float(outcome.retry_after_s or 1.0),
                    )
                    self.outbox_repo.mark(
                        conn,
                        row.outbox_id,
                        "FAILED_RETRYABLE",
                        now,
                        next_attempt_at=now
                        + timedelta(seconds=delay),
                    )
                    self.effect_repo.set_state(
                        conn, row.effect_id, "QUEUED", now
                    )
                    self.delivery_repo.mark_retryable(
                        conn, row.effect_id, now
                    )
                else:
                    self.outbox_repo.mark(
                        conn,
                        row.outbox_id,
                        "NEEDS_RECONCILIATION",
                        now,
                    )
                    self.effect_repo.set_state(
                        conn,
                        row.effect_id,
                        "NEEDS_RECONCILIATION",
                        now,
                    )
                    self.delivery_repo.mark_unknown(
                        conn, row.effect_id, now
                    )
                return

            if outcome.status == DispatchStatus.FAILED_FINAL:
                self.outbox_repo.mark(
                    conn, row.outbox_id, "FAILED_FINAL", now
                )
                self.effect_repo.set_state(
                    conn, row.effect_id, "FAILED", now
                )
                self.delivery_repo.mark_failed_final(
                    conn, row.effect_id, now
                )
                return

            self.outbox_repo.mark(
                conn,
                row.outbox_id,
                "NEEDS_RECONCILIATION",
                now,
            )
            self.effect_repo.set_state(
                conn,
                row.effect_id,
                "NEEDS_RECONCILIATION",
                now,
            )
            self.delivery_repo.mark_unknown(
                conn, row.effect_id, now
            )
