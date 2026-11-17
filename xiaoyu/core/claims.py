from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from xiaoyu.contracts import Taint, TrustClass
from xiaoyu.core.events import CanonicalEvent
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.claims import ClaimRepository
from xiaoyu.persistence.repositories.events import CanonicalEventRepository


class ClaimAdmissionError(PermissionError):
    pass


class OwnerMutationAdmissionPolicy:
    """Only authenticated owner-origin evidence may directly mutate truth."""

    TRUSTED_OWNER_CLASSES = {
        TrustClass.OWNER_DIRECT,
        TrustClass.OWNER_AUTHENTICATED_DEVICE,
    }
    FORBIDDEN_TAINTS = {
        Taint.MODEL_INFERRED,
        Taint.THIRD_PARTY_DATA,
        Taint.UNTRUSTED_INSTRUCTION,
    }

    def require(
        self,
        event: CanonicalEvent,
        authenticated_principal_id: str,
    ) -> None:
        if not authenticated_principal_id:
            raise ClaimAdmissionError(
                "authenticated principal is required"
            )
        if event.principal_id != authenticated_principal_id:
            raise ClaimAdmissionError(
                "source principal does not match authenticated principal"
            )
        if event.trust_class not in self.TRUSTED_OWNER_CLASSES:
            raise ClaimAdmissionError(
                "source trust class cannot directly mutate authority"
            )
        if not event.eligible_for_memory:
            raise ClaimAdmissionError(
                "source is not eligible for durable memory"
            )
        forbidden = set(event.taint).intersection(
            self.FORBIDDEN_TAINTS
        )
        if forbidden:
            raise ClaimAdmissionError(
                "tainted source requires explicit higher-level review"
            )


class ClaimProposalService:
    """Stores candidates only. Proposal never creates a temporal fact."""

    def __init__(
        self,
        db: Database,
        event_repo=None,
        claim_repo=None,
    ) -> None:
        self.db = db
        self.event_repo = event_repo or CanonicalEventRepository()
        self.claim_repo = claim_repo or ClaimRepository()

    def propose(
        self,
        *,
        claim_id: str,
        source_event_id: str,
        subject: str,
        predicate: str,
        value: Any,
        confidence: float,
        created_at: Optional[datetime] = None,
    ) -> str:
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            event = self.event_repo.get(conn, source_event_id)
            if event is None:
                raise KeyError(
                    "unknown source_event_id %s" % source_event_id
                )
            self.claim_repo.insert(
                conn,
                claim_id=claim_id,
                event=event,
                subject=subject,
                predicate=predicate,
                value=value,
                confidence=confidence,
                status="CANDIDATE",
                created_at=at,
                principal_scope=event.principal_id,
                decision_reason="PROPOSAL_ONLY",
            )
        return claim_id
