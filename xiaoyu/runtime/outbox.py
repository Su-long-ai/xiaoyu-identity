from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from typing import Callable, Dict, Optional, Union

from xiaoyu.contracts import ActionReceipt
from xiaoyu.contracts.common import canonical_json
from xiaoyu.core.effects import DispatchOutcome, DispatchStatus
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.effects import EffectRepository, OutboxRepository
from xiaoyu.persistence.repositories.receipts import (
    ActionReceiptRepository,
    DeliveryRepository,
)
from xiaoyu.persistence.repositories.execution_auth import (
    DispatchAuthorizationDenied,
    ExecutionAuthorizationRepository,
)
from xiaoyu.runtime.execution_resources import ExecutionResourceHandles


Transport = Callable[[dict, Optional[str]], DispatchOutcome]


@dataclass(frozen=True)
class TransportBinding:
    send: Transport
    actor_id: Optional[str]
    provider_id: Optional[str]
    actor_implementation_digest: Optional[str]
    actor_authorization_digest: Optional[str]
    artifact_digest: Optional[str]
    interface_digest: Optional[str]
    tool_schema_digest: Optional[str]
    capability: Optional[str]


TransportEntry = Union[Transport, TransportBinding]


class OutboxDispatcher:
    def __init__(
        self,
        db: Database,
        transports: Dict[str, TransportEntry],
        effect_repo=None,
        outbox_repo=None,
        fault_hook=None,
        receipt_repo=None,
        delivery_repo=None,
        execution_auth_repo=None,
        max_attempts: int = 5,
        resource_broker: Optional[ExecutionResourceHandles] = None,
    ) -> None:
        self.db = db
        self.transports = dict(transports)
        self.effect_repo = effect_repo or EffectRepository()
        self.outbox_repo = outbox_repo or OutboxRepository()
        self.fault_hook = fault_hook
        self.receipt_repo = receipt_repo or ActionReceiptRepository()
        self.delivery_repo = delivery_repo or DeliveryRepository()
        self.execution_auth_repo = (
            execution_auth_repo or ExecutionAuthorizationRepository()
        )
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise ValueError("max_attempts must be an integer")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.resource_broker = resource_broker

    def recover_inflight(self, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            recovered = self.outbox_repo.recover_claimed(
                conn, current
            )
            self.delivery_repo.reconcile_stranded(conn, current)
            return recovered

    def dispatch_once(self, limit: int = 20, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(timezone.utc)

        # Claim is deliberately separate from the dispatch linearization point.
        # A crash here is provably pre-transport and can be safely re-queued.
        with self.db.transaction(immediate=True) as conn:
            claimed = self.outbox_repo.claim_due(conn, current, limit)

        processed = 0
        for row in claimed:
            if self.fault_hook:
                self.fault_hook("after_claim", row)

            # Freeze the exact request before the final preflight.  From this
            # point through receipt persistence, authorization and transport
            # refer to this same canonical object.

            transport, binding_error = self._resolve_transport(
                row,
                self.transports.get(row.destination),
            )
            if binding_error is not None:
                with self.db.transaction(immediate=True) as conn:
                    self.outbox_repo.mark(
                        conn, row.outbox_id, "FAILED_FINAL", current
                    )
                    self.effect_repo.set_authorization_failed(
                        conn,
                        row.effect_id,
                        binding_error,
                        current,
                    )
                    self.delivery_repo.mark_failed_final(
                        conn, row.effect_id, current
                    )
                self._release_effect_resources(row.effect_id)
                continue

            # This is the final authorization check immediately before the
            # transport boundary.  No enqueue-time ALLOW is trusted forever.
            try:
                with self.db.transaction(immediate=True) as conn:
                    self.execution_auth_repo.preflight(
                        conn,
                        authorization_decision_id=row.authorization_decision_id,
                        identity_id=row.identity_id,
                        actor_id=row.actor_id,
                        action_class=row.action_class,
                        purpose_id=row.purpose_id,
                        destination=row.destination,
                        request=transport_payload,
                        effect_request=row.request,
                        now=current,
                        purpose_revision=row.purpose_revision,
                        purpose_occurrence_id=row.purpose_occurrence_id,
                    )
                    purpose_invalid = self._purpose_invalid_reason(conn, row)
                    if purpose_invalid is not None:
                        raise DispatchAuthorizationDenied(purpose_invalid)

                    self.effect_repo.set_state(
                        conn, row.effect_id, "DISPATCHING", current
                    )
                    if row.purpose_occurrence_id is not None:
                        cur = conn.execute(
                            """UPDATE purpose_occurrences
                               SET state='CLAIMED',effect_id=?,updated_at=?
                               WHERE occurrence_id=? AND purpose_id=?
                                 AND purpose_revision=?
                                 AND state IN ('READY','CLAIMED')""",
                            (
                                row.effect_id,
                                current.astimezone(timezone.utc).isoformat(
                                    timespec="microseconds"
                                ),
                                row.purpose_occurrence_id,
                                row.purpose_id,
                                row.purpose_revision,
                            ),
                        )
                        if cur.rowcount != 1:
                            raise DispatchAuthorizationDenied(
                                "PURPOSE_OCCURRENCE_CLAIM_RACE"
                            )
                    self.delivery_repo.mark_dispatching(
                        conn, row.effect_id, current
                    )
            except DispatchAuthorizationDenied as exc:
                with self.db.transaction(immediate=True) as conn:
                    self.outbox_repo.mark(
                        conn, row.outbox_id, "FAILED_FINAL", current
                    )
                    self.effect_repo.set_authorization_failed(
                        conn,
                        row.effect_id,
                        str(exc),
                        current,
                    )
                    if str(exc).startswith("PURPOSE_"):
                        self.delivery_repo.mark_cancelled(
                            conn, row.effect_id, current
                        )
                    else:
                        self.delivery_repo.mark_failed_final(
                            conn, row.effect_id, current
                        )
                if str(exc).startswith("PURPOSE_"):
                    self._cancel_effect_resources(row.effect_id)
                else:
                    self._release_effect_resources(row.effect_id)
                continue

            # Crossing the transaction above means dispatch may now happen.
            # Cancellation after this point cannot truthfully claim "not sent".
            if self.fault_hook:
                self.fault_hook("before_dispatch", row)

            transport_payload = json.loads(canonical_json(row.payload))
            transport_request_digest = "sha256:" + hashlib.sha256(
                canonical_json(transport_payload).encode("utf-8")
            ).hexdigest()
            try:
                outcome = transport(
                    transport_payload,
                    row.idempotency_key,
                )
            except Exception as exc:
                outcome = DispatchOutcome(
                    DispatchStatus.UNKNOWN,
                    result={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            processed += 1
            if self.fault_hook:
                self.fault_hook("after_dispatch", row)
            try:
                self._persist_outcome(
                    row,
                    outcome,
                    current,
                    request_digest=transport_request_digest,
                )
            finally:
                self._release_effect_resources(row.effect_id)
        return processed

    def _release_effect_resources(self, effect_id: str) -> None:
        if self.resource_broker is not None:
            self.resource_broker.release_effect(effect_id)

    def _cancel_effect_resources(self, effect_id: str) -> None:
        if self.resource_broker is not None:
            self.resource_broker.cancel_effect(effect_id)

    @staticmethod
    def _resolve_transport(row, entry):
        if entry is None:
            return None, "TRANSPORT_DESTINATION_MISSING"

        versioned = any(
            value is not None
            for value in (
                row.provider_artifact_digest,
                row.provider_interface_digest,
                row.provider_tool_schema_digest,
                row.provider_capability,
            )
        )
        if isinstance(entry, TransportBinding):
            comparisons = (
                ("actor_id", row.actor_id, entry.actor_id),
                ("provider_id", row.provider_id, entry.provider_id),
                (
                    "actor_implementation_digest",
                    row.actor_implementation_digest,
                    entry.actor_implementation_digest,
                ),
                (
                    "actor_authorization_digest",
                    row.actor_authorization_digest,
                    entry.actor_authorization_digest,
                ),
                ("artifact_digest", row.provider_artifact_digest, entry.artifact_digest),
                ("interface_digest", row.provider_interface_digest, entry.interface_digest),
                (
                    "tool_schema_digest",
                    row.provider_tool_schema_digest,
                    entry.tool_schema_digest,
                ),
                ("capability", row.provider_capability, entry.capability),
            )
            for name, expected, actual in comparisons:
                if expected is not None and expected != actual:
                    return None, "TRANSPORT_BINDING_%s_CHANGED" % name.upper()
            return entry.send, None

        if versioned:
            return None, "TRANSPORT_BINDING_REQUIRED_FOR_VERSIONED_PROVIDER"
        return entry, None

    @staticmethod
    def _purpose_invalid_reason(conn, row) -> Optional[str]:
        if row.purpose_id is None:
            return None
        purpose = conn.execute(
            "SELECT state,revision FROM purposes WHERE purpose_id=?",
            (row.purpose_id,),
        ).fetchone()
        if purpose is None:
            return None
        if str(purpose["state"]) in {
            "CANCELLED",
            "SUPERSEDED",
            "EXPIRED",
            "COMPLETED",
        }:
            return "PURPOSE_TERMINAL"
        if str(purpose["state"]) == "NEEDS_RECONCILIATION":
            return "PURPOSE_NEEDS_RECONCILIATION"
        if row.purpose_revision is None:
            return "PURPOSE_REVISION_MISSING"
        if int(purpose["revision"]) != int(row.purpose_revision):
            return "PURPOSE_REVISION_STALE"
        if row.purpose_occurrence_id is not None:
            occurrence = conn.execute(
                """SELECT state,purpose_revision FROM purpose_occurrences
                   WHERE occurrence_id=? AND purpose_id=?""",
                (
                    row.purpose_occurrence_id,
                    row.purpose_id,
                ),
            ).fetchone()
            if occurrence is None:
                return "PURPOSE_OCCURRENCE_MISSING"
            if int(occurrence["purpose_revision"]) != int(
                row.purpose_revision
            ):
                return "PURPOSE_OCCURRENCE_STALE"
            if str(occurrence["state"]) not in ("READY", "CLAIMED"):
                return "PURPOSE_OCCURRENCE_NOT_EXECUTABLE"
        return None

    @staticmethod
    def _mark_occurrence(conn, row, state: str, now: datetime) -> None:
        if row.purpose_occurrence_id is None:
            return
        conn.execute(
            """UPDATE purpose_occurrences
               SET state=?,effect_id=?,updated_at=?
               WHERE occurrence_id=? AND purpose_id=?
                 AND purpose_revision=?""",
            (
                state,
                row.effect_id,
                now.astimezone(timezone.utc).isoformat(
                    timespec="microseconds"
                ),
                row.purpose_occurrence_id,
                row.purpose_id,
                row.purpose_revision,
            ),
        )

    @staticmethod
    def _complete_purpose(conn, row, now: datetime) -> None:
        if (
            row.purpose_id is None
            or row.purpose_revision is None
            or row.purpose_occurrence_id is None
        ):
            return
        conn.execute(
            """UPDATE purposes
               SET state='COMPLETED',updated_at=?,last_evaluated_at=?
               WHERE purpose_id=? AND revision=?
                 AND state IN ('ACTIVE','WAITING')""",
            (
                now.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                now.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                row.purpose_id,
                row.purpose_revision,
            ),
        )

    def _persist_outcome(
        self,
        row,
        outcome: DispatchOutcome,
        now: datetime,
        *,
        request_digest: str,
    ) -> None:
        with self.db.transaction(immediate=True) as conn:
            if outcome.status == DispatchStatus.SUCCEEDED:
                result_payload = outcome.result or {}
                result_digest = "sha256:" + hashlib.sha256(
                    canonical_json(result_payload).encode("utf-8")
                ).hexdigest()
                receipt = ActionReceipt(
                    receipt_id=str(uuid.uuid4()),
                    effect_id=row.effect_id,
                    actor_id=row.actor_id,
                    provider_id=row.provider_id,
                    authorization_decision_id=row.authorization_decision_id,
                    request_digest=request_digest,
                    result_class=outcome.status.value,
                    result_digest=result_digest,
                    external_ref=outcome.external_ref,
                    observed_at=now,
                    metadata={
                        "attempt_count": row.attempt_count,
                        "authorized_request_digest": row.authorized_request_digest,
                    },
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
                self._mark_occurrence(
                    conn, row, "COMPLETED", now
                )
                self._complete_purpose(conn, row, now)
                return

            if outcome.status == DispatchStatus.FAILED_RETRYABLE:
                if (
                    row.replayable
                    and row.idempotency_key
                    and row.attempt_count < self.max_attempts
                ):
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
                elif row.replayable and row.idempotency_key:
                    self.outbox_repo.mark(
                        conn,
                        row.outbox_id,
                        "FAILED_FINAL",
                        now,
                    )
                    self.effect_repo.set_state(
                        conn, row.effect_id, "FAILED", now
                    )
                    self.delivery_repo.mark_failed_final(
                        conn, row.effect_id, now
                    )
                    self._mark_occurrence(
                        conn, row, "FAILED_FINAL", now
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
                    self._mark_occurrence(
                        conn, row, "NEEDS_RECONCILIATION", now
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
                self._mark_occurrence(
                    conn, row, "FAILED_FINAL", now
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
            self._mark_occurrence(
                conn, row, "NEEDS_RECONCILIATION", now
            )
            if row.purpose_id is not None and row.purpose_revision is not None:
                conn.execute(
                    """UPDATE purposes
                       SET state='NEEDS_RECONCILIATION',updated_at=?,
                           last_evaluated_at=?
                       WHERE purpose_id=? AND revision=?
                         AND state IN ('ACTIVE','WAITING')""",
                    (
                        now.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                        now.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                        row.purpose_id,
                        row.purpose_revision,
                    ),
                )
