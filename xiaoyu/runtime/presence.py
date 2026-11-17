from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from xiaoyu.runtime.resource_broker import ResourceMode


class PresenceState(str, Enum):
    ATTENTIVE = "ATTENTIVE"
    BUSY = "BUSY"
    IDLE = "IDLE"
    QUIET = "QUIET"
    RESTING = "RESTING"
    SLEEPING = "SLEEPING"


@dataclass(frozen=True)
class PresenceFrame:
    state: PresenceState
    motion_class: str
    attention: float
    reason: str
    durable_mutation: bool = False
    narrative_claim: str | None = None


class AmbientPresenceEngine:
    """Deterministic presentation-only companion presence.

    It describes current UI/body presentation from observable runtime state. It
    never invents off-screen activity and cannot write persona/memory/relationship
    authority.
    """

    def __init__(
        self,
        *,
        quiet_after_s: float = 90.0,
        rest_after_s: float = 600.0,
    ) -> None:
        if quiet_after_s < 0 or rest_after_s < quiet_after_s:
            raise ValueError("invalid presence idle thresholds")
        self.quiet_after_s = float(quiet_after_s)
        self.rest_after_s = float(rest_after_s)

    def frame(
        self,
        *,
        mode: ResourceMode,
        idle_seconds: float,
        user_active: bool,
        active_work: bool,
    ) -> PresenceFrame:
        idle = max(0.0, float(idle_seconds))
        if ResourceMode(mode) == ResourceMode.SLEEP:
            return PresenceFrame(
                PresenceState.SLEEPING,
                "minimal_breath",
                0.0,
                "runtime_sleep_mode",
            )
        if active_work:
            return PresenceFrame(
                PresenceState.BUSY,
                "focused_activity",
                0.7 if user_active else 0.45,
                "runtime_has_active_work",
            )
        if user_active:
            return PresenceFrame(
                PresenceState.ATTENTIVE,
                "orient_to_user",
                1.0,
                "user_is_active",
            )
        if idle >= self.rest_after_s:
            return PresenceFrame(
                PresenceState.RESTING,
                "slow_idle",
                0.15,
                "long_idle",
            )
        if idle >= self.quiet_after_s:
            return PresenceFrame(
                PresenceState.QUIET,
                "subtle_idle",
                0.25,
                "quiet_idle",
            )
        return PresenceFrame(
            PresenceState.IDLE,
            "normal_idle",
            0.35,
            "short_idle",
        )
