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
from xiaoyu.contracts.common import StringEnum
from xiaoyu.core.authorization import AuthorizationResult
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


class EffectCoordinator:
    """Atomically persists authorization + effect + outbox commitment."""

    def __init__(self, db: Database, auth_repo=None, effect_repo=None, outbox_repo=None) -> None:
        from xiaoyu.persistence.repositories.effects import EffectRepository, OutboxRepository

        self.db = db
        self.auth_repo = auth_repo or AuthorizationDecisionRepository()
        self.effect_repo = effect_repo or EffectRepository()
        self.outbox_repo = outbox_repo or OutboxRepository()

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
        if auth_result.decision != AuthorizationDecision.ALLOW:
            raise EffectNotAuthorized("effect enqueue requires ALLOW decision")
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
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
                created_at=at,
            )
            self.effect_repo.insert(conn, identity_id, effect, state="QUEUED", updated_at=at)
            self.outbox_repo.enqueue(
                conn,
                outbox_id=outbox_id,
                identity_id=identity_id,
                effect_id=effect.effect_id,
                destination=destination,
                payload=payload,
                created_at=at,
            )
