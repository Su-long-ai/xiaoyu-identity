from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Tuple

from xiaoyu.contracts import (
    CapabilityDescriptor,
    ProviderHealth,
    ProviderLifecycle,
)
from xiaoyu.contracts.common import canonical_json, datetime_to_text
from xiaoyu.persistence import Database


class PrivacyClass(str, Enum):
    PUBLIC = "PUBLIC"
    OWNER_PRIVATE = "OWNER_PRIVATE"
    LOCAL_ONLY = "LOCAL_ONLY"
    SHARED = "SHARED"


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    capability: str
    descriptor_digest: str
    capability_digest: str
    implementation_digest: str
    endpoint_scope: str
    privacy_classes: Tuple[PrivacyClass, ...]
    session_mode: str = "STATELESS"


@dataclass(frozen=True)
class ProviderAttemptContext:
    identity_id: str
    principal_id: str
    audience_scope: str
    context_space: str
    context_generation: str
    provider_id: str
    required_capability: str
    required_privacy_class: PrivacyClass
    provider_descriptor_digest: str
    provider_capability_digest: str
    provider_implementation_digest: str
    expected_descriptor_digest: Optional[str] = None
    expected_capability_digest: Optional[str] = None
    authorization_digest: Optional[str] = None
    tool_result_digest: Optional[str] = None
    tool_implementation_digest: Optional[str] = None
    tool_schema_digest: Optional[str] = None
    source_contains_private_tool_result: bool = False


@dataclass(frozen=True)
class ProviderEligibility:
    allowed: bool
    reasons: Tuple[str, ...]
    provider_id: str
    session_namespace: str
    descriptor_digest: str
    capability_digest: str


@dataclass(frozen=True)
class ProviderFallbackAudit:
    provider_id: str
    allowed: bool
    reasons: Tuple[str, ...]
    session_namespace: str
    context_generation: str
    descriptor_digest: str
    capability_digest: str


AUDIENCE_RESET_COMPONENTS = (
    "private_retrieval",
    "private_profile",
    "cached_context",
    "provider_session_kv",
    "tool_delegations",
    "retained_messages",
    "surface_state",
)


@dataclass(frozen=True)
class AudienceResetDecision:
    required: bool
    clear_components: Tuple[str, ...]
    reasons: Tuple[str, ...]


def audience_reset_decision(
    previous: ProviderAttemptContext,
    current: ProviderAttemptContext,
) -> AudienceResetDecision:
    reasons = []
    for field in (
        "identity_id",
        "principal_id",
        "audience_scope",
        "context_space",
    ):
        if getattr(previous, field) != getattr(current, field):
            reasons.append(field + "_changed")
    if reasons:
        return AudienceResetDecision(
            required=True,
            clear_components=AUDIENCE_RESET_COMPONENTS,
            reasons=tuple(reasons),
        )
    return AudienceResetDecision(False, (), ())


def stable_digest(
    value: Mapping[str, Any] | Dict[str, Any],
) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def provider_session_namespace(
    context: ProviderAttemptContext,
) -> str:
    return stable_digest(
        {
            "identity_id": context.identity_id,
            "principal_id": context.principal_id,
            "audience_scope": context.audience_scope,
            "context_space": context.context_space,
            "context_generation": context.context_generation,
            "provider_id": context.provider_id,
            "provider_descriptor_digest":
                context.provider_descriptor_digest,
            "provider_capability_digest":
                context.provider_capability_digest,
            "provider_implementation_digest":
                context.provider_implementation_digest,
            "authorization_digest": context.authorization_digest,
            "tool_result_digest": context.tool_result_digest,
            "tool_implementation_digest":
                context.tool_implementation_digest,
            "tool_schema_digest": context.tool_schema_digest,
        }
    )


def _effective_privacy(
    context: ProviderAttemptContext,
) -> PrivacyClass:
    if context.source_contains_private_tool_result:
        return PrivacyClass.OWNER_PRIVATE
    return context.required_privacy_class


def _readiness_value(health: ProviderHealth) -> str:
    value = health.readiness
    return str(getattr(value, "value", value)).upper()


