from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

from xiaoyu.contracts.capability import ProviderHealth


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
    owner_principal_id: Optional[str] = "owner"
    routing_policy_digest: Optional[str] = None
    expected_descriptor_digest: Optional[str] = None
    expected_capability_digest: Optional[str] = None
    expected_approval_binding_digest: Optional[str] = None
    authorization_digest: Optional[str] = None
    tool_result_digest: Optional[str] = None
    tool_implementation_digest: Optional[str] = None
    tool_schema_digest: Optional[str] = None
    source_contains_private_tool_result: bool = False
    viewer_principal_ids: Tuple[str, ...] = ()


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


AUDIENCE_RESET_COMPONENTS=(
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
    """Declare the mandatory reset boundary before any audience/principal reuse."""
    reasons=[]
    for field in (
        "identity_id",
        "principal_id",
        "audience_scope",
        "context_space",
    ):
        if getattr(previous,field) != getattr(current,field):
            reasons.append(field+"_changed")
    if tuple(sorted(previous.viewer_principal_ids)) != tuple(
        sorted(current.viewer_principal_ids)
    ):
        reasons.append("viewer_principal_ids_changed")
    if reasons:
        return AudienceResetDecision(
            required=True,
            clear_components=AUDIENCE_RESET_COMPONENTS,
            reasons=tuple(reasons),
        )
    return AudienceResetDecision(False,(),())


def apply_audience_reset(
    state: MutableMapping[str, Any],
    previous: ProviderAttemptContext,
    current: ProviderAttemptContext,
) -> AudienceResetDecision:
    """Clear every audience-derived runtime slot before the new scope is used.

    The caller owns the state container; this helper deliberately clears only
    audience-derived slots and leaves unrelated process state untouched.
    """
    decision=audience_reset_decision(previous,current)
    if not decision.required:
        return decision
    for component in decision.clear_components:
        state.pop(component,None)
    return decision


def stable_digest(value: Mapping[str, Any] | Dict[str, Any]) -> str:
    payload=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return "sha256:"+hashlib.sha256(payload.encode("utf-8")).hexdigest()


def standing_approval_binding_digest(
    descriptor: ProviderDescriptor,
    context: ProviderAttemptContext,
) -> str:
    """Bind reusable approval to exactly the provider/tool contract it approved."""
    return stable_digest({
        "authorization_digest":context.authorization_digest,
        "provider_id":descriptor.provider_id,
        "provider_descriptor_digest":descriptor.descriptor_digest,
        "provider_capability_digest":descriptor.capability_digest,
        "provider_implementation_digest":descriptor.implementation_digest,
        "tool_implementation_digest":context.tool_implementation_digest,
        "tool_schema_digest":context.tool_schema_digest,
    })


def provider_session_namespace(context: ProviderAttemptContext) -> str:
    """Namespace all hidden provider state by authority + implementation state."""
    return stable_digest({
        "identity_id":context.identity_id,
        "principal_id":context.principal_id,
        "audience_scope":context.audience_scope,
        "context_space":context.context_space,
        "context_generation":context.context_generation,
        "viewer_principal_ids":sorted(context.viewer_principal_ids),
        "provider_id":context.provider_id,
        "provider_descriptor_digest":context.provider_descriptor_digest,
        "provider_capability_digest":context.provider_capability_digest,
        "provider_implementation_digest":context.provider_implementation_digest,
        "authorization_digest":context.authorization_digest,
        "routing_policy_digest":context.routing_policy_digest,
        "tool_result_digest":context.tool_result_digest,
        "tool_implementation_digest":context.tool_implementation_digest,
        "tool_schema_digest":context.tool_schema_digest,
    })


def _effective_privacy(context: ProviderAttemptContext) -> PrivacyClass:
    # LOCAL_ONLY is a transport boundary, not a weaker content class. Never
    # erase it merely because the source also contains owner-private material.
    if context.required_privacy_class is PrivacyClass.LOCAL_ONLY:
        return PrivacyClass.LOCAL_ONLY
    if context.source_contains_private_tool_result:
        return PrivacyClass.OWNER_PRIVATE
    return context.required_privacy_class


def _requires_owner_scope(context: ProviderAttemptContext) -> bool:
    return (
        context.required_privacy_class is PrivacyClass.OWNER_PRIVATE
        or context.source_contains_private_tool_result
    )


def evaluate_provider(
    descriptor: ProviderDescriptor,
    context: ProviderAttemptContext,
    health: Optional[ProviderHealth]=None,
) -> ProviderEligibility:
    reasons=[]
    if descriptor.provider_id != context.provider_id:
        reasons.append("provider_id_mismatch")
    if descriptor.capability != context.required_capability:
        reasons.append("capability_mismatch")
    if descriptor.descriptor_digest != context.provider_descriptor_digest:
        reasons.append("attempt_descriptor_mismatch")
    if descriptor.capability_digest != context.provider_capability_digest:
        reasons.append("attempt_capability_digest_mismatch")
    if descriptor.implementation_digest != context.provider_implementation_digest:
        reasons.append("attempt_implementation_digest_mismatch")
    if str(descriptor.session_mode or "").upper() != "STATELESS":
        # Current host intentionally carries no provider-side KV/session ID.
        # Stateful providers remain ineligible until the host binds the
        # computed namespace to the provider's actual session primitive.
        reasons.append("stateful_provider_session_not_host_bound")

    privacy=_effective_privacy(context)
    if privacy not in descriptor.privacy_classes:
        reasons.append("privacy_class_ineligible")
    if privacy is PrivacyClass.LOCAL_ONLY and descriptor.endpoint_scope != "LOCAL":
        reasons.append("local_only_requires_local_provider")

    audience=str(context.audience_scope or "").upper()
    principal=str(context.principal_id or "").lower()
    owner_principal=str(context.owner_principal_id or "").lower()
    context_space=str(context.context_space or "").upper()
    if _requires_owner_scope(context):
        if audience not in {"PRIVATE","OWNER_PRIVATE"}:
            reasons.append("owner_private_audience_mismatch")
        # Owner-private authority is an allowlist binding, not a denylist.
        if not owner_principal or principal != owner_principal:
            reasons.append("owner_private_principal_mismatch")
        viewers = {
            str(value).lower()
            for value in context.viewer_principal_ids
            if str(value)
        }
        if viewers != {owner_principal}:
            reasons.append("owner_private_viewer_set_mismatch")
        if context_space in {"SHARED","GROUP","GUEST"}:
            reasons.append("owner_private_context_space_mismatch")

    if (
        context.expected_descriptor_digest is not None
        and context.expected_descriptor_digest != descriptor.descriptor_digest
    ):
        reasons.append("descriptor_digest_changed")
    if (
        context.expected_capability_digest is not None
        and context.expected_capability_digest != descriptor.capability_digest
    ):
        reasons.append("capability_digest_changed")
    if (
        context.expected_approval_binding_digest is not None
        and context.expected_approval_binding_digest
            != standing_approval_binding_digest(descriptor,context)
    ):
        reasons.append("approval_binding_changed")

    if health is not None and str(health.readiness).upper() != "READY":
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
