from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from xiaoyu.core.effects import DispatchOutcome, DispatchStatus
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.effects import EffectRepository, OutboxRepository


Transport = Callable[[dict, Optional[str]], DispatchOutcome]


class OutboxDispatcher:
    def __init__(
        self,
        db: Database,
        transports: Dict[str, Transport],
        effect_repo=None,
        outbox_repo=None,
        fault_hook=None,
    ) -> None:
        self.db = db
        self.transports = dict(transports)
        self.effect_repo = effect_repo or EffectRepository()
        self.outbox_repo = outbox_repo or OutboxRepository()
        self.fault_hook = fault_hook

    def recover_inflight(self, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            return self.outbox_repo.recover_claimed_as_reconciliation(conn, current)

    def dispatch_once(self, limit: int = 20, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            claimed = self.outbox_repo.claim_due(conn, current, limit)
            for row in claimed:
                self.effect_repo.set_state(conn, row.effect_id, "DISPATCHING", current)

        processed = 0
        for row in claimed:
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
                        result={"error_type": type(exc).__name__, "error": str(exc)},
                    )
            if self.fault_hook:
                self.fault_hook("after_dispatch", row)
            self._persist_outcome(row, outcome, current)
        return processed

    def _persist_outcome(self, row, outcome: DispatchOutcome, now: datetime) -> None:
        with self.db.transaction(immediate=True) as conn:
            if outcome.status == DispatchStatus.SUCCEEDED:
                self.outbox_repo.mark(conn, row.outbox_id, "SENT", now)
                self.effect_repo.set_state(conn, row.effect_id, "SUCCEEDED", now)
                return

            if outcome.status == DispatchStatus.FAILED_RETRYABLE:
                if row.replayable and row.idempotency_key:
                    delay = max(0.0, float(outcome.retry_after_s or 1.0))
                    self.outbox_repo.mark(
                        conn,
                        row.outbox_id,
                        "FAILED_RETRYABLE",
                        now,
                        next_attempt_at=now + timedelta(seconds=delay),
                    )
                    self.effect_repo.set_state(conn, row.effect_id, "QUEUED", now)
                else:
                    self.outbox_repo.mark(
                        conn, row.outbox_id, "NEEDS_RECONCILIATION", now
                    )
                    self.effect_repo.set_state(
                        conn, row.effect_id, "NEEDS_RECONCILIATION", now
                    )
                return

            if outcome.status == DispatchStatus.FAILED_FINAL:
                self.outbox_repo.mark(conn, row.outbox_id, "FAILED_FINAL", now)
                self.effect_repo.set_state(conn, row.effect_id, "FAILED", now)
                return

            self.outbox_repo.mark(conn, row.outbox_id, "NEEDS_RECONCILIATION", now)
            self.effect_repo.set_state(
                conn, row.effect_id, "NEEDS_RECONCILIATION", now
            )
