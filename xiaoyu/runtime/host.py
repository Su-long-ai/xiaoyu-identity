from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from xiaoyu.contracts import (
    CapabilityDescriptor,
    ProviderHealth,
    ProviderLifecycle,
)
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.provider_execution import (
    ProviderExecutionRegistry,
)
from xiaoyu.runtime.provider_registry import ProviderDescriptor
from xiaoyu.runtime.resource_broker import (
    ResourceBroker,
    ResourceLease,
)


@dataclass(frozen=True)
class RuntimeAdmission:
    allowed: bool
    provider_id: str
    capability: str
    reasons: Tuple[str, ...]
    descriptor: Optional[CapabilityDescriptor]
    health: Optional[ProviderHealth]


class RuntimeHost:
    """Composition boundary for replaceable capability providers.

    Durable descriptor/lifecycle/health state lives in ProviderExecutionRegistry.
    Attempt-level audience/privacy/session policy stays in provider_registry.
    RuntimeHost only composes those provider-facing contracts; it owns no XiaoYu
    identity, memory, relationship, Purpose or Effect authority.
    """

    DEFAULT_CONTRACTS = {
        "openai.chat.completions": "1.0",
    }

    def __init__(
        self,
        db: Database,
        *,
        supported_contracts: Optional[Mapping[str, str]] = None,
        registry=None,
        resource_broker: Optional[ResourceBroker] = None,
    ) -> None:
        self.db = db
        self.registry = registry or ProviderExecutionRegistry(db)
        self.supported_contracts = dict(
            supported_contracts or self.DEFAULT_CONTRACTS
        )
        self.resource_broker = resource_broker

    @staticmethod
    def _version(value: str) -> tuple[int, ...]:
        parts = str(value).strip().split(".")
        if not parts or any(not part.isdigit() for part in parts):
            raise ValueError("contract version must be numeric dotted version")
        return tuple(int(part) for part in parts)

    @classmethod
    def _version_in_range(
        cls,
        version: str,
        minimum: str,
        maximum_exclusive: str,
    ) -> bool:
        current = cls._version(version)
        lower = cls._version(minimum)
        upper = cls._version(maximum_exclusive)
        width = max(len(current), len(lower), len(upper))
        current += (0,) * (width - len(current))
        lower += (0,) * (width - len(lower))
        upper += (0,) * (width - len(upper))
        return lower <= current < upper

    @staticmethod
    def _digest_shape(value: Optional[str], *, optional: bool = False) -> bool:
        if value is None:
            return optional
        text = str(value)
        if not text.startswith("sha256:"):
            return False
        digest = text[len("sha256:"):]
        return len(digest) == 64 and all(
            ch in "0123456789abcdef" for ch in digest.lower()
        )

    def descriptor_reasons(
        self,
        descriptor: CapabilityDescriptor,
    ) -> tuple[str, ...]:
        reasons = []
        supported = self.supported_contracts.get(
            descriptor.contract_name
        )
        if supported is None:
            reasons.append("unsupported_contract")
        else:
            try:
                compatible = self._version_in_range(
                    supported,
                    descriptor.contract_min_version,
                    descriptor.contract_max_exclusive,
                )
            except ValueError:
                compatible = False
            if not compatible:
                reasons.append("contract_version_incompatible")

        if not self._digest_shape(
            descriptor.descriptor_digest
        ):
            reasons.append("descriptor_digest_invalid")
        if not self._digest_shape(
            descriptor.interface_digest
        ):
            reasons.append("interface_digest_invalid")
        if not self._digest_shape(
            descriptor.artifact_digest,
            optional=True,
        ):
            reasons.append("artifact_digest_invalid")
        if not self._digest_shape(
            descriptor.tool_schema_digest,
            optional=True,
        ):
            reasons.append("tool_schema_digest_invalid")

        if not descriptor.provider_id:
            reasons.append("provider_id_missing")
        if not descriptor.capability:
            reasons.append("capability_missing")
        if not descriptor.data_classes:
            reasons.append("data_classes_missing")
        return tuple(reasons)

    def register_provider(
        self,
        descriptor: CapabilityDescriptor,
        health: ProviderHealth,
    ) -> None:
        reasons = self.descriptor_reasons(descriptor)
        if reasons:
            raise ValueError(
                "provider descriptor rejected: " + ",".join(reasons)
            )
        self.registry.register(descriptor, health)


    def reserve_provider_resources(
        self,
        provider_id: str,
        *,
        lease_id: str,
        priority: int = 50,
        preemptible: bool = True,
    ) -> ResourceLease:
        if self.resource_broker is None:
            raise RuntimeError("RuntimeHost has no ResourceBroker")
        snapshot = self.registry.snapshot(provider_id)
        if snapshot is None:
            raise KeyError("provider not registered: %s" % provider_id)
        descriptor, _ = snapshot
        request = self.resource_broker.request_from_descriptor(
            descriptor,
            priority=priority,
            preemptible=preemptible,
        )
        return self.resource_broker.reserve(lease_id, request)

    def release_provider_resources(self, lease_id: str) -> bool:
        if self.resource_broker is None:
            return False
        return self.resource_broker.release(lease_id)

    @staticmethod
    def _health_ready(health: ProviderHealth) -> bool:
        return (
            str(health.readiness).upper() == "READY"
            and str(health.liveness).upper()
            not in {"DOWN", "DEAD", "UNAVAILABLE"}
        )

    def admit_provider(
        self,
        runtime_descriptor: ProviderDescriptor,
        *,
        required_data_class: Optional[str] = None,
        required_features: tuple[str, ...] = (),
        live_health: Optional[ProviderHealth] = None,
    ) -> RuntimeAdmission:
        snapshot = self.registry.snapshot(
            runtime_descriptor.provider_id
        )
        if snapshot is None:
            return RuntimeAdmission(
                False,
                runtime_descriptor.provider_id,
                runtime_descriptor.capability,
                ("provider_not_registered",),
                None,
                None,
            )
        descriptor, stored_health = snapshot
        reasons = list(self.descriptor_reasons(descriptor))

        if descriptor.lifecycle != ProviderLifecycle.ACTIVE:
            reasons.append("provider_lifecycle_not_active")
        if descriptor.capability != runtime_descriptor.capability:
            reasons.append("capability_changed")
        if (
            descriptor.descriptor_digest
            != runtime_descriptor.descriptor_digest
        ):
            reasons.append("descriptor_digest_changed")

        features = descriptor.features
        if (
            features.get("capability_digest")
            != runtime_descriptor.capability_digest
        ):
            reasons.append("capability_digest_changed")
        if (
            features.get("implementation_digest")
            != runtime_descriptor.implementation_digest
        ):
            reasons.append("implementation_digest_changed")
        if (
            features.get("endpoint_scope")
            != runtime_descriptor.endpoint_scope
        ):
            reasons.append("endpoint_scope_changed")

        runtime_classes = {
            privacy.value
            for privacy in runtime_descriptor.privacy_classes
        }
        registered_classes = {
            str(value).upper()
            for value in descriptor.data_classes
        }
        if not runtime_classes.issubset(registered_classes):
            reasons.append("runtime_data_classes_not_registered")
        if (
            required_data_class is not None
            and str(required_data_class).upper()
            not in registered_classes
        ):
            reasons.append("required_data_class_not_registered")

        for feature in required_features:
            if not bool(features.get(feature)):
                reasons.append("feature_missing:" + str(feature))

        health = live_health or stored_health
        if not self._health_ready(stored_health):
            reasons.append("stored_provider_not_ready")
        if (
            live_health is not None
            and not self._health_ready(live_health)
        ):
            reasons.append("live_provider_not_ready")

        return RuntimeAdmission(
            allowed=not reasons,
            provider_id=runtime_descriptor.provider_id,
            capability=runtime_descriptor.capability,
            reasons=tuple(reasons),
            descriptor=descriptor,
            health=health,
        )
