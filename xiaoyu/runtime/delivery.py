from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from xiaoyu.contracts import (
    ActionRequest,
    ActorContext,
    AuthorizationContext,
    Delegation,
    EffectIntent,
    PrincipalContext,
    ResourceRef,
)
from xiaoyu.core.authorization import AuthorizationResult
from xiaoyu.core.effects import EffectCoordinator
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.receipts import DeliveryRepository


class DeliveryLedger:
    """Durable logical-delivery metadata only.

    Carrier transports are deliberately absent here. Every actual carrier attempt
    must flow through DeliveryCoordinator -> EffectCoordinator -> OutboxDispatcher.
    """

    def __init__(self, db: Database, repository=None) -> None:
        self.db = db
        self.repository = repository or DeliveryRepository()

    def create(
        self,
        *,
        delivery_id: str,
        identity_id: str,
        logical_notification_id: str,
        purpose_id: Optional[str],
        preferred_surface: str,
        created_at: Optional[datetime] = None,
    ) -> bool:
        current = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            return self.repository.create(
                conn,
                delivery_id=delivery_id,
                identity_id=identity_id,
                logical_notification_id=logical_notification_id,
                purpose_id=purpose_id,
                surface=preferred_surface,
                created_at=current,
            )


class DeliveryAttemptAlreadyActive(RuntimeError):
    pass


class DeliveryCoordinator:
    """Reserve one logical carrier attempt and enqueue its authorized effect atomically."""

    def __init__(
        self,
        db: Database,
        delivery_repo=None,
        effect_coordinator=None,
    ) -> None:
        self.db = db
        self.delivery_repo = delivery_repo or DeliveryRepository()
        self.effect_coordinator = effect_coordinator or EffectCoordinator(db)

    def enqueue_attempt(
        self,
        *,
        attempt_id: str,
        delivery_id: str,
        logical_notification_id: str,
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
        surface: str,
        created_at: Optional[datetime] = None,
    ) -> None:
        payload_logical_id = effect.request.get("logical_notification_id")
        if (
            payload_logical_id is not None
            and payload_logical_id != logical_notification_id
        ):
            raise ValueError(
                "effect logical_notification_id does not match delivery identity"
            )
        current = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            if not self.delivery_repo.reserve_attempt(
                conn,
                attempt_id=attempt_id,
                delivery_id=delivery_id,
                identity_id=identity_id,
                logical_notification_id=logical_notification_id,
                effect_id=effect.effect_id,
                purpose_id=effect.purpose_id,
                surface=surface,
                created_at=current,
            ):
                raise DeliveryAttemptAlreadyActive(
                    "logical notification already delivered, reconciling, "
                    "or has an active carrier attempt"
                )
            self.effect_coordinator.enqueue_authorized_in_transaction(
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
                destination=surface,
                payload=effect.request,
                created_at=current,
            )
