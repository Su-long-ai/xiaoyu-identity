from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .resource import ResourceMode


class PresenceState(str, Enum):
    SLEEPING = "SLEEPING"
    GAME_MINIMAL = "GAME_MINIMAL"
    ATTENTIVE = "ATTENTIVE"
    IDLE = "IDLE"
    QUIET = "QUIET"


@dataclass(frozen=True)
class PresenceFrame:
    state: PresenceState
    animation_key: str
    status_key: str
    next_tick_ms: int
    llm_required: bool = False


class AmbientPresenceEngine:
    """Deterministic presentation state; never writes semantic authority."""

    def tick(
        self,
        *,
        mode: ResourceMode,
        user_active: bool,
        window_visible: bool,
        llm_available: bool,
    ) -> PresenceFrame:
        mode = ResourceMode(mode)
        if mode is ResourceMode.SLEEP:
            return PresenceFrame(
                PresenceState.SLEEPING,
                "sleep_breathe",
                "sleep",
                5000,
            )
        if mode is ResourceMode.GAME:
            return PresenceFrame(
                PresenceState.GAME_MINIMAL,
                "minimal_idle",
                "game",
                4000,
            )
        if user_active and window_visible:
            return PresenceFrame(
                PresenceState.ATTENTIVE,
                "attentive_idle",
                "present",
                1500,
            )
        if mode is ResourceMode.ECO:
            return PresenceFrame(
                PresenceState.QUIET,
                "quiet_idle",
                "eco",
                3500,
            )
        return PresenceFrame(
            PresenceState.IDLE,
            "ambient_idle",
            "idle",
            2500,
        )