def evaluate_provider(
    descriptor: ProviderDescriptor,
    context: ProviderAttemptContext,
    health: Optional[ProviderHealth] = None,
) -> ProviderEligibility:
    reasons = []
    if descriptor.provider_id != context.provider_id:
        reasons.append("provider_id_mismatch")
    if descriptor.capability != context.required_capability:
        reasons.append("capability_mismatch")
    if (
        descriptor.descriptor_digest
        != context.provider_descriptor_digest
    ):
        reasons.append("attempt_descriptor_mismatch")
    if (
        descriptor.capability_digest
        != context.provider_capability_digest
    ):
        reasons.append("attempt_capability_digest_mismatch")
    if (
        descriptor.implementation_digest
        != context.provider_implementation_digest
    ):
        reasons.append("attempt_implementation_digest_mismatch")

    privacy = _effective_privacy(context)
    if privacy not in descriptor.privacy_classes:
        reasons.append("privacy_class_ineligible")
    if (
        privacy is PrivacyClass.LOCAL_ONLY
        and descriptor.endpoint_scope != "LOCAL"
    ):
        reasons.append("local_only_requires_local_provider")

    audience = str(context.audience_scope or "").upper()
    principal = str(context.principal_id or "").lower()
    context_space = str(context.context_space or "").upper()
    if privacy is PrivacyClass.OWNER_PRIVATE:
        if audience not in {"PRIVATE", "OWNER_PRIVATE"}:
            reasons.append("owner_private_audience_mismatch")
        if principal in {"guest", "unknown", "group", "shared"}:
            reasons.append("owner_private_principal_mismatch")
        if context_space in {"SHARED", "GROUP", "GUEST"}:
            reasons.append("owner_private_context_space_mismatch")

    if (
        context.expected_descriptor_digest is not None
        and context.expected_descriptor_digest
        != descriptor.descriptor_digest
    ):
        reasons.append("descriptor_digest_changed")
    if (
        context.expected_capability_digest is not None
        and context.expected_capability_digest
        != descriptor.capability_digest
    ):
        reasons.append("capability_digest_changed")

    if health is not None and _readiness_value(health) != "READY":
        reasons.append("provider_not_ready")

    return ProviderEligibility(
        allowed=not reasons,
        reasons=tuple(reasons),
        provider_id=descriptor.provider_id,
        session_namespace=provider_session_namespace(context),
        descriptor_digest=descriptor.descriptor_digest,
        capability_digest=descriptor.capability_digest,
    )


def fallback_audit(
    context: ProviderAttemptContext,
    eligibility: ProviderEligibility,
) -> ProviderFallbackAudit:
    return ProviderFallbackAudit(
        provider_id=eligibility.provider_id,
        allowed=eligibility.allowed,
        reasons=eligibility.reasons,
        session_namespace=eligibility.session_namespace,
        context_generation=context.context_generation,
        descriptor_digest=eligibility.descriptor_digest,
        capability_digest=eligibility.capability_digest,
    )


class ProviderRegistry:
    """Durable execution-facing provider descriptor/lifecycle registry."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def register(
        self,
        descriptor: CapabilityDescriptor,
        health: ProviderHealth,
        updated_at: Optional[datetime] = None,
    ) -> None:
        current = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO provider_registry(
                       provider_id,capability,descriptor_json,artifact_digest,
                       descriptor_digest,interface_digest,tool_schema_digest,
                       lifecycle_state,health_state_json,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(provider_id) DO UPDATE SET
                       capability=excluded.capability,
                       descriptor_json=excluded.descriptor_json,
                       artifact_digest=excluded.artifact_digest,
                       descriptor_digest=excluded.descriptor_digest,
                       interface_digest=excluded.interface_digest,
                       tool_schema_digest=excluded.tool_schema_digest,
                       lifecycle_state=excluded.lifecycle_state,
                       health_state_json=excluded.health_state_json,
                       updated_at=excluded.updated_at""",
                (
                    descriptor.provider_id,
                    descriptor.capability,
                    canonical_json(descriptor.to_dict()),
                    descriptor.artifact_digest,
                    descriptor.descriptor_digest,
                    descriptor.interface_digest,
                    descriptor.tool_schema_digest,
                    descriptor.lifecycle.value,
                    canonical_json(health.to_dict()),
                    datetime_to_text(current, "updated_at"),
                ),
            )

    def update_health(
        self,
        provider_id: str,
        health: ProviderHealth,
        updated_at: Optional[datetime] = None,
    ) -> bool:
        current = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            cur = conn.execute(
                """UPDATE provider_registry
                   SET health_state_json=?,updated_at=?
                   WHERE provider_id=?""",
                (
                    canonical_json(health.to_dict()),
                    datetime_to_text(current, "updated_at"),
                    provider_id,
                ),
            )
            return cur.rowcount == 1

    def set_lifecycle(
        self,
        provider_id: str,
        lifecycle: ProviderLifecycle,
        updated_at: Optional[datetime] = None,
    ) -> bool:
        current = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            cur = conn.execute(
                """UPDATE provider_registry
                   SET lifecycle_state=?,updated_at=?
                   WHERE provider_id=?""",
                (
                    lifecycle.value,
                    datetime_to_text(current, "updated_at"),
                    provider_id,
                ),
            )
            return cur.rowcount == 1

    def authorization_compatible(
        self,
        *,
        provider_id: str,
        capability: str,
        artifact_digest: Optional[str],
        interface_digest: str,
        tool_schema_digest: Optional[str],
    ) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT capability,artifact_digest,interface_digest,
                          tool_schema_digest,lifecycle_state,
                          health_state_json
                   FROM provider_registry WHERE provider_id=?""",
                (provider_id,),
            ).fetchone()
        if row is None or str(row["lifecycle_state"]) != "ACTIVE":
            return False
        if (
            str(row["capability"]) != capability
            or row["artifact_digest"] != artifact_digest
            or str(row["interface_digest"]) != interface_digest
            or row["tool_schema_digest"] != tool_schema_digest
        ):
            return False
        try:
            health = json.loads(str(row["health_state_json"]))
        except (TypeError, ValueError):
            return False
        return (
            str(health.get("readiness", "")).upper() == "READY"
            and str(health.get("liveness", "")).upper()
            not in {"DOWN", "DEAD", "UNAVAILABLE"}
        )
