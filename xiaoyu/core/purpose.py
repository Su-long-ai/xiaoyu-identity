from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from xiaoyu.contracts.common import StringEnum, require_aware


class PurposeState(StringEnum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class PurposeKind(StringEnum):
    REMINDER = "REMINDER"
    BOUNDED_WATCH = "BOUNDED_WATCH"
    FOLLOW_UP = "FOLLOW_UP"
    TASK_COMPLETION_DELIVERY = "TASK_COMPLETION_DELIVERY"


class PurposeOwner(StringEnum):
    USER = "USER"
    XIAOYU = "XIAOYU"
    SHARED = "SHARED"


class MissPolicy(StringEnum):
    DELIVER_LATE = "DELIVER_LATE"
    SKIP_IF_MISSED = "SKIP_IF_MISSED"
    RESCHEDULE = "RESCHEDULE"
    ASK = "ASK"
    RECONCILE = "RECONCILE"


@dataclass(frozen=True)
class Purpose:
    purpose_id: str
    identity_id: str
    owner_type: PurposeOwner
    owner_id: Optional[str]
    state: PurposeState
    kind: PurposeKind
    source_event_id: str
    payload: Dict[str, Any]
    scheduled_wall_time: Optional[str]
    timezone_name: Optional[str]
    resolved_utc_time: Optional[datetime]
    miss_policy: MissPolicy
    quiet_class: str = "NORMAL"
    duplicate_key: Optional[str] = None
    last_evaluated_at: Optional[datetime] = None
    revision: int = 1
    auto_reschedule_count: int = 0

    def __post_init__(self) -> None:
        if self.resolved_utc_time is not None:
            require_aware(self.resolved_utc_time, "resolved_utc_time")
        if self.last_evaluated_at is not None:
            require_aware(self.last_evaluated_at, "last_evaluated_at")
        if self.revision < 1:
            raise ValueError("purpose revision must be >= 1")
        if self.auto_reschedule_count < 0:
            raise ValueError("auto_reschedule_count must be >= 0")
        if (self.scheduled_wall_time is None) != (self.timezone_name is None):
            raise ValueError(
                "scheduled_wall_time and timezone_name must be set together"
            )


def resolve_wall_time(local_time: datetime, timezone_name: str) -> datetime:
    """Resolve a valid offset-aware local wall time, rejecting DST gaps."""
    require_aware(local_time, "local_time")
    zone = ZoneInfo(timezone_name)
    resolved = local_time.astimezone(timezone.utc)
    round_trip = resolved.astimezone(zone)
    if (
        round_trip.replace(tzinfo=None)
        != local_time.replace(tzinfo=None)
        or round_trip.utcoffset() != local_time.utcoffset()
    ):
        raise ValueError(
            "local_time is nonexistent or offset does not match timezone"
        )
    return resolved
