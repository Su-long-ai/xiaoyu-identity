from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from xiaoyu.core.purpose import MissPolicy, PurposeState
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.purposes import PurposeRepository


@dataclass(frozen=True)
class PurposeDecision:
    purpose_id: str
    previous_state: PurposeState
    new_state: PurposeState
    reason: str


class PurposeScheduler:
    def __init__(
        self,
        db: Database,
        identity_id: str,
        repository=None,
    ) -> None:
        self.db = db
        self.identity_id = identity_id
        self.repository = repository or PurposeRepository()

    def reconcile_due(
        self,
        now: Optional[datetime] = None,
        *,
        late_threshold_s: float = 60.0,
        limit: int = 100,
    ) -> List[PurposeDecision]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("scheduler time must be timezone-aware")
        with self.db.transaction(immediate=True) as conn:
            due = self.repository.list_due(
                conn, self.identity_id, current, limit
            )
            decisions: List[PurposeDecision] = []
            for purpose in due:
                due_at = purpose.resolved_utc_time
                if due_at is None:
                    continue
                lateness = max(
                    0.0, (current - due_at).total_seconds()
                )
                new_state, reason, new_due = self._decide(
                    purpose.miss_policy,
                    purpose.payload,
                    current,
                    lateness,
                    late_threshold_s,
                )
                changed = self.repository.transition(
                    conn,
                    purpose.purpose_id,
                    (PurposeState.SCHEDULED,),
                    new_state,
                    current,
                    resolved_utc_time=new_due,
                    scheduled_wall_time=(
                        new_due.astimezone(
                            ZoneInfo(purpose.timezone_name)
                            if purpose.timezone_name
                            else timezone.utc
                        ).isoformat(timespec="minutes")
                        if new_due is not None
                        else None
                    ),
                )
                if changed:
                    decisions.append(
                        PurposeDecision(
                            purpose.purpose_id,
                            PurposeState.SCHEDULED,
                            new_state,
                            reason,
                        )
                    )
            return decisions

    @staticmethod
    def _decide(
        policy,
        payload,
        current,
        lateness,
        threshold,
    ):
        if policy == MissPolicy.DELIVER_LATE:
            return (
                PurposeState.ACTIVE,
                "DUE_OR_LATE_DELIVERY",
                None,
            )
        if policy == MissPolicy.SKIP_IF_MISSED:
            if lateness > float(
                payload.get("miss_after_seconds", threshold)
            ):
                return (
                    PurposeState.EXPIRED,
                    "MISSED_WINDOW",
                    None,
                )
            return (
                PurposeState.ACTIVE,
                "WITHIN_MISS_WINDOW",
                None,
            )
        if policy == MissPolicy.ASK:
            return (
                PurposeState.WAITING,
                "MISSED_REQUIRES_OWNER_DECISION",
                None,
            )
        if policy == MissPolicy.RECONCILE:
            return (
                PurposeState.NEEDS_RECONCILIATION,
                "MISSED_REQUIRES_RECONCILIATION",
                None,
            )
        if policy == MissPolicy.RESCHEDULE:
            seconds = payload.get("reschedule_seconds")
            if isinstance(seconds, (int, float)) and seconds > 0:
                return (
                    PurposeState.SCHEDULED,
                    "RESCHEDULED",
                    current + timedelta(seconds=float(seconds)),
                )
            return (
                PurposeState.NEEDS_RECONCILIATION,
                "RESCHEDULE_RULE_MISSING",
                None,
            )
        return (
            PurposeState.NEEDS_RECONCILIATION,
            "UNKNOWN_MISS_POLICY",
            None,
        )
