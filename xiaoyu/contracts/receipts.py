from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .common import (
    SCHEMA_VERSION,
    copy_json_object,
    datetime_from_text,
    datetime_to_text,
    ensure_exact_fields,
    require_aware,
)


@dataclass(frozen=True)
class ActionReceipt:
    receipt_id: str
    effect_id: str
    actor_id: str
    provider_id: Optional[str]
    authorization_decision_id: str
    request_digest: str
    result_class: str
    result_digest: Optional[str]
    external_ref: Optional[str]
    observed_at: datetime
    metadata: Dict[str, Any]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "effect_id": self.effect_id,
            "actor_id": self.actor_id,
            "provider_id": self.provider_id,
            "authorization_decision_id": self.authorization_decision_id,
            "request_digest": self.request_digest,
            "result_class": self.result_class,
            "result_digest": self.result_digest,
            "external_ref": self.external_ref,
            "observed_at": datetime_to_text(self.observed_at, "observed_at"),
            "metadata": copy_json_object(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionReceipt":
        ensure_exact_fields(data, (
            "schema_version", "receipt_id", "effect_id", "actor_id", "provider_id",
            "authorization_decision_id", "request_digest", "result_class", "result_digest",
            "external_ref", "observed_at", "metadata",
        ))
        return cls(
            schema_version=int(data["schema_version"]),
            receipt_id=str(data["receipt_id"]),
            effect_id=str(data["effect_id"]),
            actor_id=str(data["actor_id"]),
            provider_id=data["provider_id"],
            authorization_decision_id=str(data["authorization_decision_id"]),
            request_digest=str(data["request_digest"]),
            result_class=str(data["result_class"]),
            result_digest=data["result_digest"],
            external_ref=data["external_ref"],
            observed_at=datetime_from_text(data["observed_at"], "observed_at"),
            metadata=copy_json_object(data["metadata"]),
        )
