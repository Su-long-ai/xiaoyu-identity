from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from xiaoyu.contracts.common import StringEnum, require_aware
from xiaoyu.runtime.scheduler import PurposeScheduler


class PowerState(StringEnum):
    FOREGROUND = "FOREGROUND"
    BACKGROUND = "BACKGROUND"
    IDLE = "IDLE"
    SUSPENDING = "SUSPENDING"
    SUSPENDED = "SUSPENDED"
    RESUMING = "RESUMING"
    BATTERY_SAVER = "BATTERY_SAVER"
    AC_POWER = "AC_POWER"


@dataclass(frozen=True)
class ResumeReport:
    suspended_at: Optional[datetime]
    resumed_at: datetime
    reconciled_purposes: int


class PowerLifecycle:
    """Runtime power state; durable purpose correctness stays in the scheduler."""

    def __init__(self, scheduler: PurposeScheduler) -> None:
        self.scheduler = scheduler
        self.state = PowerState.FOREGROUND
        self.suspended_at: Optional[datetime] = None

    def suspend(self, at: Optional[datetime] = None) -> None:
        current = at or datetime.now(timezone.utc)
        require_aware(current, "suspend_at")
        self.state = PowerState.SUSPENDING
        self.suspended_at = current
        self.state = PowerState.SUSPENDED

    def resume(self, at: Optional[datetime] = None) -> ResumeReport:
        current = at or datetime.now(timezone.utc)
        require_aware(current, "resume_at")
        previous = self.suspended_at
        self.state = PowerState.RESUMING
        decisions = self.scheduler.reconcile_due(current)
        self.state = PowerState.FOREGROUND
        self.suspended_at = None
        return ResumeReport(previous, current, len(decisions))
