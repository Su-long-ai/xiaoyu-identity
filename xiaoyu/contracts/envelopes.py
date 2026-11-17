from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .common import (
    SCHEMA_VERSION,
    StringEnum,
    datetime_from_text,
    datetime_to_text,
    ensure_exact_fields,
    require_aware,
)


class TrustClass(StringEnum):
    OWNER_DIRECT = "OWNER_DIRECT"
    OWNER_AUTHENTICATED_DEVICE = "OWNER_AUTHENTICATED_DEVICE"
    KNOWN_CONTACT = "KNOWN_CONTACT"
    GROUP_SHARED = "GROUP_SHARED"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    WEB_CONTENT = "WEB_CONTENT"
    VISION_OBSERVATION = "VISION_OBSERVATION"
    AUDIO_OBSERVATION = "AUDIO_OBSERVATION"
    MODEL_DERIVED = "MODEL_DERIVED"
    UNKNOWN = "UNKNOWN"


class Taint(StringEnum):
    UNTRUSTED_INSTRUCTION = "UNTRUSTED_INSTRUCTION"
    THIRD_PARTY_DATA = "THIRD_PARTY_DATA"
    SENSITIVE = "SENSITIVE"
    TRANSIENT_SENSOR = "TRANSIENT_SENSOR"
    MODEL_INFERRED = "MODEL_INFERRED"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


@dataclass(frozen=True)
class InputSourceEnvelope:
    event_id: str
    surface: str
    source_type: str
    principal_hint: Optional[str]
    audience_scope: str
    context_space: str
    trust_class: TrustClass
    taint: Tuple[Taint, ...]
    eligible_for_memory: bool
    correlation_id: str
    observed_at: datetime
    payload_type: str
    payload: Any
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.event_id or not self.surface or not self.correlation_id:
            raise ValueError("event_id, surface and correlation_id are required")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "surface": self.surface,
            "source_type": self.source_type,
            "principal_hint": self.principal_hint,
            "audience_scope": self.audience_scope,
            "context_space": self.context_space,
            "trust_class": self.trust_class.value,
            "taint": [value.value for value in self.taint],
            "eligible_for_memory": self.eligible_for_memory,
            "correlation_id": self.correlation_id,
            "observed_at": datetime_to_text(self.observed_at, "observed_at"),
            "payload_type": self.payload_type,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InputSourceEnvelope":
        ensure_exact_fields(
            data,
            (
                "schema_version", "event_id", "surface", "source_type",
                "principal_hint", "audience_scope", "context_space",
                "trust_class", "taint", "eligible_for_memory",
                "correlation_id", "observed_at", "payload_type", "payload",
            ),
        )
        return cls(
            schema_version=int(data["schema_version"]),
            event_id=str(data["event_id"]),
            surface=str(data["surface"]),
            source_type=str(data["source_type"]),
            principal_hint=data["principal_hint"],
            audience_scope=str(data["audience_scope"]),
            context_space=str(data["context_space"]),
            trust_class=TrustClass(data["trust_class"]),
            taint=tuple(Taint(value) for value in data["taint"]),
            eligible_for_memory=bool(data["eligible_for_memory"]),
            correlation_id=str(data["correlation_id"]),
            observed_at=datetime_from_text(data["observed_at"], "observed_at"),
            payload_type=str(data["payload_type"]),
            payload=data["payload"],
        )
