from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .common import (
    SCHEMA_VERSION,
    copy_json_object,
    datetime_from_text,
    datetime_to_text,
    ensure_exact_fields,
    require_aware,
)


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    actor_type: str
    implementation_digest: Optional[str]
    provider_id: Optional[str]
    device_id: Optional[str]
    trust_tier: str
    attestation_state: Optional[str] = None
    authorization_digest: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "implementation_digest": self.implementation_digest,
            "provider_id": self.provider_id,
            "device_id": self.device_id,
            "trust_tier": self.trust_tier,
            "attestation_state": self.attestation_state,
            "authorization_digest": self.authorization_digest,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActorContext":
        ensure_exact_fields(data, (
            "schema_version", "actor_id", "actor_type", "implementation_digest",
            "provider_id", "device_id", "trust_tier", "attestation_state",
            "authorization_digest",
        ))
        return cls(**data)


@dataclass(frozen=True)
class Delegation:
    delegation_id: str
    issued_by_principal: str
    issued_to_actor: str
    purpose_id: Optional[str]
    action_classes: Tuple[str, ...]
    resources: Tuple[str, ...]
    max_effect: Dict[str, Any]
    valid_from: datetime
    expires_at: Optional[datetime]
    revocable: bool
    revoked_at: Optional[datetime] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.valid_from, "valid_from")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
            if self.expires_at < self.valid_from:
                raise ValueError("expires_at cannot be earlier than valid_from")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, "revoked_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "delegation_id": self.delegation_id,
            "issued_by_principal": self.issued_by_principal,
            "issued_to_actor": self.issued_to_actor,
            "purpose_id": self.purpose_id,
            "action_classes": list(self.action_classes),
            "resources": list(self.resources),
            "max_effect": copy_json_object(self.max_effect),
            "valid_from": datetime_to_text(self.valid_from, "valid_from"),
            "expires_at": None if self.expires_at is None else datetime_to_text(self.expires_at, "expires_at"),
            "revocable": self.revocable,
            "revoked_at": None if self.revoked_at is None else datetime_to_text(self.revoked_at, "revoked_at"),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Delegation":
        ensure_exact_fields(data, (
            "schema_version", "delegation_id", "issued_by_principal", "issued_to_actor",
            "purpose_id", "action_classes", "resources", "max_effect",
            "valid_from", "expires_at", "revocable", "revoked_at",
        ))
        expires = data["expires_at"]
        return cls(
            schema_version=int(data["schema_version"]),
            delegation_id=str(data["delegation_id"]),
            issued_by_principal=str(data["issued_by_principal"]),
            issued_to_actor=str(data["issued_to_actor"]),
            purpose_id=data["purpose_id"],
            action_classes=tuple(str(v) for v in data["action_classes"]),
            resources=tuple(str(v) for v in data["resources"]),
            max_effect=copy_json_object(data["max_effect"]),
            valid_from=datetime_from_text(data["valid_from"], "valid_from"),
            expires_at=None if expires is None else datetime_from_text(expires, "expires_at"),
            revocable=bool(data["revocable"]),
            revoked_at=None if data["revoked_at"] is None else datetime_from_text(data["revoked_at"], "revoked_at"),
        )
