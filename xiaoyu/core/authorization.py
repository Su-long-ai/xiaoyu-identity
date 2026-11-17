from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import datetime, timezone
from typing import Optional

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    AuthorizationDecision,
    Delegation,
    PrincipalContext,
    ResourceRef,
    RiskTier,
)


OWNER_STRONG_LEVELS = {"OWNER_AUTHENTICATED"}

# Execution Reliability deliberately keeps this small and explicit.  These are
# the only external action classes implemented by the current R5-R8 slice.
_ACTION_PARAMETER_SCHEMAS = {
    "message.send": {"messages": int},
    "notification.deliver": {"messages": int},
}


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    reason_code: str
    matched_delegation_id: Optional[str] = None


def validate_action_parameters(action: ActionRequest) -> Optional[str]:
    schema = _ACTION_PARAMETER_SCHEMAS.get(action.action_class)
    if schema is None:
        return "UNKNOWN_ACTION"
    actual = set(action.parameters)
    expected = set(schema)
    missing = expected - actual
    if missing:
        return "MISSING_PARAMETER_%s" % sorted(missing)[0]
    unknown = actual - expected
    if unknown:
        return "UNKNOWN_PARAMETER_%s" % sorted(unknown)[0]
    for key, expected_type in schema.items():
        value = action.parameters[key]
        if expected_type is int:
            if isinstance(value, bool) or not isinstance(value, int):
                return "PARAMETER_TYPE_MISMATCH_%s" % key
            if value <= 0:
                return "PARAMETER_VALUE_MISMATCH_%s" % key
        elif not isinstance(value, expected_type):
            return "PARAMETER_TYPE_MISMATCH_%s" % key
    return None


class AuthorizationPolicy:
    """Deterministic pre-effect policy. Models never override this result."""

    def evaluate(
        self,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        context: AuthorizationContext,
        now: Optional[datetime] = None,
    ) -> AuthorizationResult:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("authorization time must be timezone-aware")

        action_error = validate_action_parameters(action)
        if action_error is not None:
            return AuthorizationResult(
                AuthorizationDecision.DENY,
                "ACTION_INVALID_%s" % action_error,
            )

        if principal.expires_at is not None and current >= principal.expires_at:
            return AuthorizationResult(AuthorizationDecision.DENY, "PRINCIPAL_EXPIRED")

        strong_owner = principal.authentication_level in OWNER_STRONG_LEVELS
        private_resource = bool(resource.attributes.get("private"))
        if private_resource and not strong_owner:
            return AuthorizationResult(AuthorizationDecision.DENY, "PRIVATE_RESOURCE_REQUIRES_OWNER")
        if private_resource:
            if context.audience_scope != "PRIVATE":
                return AuthorizationResult(
                    AuthorizationDecision.DENY,
                    "PRIVATE_RESOURCE_REQUIRES_PRIVATE_AUDIENCE",
                )
            if any(viewer != principal.principal_id for viewer in principal.viewer_set):
                return AuthorizationResult(
                    AuthorizationDecision.DENY,
                    "PRIVATE_RESOURCE_HAS_OTHER_VIEWERS",
                )

        delegation_reason = self._delegation_failure_reason(
            principal, actor, delegation, action, resource, current
        )
        if delegation is not None and delegation_reason is None:
            return AuthorizationResult(
                AuthorizationDecision.ALLOW,
                "VALID_DELEGATION",
                matched_delegation_id=delegation.delegation_id,
            )

        if action.risk_tier == RiskTier.T0_OBSERVE:
            if private_resource and not strong_owner:
                return AuthorizationResult(AuthorizationDecision.DENY, "PRIVATE_OBSERVE_DENIED")
            return AuthorizationResult(AuthorizationDecision.ALLOW, "OBSERVE_ALLOWED")

        if not strong_owner:
            return AuthorizationResult(AuthorizationDecision.DENY, "STRONG_OWNER_REQUIRED")

        if action.risk_tier == RiskTier.T1_LOCAL_REVERSIBLE:
            return AuthorizationResult(AuthorizationDecision.ALLOW, "OWNER_LOCAL_REVERSIBLE")

        if delegation is not None and delegation_reason is not None:
            return AuthorizationResult(
                AuthorizationDecision.ASK,
                "DELEGATION_INVALID_%s" % delegation_reason,
            )

        if action.risk_tier == RiskTier.T2_OWNER_STATE_MUTATION:
            return AuthorizationResult(AuthorizationDecision.ASK, "OWNER_MUTATION_REQUIRES_CONFIRMATION")

        if action.risk_tier == RiskTier.T3_EXTERNAL_OR_IRREVERSIBLE:
            return AuthorizationResult(AuthorizationDecision.ASK, "EXTERNAL_EFFECT_REQUIRES_CONFIRMATION")

        return AuthorizationResult(AuthorizationDecision.DENY, "UNRECOGNIZED_RISK_TIER")

    def _delegation_failure_reason(
        self,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        current: datetime,
    ) -> Optional[str]:
        if delegation is None:
            return "MISSING"
        if delegation.issued_by_principal != principal.principal_id:
            return "WRONG_PRINCIPAL"
        if delegation.issued_to_actor != actor.actor_id:
            return "WRONG_ACTOR"
        if delegation.revoked_at is not None and current >= delegation.revoked_at:
            return "REVOKED"
        if current < delegation.valid_from:
            return "NOT_YET_VALID"
        if delegation.expires_at is not None and current >= delegation.expires_at:
            return "EXPIRED"
        if action.action_class not in delegation.action_classes and "*" not in delegation.action_classes:
            return "WRONG_ACTION"

        resource_tokens = {
            resource.identifier,
            "%s:%s" % (resource.kind, resource.identifier),
        }
        if "*" not in delegation.resources and not resource_tokens.intersection(delegation.resources):
            return "WRONG_RESOURCE"

        for key, limit in delegation.max_effect.items():
            requested = action.parameters.get(key)
            if isinstance(limit, bool):
                return "INVALID_LIMIT_SCHEMA"
            if isinstance(limit, (int, float)):
                if (
                    isinstance(requested, bool)
                    or not isinstance(requested, (int, float))
                    or not math.isfinite(float(requested))
                ):
                    return "PARAMETER_TYPE_MISMATCH"
                if not math.isfinite(float(limit)):
                    return "INVALID_LIMIT_SCHEMA"
                if requested > limit:
                    return "MAX_EFFECT_EXCEEDED"
        return None
