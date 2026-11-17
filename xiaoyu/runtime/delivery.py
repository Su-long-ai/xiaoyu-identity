from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.receipts import DeliveryRepository


DeliveryTransport = Callable[[dict], Optional[str]]


class DeliveryLedger:
    """Carrier fallback with one logical durable delivery outcome."""

    def __init__(
        self,
        db: Database,
        transports: Dict[str, DeliveryTransport],
        repository=None,
    ) -> None:
        self.db = db
        self.transports = dict(transports)
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

    def attempt(
        self,
        *,
        identity_id: str,
        logical_notification_id: str,
        surface: str,
        payload: dict,
        now: Optional[datetime] = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            if not self.repository.begin_attempt(
                conn,
                identity_id=identity_id,
                logical_notification_id=logical_notification_id,
                surface=surface,
                updated_at=current,
            ):
                return False

        transport = self.transports.get(surface)
        if transport is None:
            with self.db.transaction(immediate=True) as conn:
                self.repository.mark_failed(
                    conn,
                    identity_id=identity_id,
                    logical_notification_id=logical_notification_id,
                    updated_at=current,
                )
            return False

        try:
            external_ref = transport(payload)
        except Exception:
            with self.db.transaction(immediate=True) as conn:
                self.repository.mark_failed(
                    conn,
                    identity_id=identity_id,
                    logical_notification_id=logical_notification_id,
                    updated_at=current,
                )
            return False

        with self.db.transaction(immediate=True) as conn:
            return self.repository.mark_delivered(
                conn,
                identity_id=identity_id,
                logical_notification_id=logical_notification_id,
                surface=surface,
                external_ref=external_ref,
                updated_at=current,
            )
