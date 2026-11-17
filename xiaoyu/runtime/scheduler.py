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
    occurrence_id: Optional[str] = None


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
        current = (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
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
                due_at = due_at.astimezone(timezone.utc)
                lateness = max(
                    0.0, (current - due_at).total_seconds()
                )

                # Normal due execution is not a "miss".  Miss policy becomes
                # relevant only after the configured grace window.
                if lateness <= late_threshold_s:
                    occurrence_id = self.repository.activate_occurrence(
                        conn, purpose, current
                    )
                    decisions.append(
                        PurposeDecision(
                            purpose.purpose_id,
                            PurposeState.SCHEDULED,
                            PurposeState.ACTIVE,
                            "DUE_ON_TIME",
                            occurrence_id,
                        )
                    )
                    continue

                policy = purpose.miss_policy
                if policy == MissPolicy.DELIVER_LATE:
                    occurrence_id = self.repository.activate_occurrence(
                        conn, purpose, current
                    )
                    decisions.append(
                        PurposeDecision(
                            purpose.purpose_id,
                            PurposeState.SCHEDULED,
                            PurposeState.ACTIVE,
                            "MISSED_DELIVER_LATE",
                            occurrence_id,
                        )
                    )
                    continue

                if policy == MissPolicy.SKIP_IF_MISSED:
                    miss_after = float(
                        purpose.payload.get(
                            "miss_after_seconds",
                            late_threshold_s,
                        )
                    )
                    if lateness > miss_after:
                        new_state = PurposeState.EXPIRED
                        reason = "MISSED_WINDOW"
                    else:
                        occurrence_id = (
                            self.repository.activate_occurrence(
                                conn, purpose, current
                            )
                        )
                        decisions.append(
                            PurposeDecision(
                                purpose.purpose_id,
                                PurposeState.SCHEDULED,
                                PurposeState.ACTIVE,
                                "WITHIN_MISS_WINDOW",
                                occurrence_id,
                            )
                        )
                        continue

                elif policy == MissPolicy.ASK:
                    new_state = PurposeState.WAITING
                    reason = "MISSED_REQUIRES_OWNER_DECISION"

                elif policy == MissPolicy.RECONCILE:
                    new_state = PurposeState.NEEDS_RECONCILIATION
                    reason = "MISSED_REQUIRES_RECONCILIATION"

                elif policy == MissPolicy.RESCHEDULE:
                    seconds = purpose.payload.get(
                        "reschedule_seconds"
                    )
                    if (
                        isinstance(seconds, bool)
                        or not isinstance(seconds, (int, float))
                        or seconds <= 0
                    ):
                        new_state = PurposeState.NEEDS_RECONCILIATION
                        reason = "RESCHEDULE_RULE_MISSING"
                    else:
                        new_due = current + timedelta(
                            seconds=float(seconds)
                        )
                        zone = (
                            ZoneInfo(purpose.timezone_name)
                            if purpose.timezone_name
                            else timezone.utc
                        )
                        wall = new_due.astimezone(zone).isoformat(
                            timespec="minutes"
                        )
                        changed = self.repository.reschedule(
                            conn,
                            purpose.purpose_id,
                            wall,
                            purpose.timezone_name or "UTC",
                            new_due,
                            current,
                        )
                        if changed:
                            decisions.append(
                                PurposeDecision(
                                    purpose.purpose_id,
                                    PurposeState.SCHEDULED,
                                    PurposeState.SCHEDULED,
                                    "MISSED_RESCHEDULED",
                                )
                            )
                        continue
                else:
                    new_state = PurposeState.NEEDS_RECONCILIATION
                    reason = "UNKNOWN_MISS_POLICY"

                if self.repository.transition(
                    conn,
                    purpose.purpose_id,
                    (PurposeState.SCHEDULED,),
                    new_state,
                    current,
                ):
                    decisions.append(
                        PurposeDecision(
                            purpose.purpose_id,
                            PurposeState.SCHEDULED,
                            new_state,
                            reason,
                        )
                    )

            return decisions
