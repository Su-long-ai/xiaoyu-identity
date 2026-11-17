from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .common import (
    SCHEMA_VERSION,
    StringEnum,
    copy_json_object,
    datetime_from_text,
    datetime_to_text,
    ensure_exact_fields,
    require_aware,
)


class ProviderLifecycle(StringEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRING = "RETIRING"
    SHUTDOWN = "SHUTDOWN"
    DISABLED = "DISABLED"


class IsolationMode(StringEnum):
    IN_PROCESS = "in_process"
    SIDECAR = "sidecar"
    WASM = "wasm"
    REMOTE = "remote"


@dataclass(frozen=True)
class CapabilityDescriptor:
    provider_id: str
    capability: str
    implementation_version: str
    contract_name: str
    contract_min_version: str
    contract_max_exclusive: str
    artifact_digest: Optional[str]
    descriptor_digest: str
    interface_digest: str
    tool_schema_digest: Optional[str]
    isolation: IsolationMode
    features: Dict[str, Any]
    data_classes: Tuple[str, ...]
    permissions_required: Tuple[str, ...]
    fallback_group: Optional[str]
    lifecycle: ProviderLifecycle
    resource_profile: Dict[str, Any]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "capability": self.capability,
            "implementation_version": self.implementation_version,
            "contract_name": self.contract_name,
            "contract_min_version": self.contract_min_version,
            "contract_max_exclusive": self.contract_max_exclusive,
            "artifact_digest": self.artifact_digest,
            "descriptor_digest": self.descriptor_digest,
            "interface_digest": self.interface_digest,
            "tool_schema_digest": self.tool_schema_digest,
            "isolation": self.isolation.value,
            "features": copy_json_object(self.features),
            "data_classes": list(self.data_classes),
            "permissions_required": list(self.permissions_required),
            "fallback_group": self.fallback_group,
            "lifecycle": self.lifecycle.value,
            "resource_profile": copy_json_object(self.resource_profile),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityDescriptor":
        ensure_exact_fields(data, (
            "schema_version", "provider_id", "capability", "implementation_version",
            "contract_name", "contract_min_version", "contract_max_exclusive",
            "artifact_digest", "descriptor_digest", "interface_digest", "tool_schema_digest",
            "isolation", "features", "data_classes", "permissions_required",
            "fallback_group", "lifecycle", "resource_profile",
        ))
        return cls(
            schema_version=int(data["schema_version"]),
            provider_id=str(data["provider_id"]),
            capability=str(data["capability"]),
            implementation_version=str(data["implementation_version"]),
            contract_name=str(data["contract_name"]),
            contract_min_version=str(data["contract_min_version"]),
            contract_max_exclusive=str(data["contract_max_exclusive"]),
            artifact_digest=data["artifact_digest"],
            descriptor_digest=str(data["descriptor_digest"]),
            interface_digest=str(data["interface_digest"]),
            tool_schema_digest=data["tool_schema_digest"],
            isolation=IsolationMode(data["isolation"]),
            features=copy_json_object(data["features"]),
            data_classes=tuple(str(v) for v in data["data_classes"]),
            permissions_required=tuple(str(v) for v in data["permissions_required"]),
            fallback_group=data["fallback_group"],
            lifecycle=ProviderLifecycle(data["lifecycle"]),
            resource_profile=copy_json_object(data["resource_profile"]),
        )


@dataclass(frozen=True)
class ProviderHealth:
    liveness: str
    readiness: str
    capability_health: Dict[str, str]
    reason: Optional[str]
    since: datetime
    retry_after_ms: Optional[int]
    details: Dict[str, Any]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_aware(self.since, "since")
        if self.retry_after_ms is not None and self.retry_after_ms < 0:
            raise ValueError("retry_after_ms cannot be negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "liveness": self.liveness,
            "readiness": self.readiness,
            "capability_health": dict(self.capability_health),
            "reason": self.reason,
            "since": datetime_to_text(self.since, "since"),
            "retry_after_ms": self.retry_after_ms,
            "details": copy_json_object(self.details),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderHealth":
        ensure_exact_fields(data, (
            "schema_version", "liveness", "readiness", "capability_health",
            "reason", "since", "retry_after_ms", "details",
        ))
        return cls(
            schema_version=int(data["schema_version"]),
            liveness=str(data["liveness"]),
            readiness=str(data["readiness"]),
            capability_health={str(k): str(v) for k, v in data["capability_health"].items()},
            reason=data["reason"],
            since=datetime_from_text(data["since"], "since"),
            retry_after_ms=data["retry_after_ms"],
            details=copy_json_object(data["details"]),
        )
