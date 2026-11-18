from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    AuthorizationDecision,
    Delegation,
    EffectIntent,
    PrincipalContext,
    ResourceRef,
)
from xiaoyu.contracts.common import StringEnum, canonical_json
from xiaoyu.core.authorization import AuthorizationPolicy, AuthorizationResult
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.grants import AuthorizationDecisionRepository


class OutboxState(StringEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class DispatchStatus(StringEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DispatchOutcome:
    status: DispatchStatus
    external_ref: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    retry_after_s: Optional[float] = None


class EffectNotAuthorized(RuntimeError):
    pass


class EffectBindingError(ValueError):
    pass


_REQUEST_SCHEMAS = {
    "message.send": (
        {"text"},
        {"recipient"},
    ),
    "notification.deliver": (
        {"logical_notification_id", "surface", "text"},
        {"recipient"},
    ),
}


def _validate_request_shape(action_class: str, request: Dict[str, Any]) -> None:
    schema = _REQUEST_SCHEMAS.get(action_class)
    if schema is None:
        raise EffectBindingError("unknown executable action")
    required, optional = schema
    actual = set(request)
    missing = required - actual
    if missing:
        raise EffectBindingError(
            "effect request missing field: %s" % sorted(missing)[0]
        )
    unknown = actual - required - optional
    if unknown:
        raise EffectBindingError(
            "effect request has unknown field: %s" % sorted(unknown)[0]
        )
    for key in actual:
        if not isinstance(request[key], str):
            raise EffectBindingError(
                "effect request field must be string: %s" % key
            )
        if key in required and not request[key]:
            raise EffectBindingError(
                "effect request field must be non-empty: %s" % key
            )


class EffectCoordinator:
    """Atomically persists authorization + effect + outbox commitment."""

    def __init__(
        self,
        db: Database,
        auth_repo=None,
        effect_repo=None,
        outbox_repo=None,
        delegation_repo=None,
        actor_registry_repo=None,
        principal_registry_repo=None,
        execution_auth_repo=None,
        authorization_policy=None,
    ) -> None:
        from xiaoyu.persistence.repositories.effects import EffectRepository, OutboxRepository
        from xiaoyu.persistence.repositories.execution_auth import (
            ActorRegistryRepository,
            DelegationRepository,
            ExecutionAuthorizationRepository,
            PrincipalExecutionRepository,
        )

        self.db = db
        self.auth_repo = auth_repo or AuthorizationDecisionRepository()
        self.effect_repo = effect_repo or EffectRepository()
        self.outbox_repo = outbox_repo or OutboxRepository()
        self.delegation_repo = delegation_repo or DelegationRepository()
        self.actor_registry_repo = actor_registry_repo or ActorRegistryRepository()
        self.principal_registry_repo = (
            principal_registry_repo or PrincipalExecutionRepository()
        )
        self.execution_auth_repo = execution_auth_repo or ExecutionAuthorizationRepository()
        self.authorization_policy = authorization_policy or AuthorizationPolicy()

    @staticmethod
    def _validate_binding(
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        effect: EffectIntent,
        destination: str,
        payload: Dict[str, Any],
    ) -> None:
        if effect.actor_id != actor.actor_id:
            raise EffectBindingError("effect actor does not match authorized actor")
        if effect.action_class != action.action_class:
            raise EffectBindingError("effect action does not match authorized action")
        if effect.replayable != action.replayable:
            raise EffectBindingError("effect replayability does not match authorized action")
        if effect.idempotency_key != action.idempotency_key:
            raise EffectBindingError("effect idempotency key does not match authorized action")
        if (
            delegation is not None
            and delegation.purpose_id is not None
            and effect.purpose_id != delegation.purpose_id
        ):
            raise EffectBindingError("effect purpose does not match delegation purpose")
        if canonical_json(payload) != canonical_json(effect.request):
            raise EffectBindingError("outbox payload must equal effect request")

        _validate_request_shape(action.action_class, effect.request)

        recipient = effect.request.get("recipient")
        if recipient is not None and recipient != resource.identifier:
            raise EffectBindingError(
                "effect recipient does not match authorized resource"
            )
        surface = effect.request.get("surface")
        if surface is not None and surface != destination:
            raise EffectBindingError(
                "effect surface does not match transport destination"
            )

    def enqueue_authorized_in_transaction(
        self,
        conn,
        *,
        decision_id: str,
        outbox_id: str,
        identity_id: str,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        context: AuthorizationContext,
        auth_result: AuthorizationResult,
        effect: EffectIntent,
        destination: str,
        payload: Dict[str, Any],
        created_at: datetime,
    ) -> None:
        evaluated = self.authorization_policy.evaluate(
            principal,
            actor,
            delegation,
            action,
            resource,
            context,
            created_at,
        )
        if evaluated.decision != AuthorizationDecision.ALLOW:
            raise EffectNotAuthorized(
                "effect enqueue policy denied: %s" % evaluated.reason_code
            )
        if (
            auth_result.decision != evaluated.decision
            or auth_result.matched_delegation_id
            != evaluated.matched_delegation_id
        ):
            raise EffectNotAuthorized(
                "caller authorization result does not match policy"
            )
        self._validate_binding(
            actor,
            delegation,
            action,
            resource,
            effect,
            destination,
            payload,
        )
        purpose_row = None
        if effect.purpose_id is not None:
            purpose_row = conn.execute(
                """SELECT revision,state,resolved_utc_time
                   FROM purposes WHERE purpose_id=?""",
                (effect.purpose_id,),
            ).fetchone()
        if purpose_row is not None:
            if effect.purpose_revision is None:
                raise EffectBindingError(
                    "effect must bind current purpose revision"
                )
            if int(purpose_row["revision"]) != int(effect.purpose_revision):
                raise EffectBindingError(
                    "effect purpose revision is stale"
                )
            if str(purpose_row["state"]) in (
                "CANCELLED", "SUPERSEDED", "EXPIRED", "COMPLETED",
            ):
                raise EffectBindingError(
                    "effect cannot bind terminal purpose"
                )
            if purpose_row["resolved_utc_time"] is not None:
                if str(purpose_row["state"]) == "SCHEDULED":
                    raise EffectBindingError(
                        "scheduled purpose has not activated an occurrence"
                    )
                if effect.purpose_occurrence_id is None:
                    raise EffectBindingError(
                        "scheduled purpose effect must bind current occurrence"
                    )
            if effect.purpose_occurrence_id is not None:
                occurrence = conn.execute(
                    """SELECT state,purpose_revision FROM purpose_occurrences
                       WHERE occurrence_id=? AND purpose_id=?""",
                    (
                        effect.purpose_occurrence_id,
                        effect.purpose_id,
                    ),
                ).fetchone()
                if (
                    occurrence is None
                    or int(occurrence["purpose_revision"])
                    != int(effect.purpose_revision)
                    or str(occurrence["state"])
                    not in ("READY", "CLAIMED")
                ):
                    raise EffectBindingError(
                        "effect purpose occurrence is not executable"
                    )
        self.auth_repo.record(
            conn=conn,
            decision_id=decision_id,
            identity_id=identity_id,
            principal=principal,
            actor=actor,
            delegation=delegation,
            action=action,
            resource=resource,
            context=context,
            result=auth_result,
            created_at=created_at,
            purpose_id_override=effect.purpose_id,
        )
        delegation_digest = None
        if delegation is not None:
            delegation_digest = self.delegation_repo.ensure(
                conn,
                identity_id,
                delegation,
                actor,
            )
        self.actor_registry_repo.register(
            conn,
            actor,
            created_at,
        )
        self.principal_registry_repo.register(
            conn,
            identity_id,
            principal,
            created_at,
        )
        self.execution_auth_repo.record(
            conn,
            decision_id=decision_id,
            identity_id=identity_id,
            principal=principal,
            actor=actor,
            delegation=delegation,
            delegation_digest=delegation_digest,
            purpose_id=effect.purpose_id,
            action=action,
            resource=resource,
            context=context,
            request=payload,
            destination=destination,
            created_at=created_at,
            purpose_revision=effect.purpose_revision,
            purpose_occurrence_id=effect.purpose_occurrence_id,
        )
        self.effect_repo.insert(
            conn,
            identity_id,
            effect,
            state="QUEUED",
            updated_at=created_at,
            authorization_decision_id=decision_id,
        )
        self.outbox_repo.enqueue(
            conn,
            outbox_id=outbox_id,
            identity_id=identity_id,
            effect_id=effect.effect_id,
            destination=destination,
            payload=payload,
            created_at=created_at,
        )

    def enqueue_authorized(
        self,
        *,
        decision_id: str,
        outbox_id: str,
        identity_id: str,
        principal: PrincipalContext,
        actor: ActorContext,
        delegation: Optional[Delegation],
        action: ActionRequest,
        resource: ResourceRef,
        context: AuthorizationContext,
        auth_result: AuthorizationResult,
        effect: EffectIntent,
        destination: str,
        payload: Dict[str, Any],
        created_at: Optional[datetime] = None,
    ) -> None:
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            self.enqueue_authorized_in_transaction(
                conn,
                decision_id=decision_id,
                outbox_id=outbox_id,
                identity_id=identity_id,
                principal=principal,
                actor=actor,
                delegation=delegation,
                action=action,
                resource=resource,
                context=context,
                auth_result=auth_result,
                effect=effect,
                destination=destination,
                payload=payload,
                created_at=at,
            )
