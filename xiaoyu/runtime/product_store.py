from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from xiaoyu.contracts import (
    InputSourceEnvelope,
    Taint,
    TrustClass,
)
from xiaoyu.core.claims import (
    ClaimProposalService,
    OwnerMutationAdmissionPolicy,
)
from xiaoyu.core.events import (
    CanonicalEvent,
    stable_event_id,
)
from xiaoyu.core.identity import SelfAuthorityService
from xiaoyu.core.memory import (
    CANONICAL_MEMORY_PREDICATE,
    CanonicalMemoryItem,
    CanonicalMemoryService,
)
from xiaoyu.core.purpose import Purpose
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.events import (
    CanonicalEventRepository,
)
from xiaoyu.persistence.repositories.product_runtime import (
    DEFAULT_PRESENTATION,
    MemoryProposalDecisionRepository,
    PresentationStateRepository,
)
from xiaoyu.persistence.repositories.purposes import PurposeRepository


class CanonicalProductWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoryProposal:
    claim_id: str
    state: str
    text: str
    category: str
    priority: int
    source_event_id: str
    memory_id: Optional[str] = None
    decision_event_id: Optional[str] = None


class PresentationStateStore:
    """Non-authority presentation state replacing legacy settings.state."""

    def __init__(
        self,
        db: Database,
        *,
        repository=None,
    ) -> None:
        self.db = db
        self.repository = (
            repository or PresentationStateRepository()
        )

    def get(self, identity_id: str) -> dict:
        with self.db.transaction() as conn:
            value = self.repository.get(conn, identity_id)
        if value is None:
            return dict(DEFAULT_PRESENTATION)
        return value

    def update(
        self,
        *,
        identity_id: str,
        state: dict,
        updated_at: Optional[datetime] = None,
    ) -> dict:
        at = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            return self.repository.update(
                conn,
                identity_id=identity_id,
                state=state,
                updated_at=at,
            )

    def backfill_legacy(
        self,
        *,
        identity_id: str,
        updated_at: Optional[datetime] = None,
    ) -> dict:
        at = updated_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            existing = self.repository.get(
                conn, identity_id
            )
            if existing is not None:
                return existing
            table = conn.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='settings'"""
            ).fetchone()
            legacy = {}
            if table is not None:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key='state'"
                ).fetchone()
                if row is not None:
                    import json
                    try:
                        value = json.loads(str(row[0]))
                    except (
                        TypeError,
                        ValueError,
                        json.JSONDecodeError,
                    ):
                        value = {}
                    if isinstance(value, dict):
                        legacy = value
            return self.repository.initialize(
                conn,
                identity_id=identity_id,
                state=legacy or DEFAULT_PRESENTATION,
                updated_at=at,
            )


class MemoryProposalLedger:
    """Product approval/rejection ledger over existing Claim candidates."""

    def __init__(
        self,
        db: Database,
        *,
        claim_service=None,
        decision_repository=None,
        memory_service=None,
        event_repository=None,
        admission_policy=None,
    ) -> None:
        self.db = db
        self.claim_service = (
            claim_service or ClaimProposalService(db)
        )
        self.decisions = (
            decision_repository
            or MemoryProposalDecisionRepository()
        )
        self.memory_service = (
            memory_service or CanonicalMemoryService(db)
        )
        self.events = (
            event_repository or CanonicalEventRepository()
        )
        self.admission = (
            admission_policy
            or OwnerMutationAdmissionPolicy()
        )

    @staticmethod
    def _candidate_value(
        *,
        text: str,
        category: str,
        priority: int,
    ) -> dict:
        normalized = CanonicalMemoryService._value(
            memory_id="proposal",
            text=text,
            category=category,
            priority=priority,
        )
        normalized.pop("memory_id", None)
        return normalized

    @staticmethod
    def _view(row) -> MemoryProposal:
        value = row["value"]
        return MemoryProposal(
            claim_id=str(row["claim_id"]),
            state=str(row["state"]),
            text=str(value["text"]),
            category=str(value["category"]),
            priority=int(value["priority"]),
            source_event_id=str(row["source_event_id"]),
            memory_id=row.get("memory_id"),
            decision_event_id=row.get(
                "decision_event_id"
            ),
        )

    def propose(
        self,
        *,
        claim_id: str,
        source_event_id: str,
        text: str,
        category: str,
        priority: int = 3,
        confidence: float = 1.0,
        created_at: Optional[datetime] = None,
    ) -> MemoryProposal:
        at = created_at or datetime.now(timezone.utc)
        value = self._candidate_value(
            text=text,
            category=category,
            priority=priority,
        )
        with self.db.transaction(immediate=True) as conn:
            event = self.events.get(conn, source_event_id)
            if event is None:
                raise KeyError(
                    "unknown proposal source event %s"
                    % source_event_id
                )
            self.claim_service.propose_in_transaction(
                conn,
                claim_id=claim_id,
                source_event_id=source_event_id,
                subject="memory-proposal:" + claim_id,
                predicate=CANONICAL_MEMORY_PREDICATE,
                value=value,
                confidence=confidence,
                created_at=at,
            )
            self.decisions.insert_pending(
                conn,
                claim_id=claim_id,
                identity_id=event.identity_id,
                created_at=at,
            )
            row = self.decisions.get(conn, claim_id)
        return self._view(row)

    def get(self, claim_id: str) -> MemoryProposal:
        with self.db.transaction() as conn:
            row = self.decisions.get(conn, claim_id)
        if row is None:
            raise KeyError(
                "unknown memory proposal %s" % claim_id
            )
        return self._view(row)

    def list_pending(
        self,
        identity_id: str,
    ) -> list[MemoryProposal]:
        with self.db.transaction() as conn:
            rows = self.decisions.list_state(
                conn,
                identity_id=identity_id,
                state="PENDING",
            )
        result = []
        for row in rows:
            value = __import__("json").loads(
                str(row["object_json"])
            )
            result.append(
                MemoryProposal(
                    claim_id=str(row["claim_id"]),
                    state=str(row["state"]),
                    text=str(value["text"]),
                    category=str(value["category"]),
                    priority=int(value["priority"]),
                    source_event_id=str(
                        row["source_event_id"]
                    ),
                    memory_id=row["memory_id"],
                    decision_event_id=row[
                        "decision_event_id"
                    ],
                )
            )
        return result

    def approve(
        self,
        *,
        claim_id: str,
        decision_event_id: str,
        principal_id: str,
        memory_id: Optional[str] = None,
        decided_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        at = decided_at or datetime.now(timezone.utc)
        with self.db.transaction() as conn:
            row = self.decisions.get(conn, claim_id)
            if row is None:
                raise KeyError(
                    "unknown memory proposal %s" % claim_id
                )
            if row["state"] == "REJECTED":
                raise CanonicalProductWriteError(
                    "rejected memory proposal cannot be approved"
                )
            existing_memory_id = row["memory_id"]
            event = self.events.get(
                conn, decision_event_id
            )
            if event is None:
                raise KeyError(
                    "unknown decision event %s"
                    % decision_event_id
                )
            self.admission.require(event, principal_id)
            value = dict(row["value"])
            identity_id = str(row["identity_id"])

        final_memory_id = str(
            existing_memory_id
            or memory_id
            or ("proposal:" + claim_id)
        )
        item = self.memory_service.save(
            memory_id=final_memory_id,
            mutation_id=(
                "memory-proposal:" + claim_id + ":approve"
            ),
            source_event_id=decision_event_id,
            principal_id=principal_id,
            text=str(value["text"]),
            category=str(value["category"]),
            priority=int(value["priority"]),
            created_at=at,
        )

        with self.db.transaction(immediate=True) as conn:
            current = self.decisions.get(conn, claim_id)
            if current["state"] == "PENDING":
                self.decisions.decide(
                    conn,
                    claim_id=claim_id,
                    expected_state="PENDING",
                    state="APPROVED",
                    memory_id=final_memory_id,
                    decision_event_id=decision_event_id,
                    updated_at=at,
                )
                conn.execute(
                    """UPDATE claims
                       SET status='PROMOTED',
                           decision_reason='OWNER_APPROVED_MEMORY'
                       WHERE claim_id=? AND status='CANDIDATE'""",
                    (claim_id,),
                )
            elif current["state"] != "APPROVED":
                raise CanonicalProductWriteError(
                    "memory proposal changed during approval"
                )
        return item

    def reject(
        self,
        *,
        claim_id: str,
        decision_event_id: str,
        principal_id: str,
        decided_at: Optional[datetime] = None,
    ) -> MemoryProposal:
        at = decided_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            row = self.decisions.get(conn, claim_id)
            if row is None:
                raise KeyError(
                    "unknown memory proposal %s" % claim_id
                )
            if row["state"] == "APPROVED":
                raise CanonicalProductWriteError(
                    "approved proposal cannot be rejected"
                )
            event = self.events.get(
                conn, decision_event_id
            )
            if event is None:
                raise KeyError(
                    "unknown decision event %s"
                    % decision_event_id
                )
            self.admission.require(event, principal_id)
            if row["state"] == "PENDING":
                self.decisions.decide(
                    conn,
                    claim_id=claim_id,
                    expected_state="PENDING",
                    state="REJECTED",
                    memory_id=None,
                    decision_event_id=decision_event_id,
                    updated_at=at,
                )
                conn.execute(
                    """UPDATE claims
                       SET status='REJECTED',
                           decision_reason='OWNER_REJECTED_MEMORY'
                       WHERE claim_id=? AND status='CANDIDATE'""",
                    (claim_id,),
                )
            result = self.decisions.get(conn, claim_id)
        return self._view(result)


class CanonicalProductStore:
    """Product write facade over canonical authorities; owns no parallel truth."""

    def __init__(
        self,
        db: Database,
        *,
        identity_id: str,
    ) -> None:
        apply_migrations(db)
        self.db = db
        self.identity_id = str(identity_id)
        self.events = CanonicalEventRepository()
        self.self_authority = SelfAuthorityService(db)
        self.memory = CanonicalMemoryService(db)
        self.proposals = MemoryProposalLedger(db)
        self.presentation = PresentationStateStore(db)
        self.purposes = PurposeRepository()

    def _record(
        self,
        *,
        source_namespace: str,
        source_event_key: str,
        event_type: str,
        surface: str,
        source_type: str,
        principal_id: Optional[str],
        audience_scope: str,
        context_space: str,
        trust_class: TrustClass,
        taint: tuple[Taint, ...],
        eligible_for_memory: bool,
        payload_type: str,
        payload,
        observed_at: datetime,
        correlation_id: str,
    ) -> CanonicalEvent:
        if not source_event_key:
            raise ValueError(
                "source_event_key is required for idempotent product writes"
            )
        envelope = InputSourceEnvelope(
            event_id="source:" + source_event_key,
            surface=surface,
            source_type=source_type,
            principal_hint=principal_id,
            audience_scope=audience_scope,
            context_space=context_space,
            trust_class=trust_class,
            taint=taint,
            eligible_for_memory=eligible_for_memory,
            correlation_id=correlation_id,
            observed_at=observed_at,
            payload_type=payload_type,
            payload=payload,
        )
        event = CanonicalEvent.from_envelope(
            identity_id=self.identity_id,
            event_type=event_type,
            envelope=envelope,
            principal_id=principal_id,
            recorded_at=observed_at,
            source_namespace=source_namespace,
            source_event_key=source_event_key,
            event_id_override=stable_event_id(
                self.identity_id,
                source_namespace,
                source_event_key,
            ),
        )
        with self.db.transaction(immediate=True) as conn:
            return self.events.append_or_get(conn, event)

    def record_user_turn(
        self,
        *,
        source_event_key: str,
        text: str,
        principal_id: str = "owner",
        surface: str = "desktop",
        audience_scope: str = "PRIVATE",
        context_space: str = "PERSONAL",
        observed_at: Optional[datetime] = None,
        correlation_id: Optional[str] = None,
    ) -> CanonicalEvent:
        clean = str(text)
        if not clean or len(clean) > 30000:
            raise ValueError(
                "user turn must be 1-30000 characters"
            )
        at = observed_at or datetime.now(timezone.utc)
        return self._record(
            source_namespace="product:" + surface,
            source_event_key=source_event_key,
            event_type="conversation.user",
            surface=surface,
            source_type="text",
            principal_id=principal_id,
            audience_scope=audience_scope,
            context_space=context_space,
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            payload_type="text/plain",
            payload={"text": clean},
            observed_at=at,
            correlation_id=(
                correlation_id
                or ("turn:" + source_event_key)
            ),
        )

    def record_assistant_turn(
        self,
        *,
        source_event_key: str,
        text: str,
        surface: str = "desktop",
        audience_scope: str = "PRIVATE",
        context_space: str = "PERSONAL",
        observed_at: Optional[datetime] = None,
        correlation_id: Optional[str] = None,
    ) -> CanonicalEvent:
        clean = str(text)
        if not clean or len(clean) > 30000:
            raise ValueError(
                "assistant turn must be 1-30000 characters"
            )
        at = observed_at or datetime.now(timezone.utc)
        return self._record(
            source_namespace="product:" + surface,
            source_event_key=source_event_key,
            event_type="conversation.assistant",
            surface=surface,
            source_type="text",
            principal_id=None,
            audience_scope=audience_scope,
            context_space=context_space,
            trust_class=TrustClass.MODEL_DERIVED,
            taint=(Taint.MODEL_INFERRED,),
            eligible_for_memory=False,
            payload_type="text/plain",
            payload={"text": clean},
            observed_at=at,
            correlation_id=(
                correlation_id
                or ("turn:" + source_event_key)
            ),
        )

    def record_owner_control(
        self,
        *,
        source_event_key: str,
        event_type: str,
        payload: dict,
        principal_id: str = "owner",
        surface: str = "desktop",
        observed_at: Optional[datetime] = None,
    ) -> CanonicalEvent:
        at = observed_at or datetime.now(timezone.utc)
        return self._record(
            source_namespace="product-control:" + surface,
            source_event_key=source_event_key,
            event_type=event_type,
            surface=surface,
            source_type="control",
            principal_id=principal_id,
            audience_scope="PRIVATE",
            context_space="PERSONAL",
            trust_class=TrustClass.OWNER_DIRECT,
            taint=(),
            eligible_for_memory=True,
            payload_type="application/json",
            payload=dict(payload),
            observed_at=at,
            correlation_id="control:" + source_event_key,
        )

    def create_purpose(
        self,
        purpose: Purpose,
        *,
        created_at: Optional[datetime] = None,
    ) -> None:
        if purpose.identity_id != self.identity_id:
            raise CanonicalProductWriteError(
                "purpose identity mismatch"
            )
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            source = self.events.get(
                conn, purpose.source_event_id
            )
            if source is None:
                raise KeyError(
                    "purpose source event is missing"
                )
            if source.identity_id != self.identity_id:
                raise CanonicalProductWriteError(
                    "purpose source identity mismatch"
                )
            self.purposes.insert(conn, purpose, at)
