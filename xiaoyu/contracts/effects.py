from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .common import (
    SCHEMA_VERSION,
    StringEnum,
    copy_json_object,
    datetime_from_text,
    datetime_to_text,
    ensure_exact_fields,
    require_aware,
)


class EffectState(StringEnum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    QUEUED = "QUEUED"
    DISPATCHING = "DISPATCHING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


@dataclass(frozen=True)
class EffectIntent:
    effect_id: str
    intent_id: str
    purpose_id: Optional[str]
    actor_id: str
    action_class: str
    request: Dict[str, Any]
    idempotency_key: Optional[str]
    replayable: bool
    created_at: datetime
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "effect_id": self.effect_id,
            "intent_id": self.intent_id,
            "purpose_id": self.purpose_id,
            "actor_id": self.actor_id,
            "action_class": self.action_class,
            "request": copy_json_object(self.request),
            "idempotency_key": self.idempotency_key,
            "replayable": self.replayable,
            "created_at": datetime_to_text(self.created_at, "created_at"),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EffectIntent":
        ensure_exact_fields(data, (
            "schema_version", "effect_id", "intent_id", "purpose_id", "actor_id",
            "action_class", "request", "idempotency_key", "replayable", "created_at",
        ))
        return cls(
            schema_version=int(data["schema_version"]),
            effect_id=str(data["effect_id"]),
            intent_id=str(data["intent_id"]),
            purpose_id=data["purpose_id"],
            actor_id=str(data["actor_id"]),
            action_class=str(data["action_class"]),
            request=copy_json_object(data["request"]),
            idempotency_key=data["idempotency_key"],
            replayable=bool(data["replayable"]),
            created_at=datetime_from_text(data["created_at"], "created_at"),
        )
