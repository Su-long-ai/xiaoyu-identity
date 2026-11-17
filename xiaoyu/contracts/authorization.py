from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .common import SCHEMA_VERSION, StringEnum, copy_json_object, ensure_exact_fields


class AuthorizationDecision(StringEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class RiskTier(StringEnum):
    T0_OBSERVE = "T0_OBSERVE"
    T1_LOCAL_REVERSIBLE = "T1_LOCAL_REVERSIBLE"
    T2_OWNER_STATE_MUTATION = "T2_OWNER_STATE_MUTATION"
    T3_EXTERNAL_OR_IRREVERSIBLE = "T3_EXTERNAL_OR_IRREVERSIBLE"


@dataclass(frozen=True)
class ActionRequest:
    action_class: str
    risk_tier: RiskTier
    parameters: Dict[str, Any]
    replayable: bool
    idempotency_key: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action_class": self.action_class,
            "risk_tier": self.risk_tier.value,
            "parameters": copy_json_object(self.parameters),
            "replayable": self.replayable,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionRequest":
        ensure_exact_fields(data, (
            "schema_version", "action_class", "risk_tier", "parameters",
            "replayable", "idempotency_key",
        ))
        return cls(
            schema_version=int(data["schema_version"]),
            action_class=str(data["action_class"]),
            risk_tier=RiskTier(data["risk_tier"]),
            parameters=copy_json_object(data["parameters"]),
            replayable=bool(data["replayable"]),
            idempotency_key=data["idempotency_key"],
        )


@dataclass(frozen=True)
class ResourceRef:
    kind: str
    identifier: str
    attributes: Dict[str, Any]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "identifier": self.identifier,
            "attributes": copy_json_object(self.attributes),
        }


@dataclass(frozen=True)
class AuthorizationContext:
    context_space: str
    audience_scope: str
    surface: str
    metadata: Dict[str, Any]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_space": self.context_space,
            "audience_scope": self.audience_scope,
            "surface": self.surface,
            "metadata": copy_json_object(self.metadata),
        }
