from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import hashlib
from typing import Any, Optional

from xiaoyu.contracts.common import (
    StringEnum,
    canonical_json,
    datetime_from_text,
    datetime_to_text,
    require_aware,
)
from xiaoyu.core.claims import (
    OwnerMutationAdmissionPolicy,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.persistence.repositories.claims import ClaimRepository
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.temporal import TemporalRepository


class FactCardinality(StringEnum):
    SINGLE = "SINGLE"
    SET = "SET"


class FactMutationOperation(StringEnum):
    ASSERT = "ASSERT"
    CORRECT = "CORRECT"
    RETRACT = "RETRACT"
    DELETE = "DELETE"


class FactMutationError(RuntimeError):
    pass


class FactRevisionConflict(FactMutationError):
    pass


class FactConflict(FactMutationError):
    pass


class DeletedFactReplay(FactMutationError):
    pass


class StaleSourceEvent(FactMutationError):
    pass


class MutationIdConflict(FactMutationError):
    pass


@dataclass(frozen=True)
class FactKey:
    identity_id: str
    principal_scope: str
    context_space: str
    subject: str
    predicate: str
    cardinality: FactCardinality

    def token(self) -> str:
        payload = {
            "identity_id": self.identity_id,
            "principal_scope": self.principal_scope,
            "context_space": self.context_space,
            "subject": self.subject,
            "predicate": self.predicate,
            "cardinality": self.cardinality.value,
        }
        return "fact:" + hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class FactMutationRequest:
    mutation_id: str
    source_event_id: str
    authenticated_principal_id: str
    subject: str
    predicate: str
    operation: FactMutationOperation
    expected_revision: int
    value: Any = None
    cardinality: FactCardinality = FactCardinality.SINGLE
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    principal_scope: Optional[str] = None
    target_fact_id: Optional[str] = None
    claim_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.expected_revision < 0:
            raise ValueError("expected_revision cannot be negative")
        if self.valid_from is not None:
            require_aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            require_aware(self.valid_to, "valid_to")

    def to_dict(self) -> dict:
        return {
            "mutation_id": self.mutation_id,
            "source_event_id": self.source_event_id,
            "authenticated_principal_id":
                self.authenticated_principal_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "operation": self.operation.value,
            "expected_revision": self.expected_revision,
            "value": self.value,
            "cardinality": self.cardinality.value,
            "valid_from": None
            if self.valid_from is None
            else datetime_to_text(
                self.valid_from.astimezone(timezone.utc),
                "valid_from",
            ),
            "valid_to": None
            if self.valid_to is None
            else datetime_to_text(
                self.valid_to.astimezone(timezone.utc),
                "valid_to",
            ),
            "principal_scope": self.principal_scope,
            "target_fact_id": self.target_fact_id,
            "claim_id": self.claim_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactMutationRequest":
        return cls(
            mutation_id=str(data["mutation_id"]),
            source_event_id=str(data["source_event_id"]),
            authenticated_principal_id=str(
                data["authenticated_principal_id"]
            ),
            subject=str(data["subject"]),
            predicate=str(data["predicate"]),
            operation=FactMutationOperation(
                data["operation"]
            ),
            expected_revision=int(
                data["expected_revision"]
            ),
            value=data.get("value"),
            cardinality=FactCardinality(
                data.get("cardinality", "SINGLE")
            ),
            valid_from=None
            if data.get("valid_from") is None
            else datetime_from_text(
                data["valid_from"], "valid_from"
            ),
            valid_to=None
            if data.get("valid_to") is None
            else datetime_from_text(
                data["valid_to"], "valid_to"
            ),
            principal_scope=data.get("principal_scope"),
            target_fact_id=data.get("target_fact_id"),
            claim_id=data.get("claim_id"),
        )


@dataclass(frozen=True)
class FactMutationResult:
    mutation_id: str
    fact_key: str
    revision: int
    erasure_generation: int
    fact_id: Optional[str]


class TemporalFactService:
    """Shadow-only deterministic temporal authority."""

    def __init__(
        self,
        db: Database,
        event_repo=None,
        claim_repo=None,
        temporal_repo=None,
        admission_policy=None,
    ) -> None:
        self.db = db
        self.event_repo = event_repo or CanonicalEventRepository()
        self.claim_repo = claim_repo or ClaimRepository()
        self.temporal_repo = temporal_repo or TemporalRepository()
        self.admission_policy = (
            admission_policy or OwnerMutationAdmissionPolicy()
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        require_aware(value, "datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _fact_id(mutation_id: str, fact_key: str) -> str:
        raw = "%s\0%s" % (mutation_id, fact_key)
        return "fact:" + hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:32]

    @staticmethod
    def _claim_id(request: FactMutationRequest) -> str:
        return request.claim_id or "claim:" + request.mutation_id

    @staticmethod
    def _mutation_digest(
        request: FactMutationRequest,
        fact_key: str,
    ) -> str:
        payload = {
            "source_event_id": request.source_event_id,
            "authenticated_principal_id":
                request.authenticated_principal_id,
            "fact_key": fact_key,
            "operation": request.operation.value,
            "expected_revision": request.expected_revision,
            "value": request.value,
            "cardinality": request.cardinality.value,
            "valid_from": None
            if request.valid_from is None
            else datetime_to_text(
                request.valid_from.astimezone(timezone.utc),
                "valid_from",
            ),
            "valid_to": None
            if request.valid_to is None
            else datetime_to_text(
                request.valid_to.astimezone(timezone.utc),
                "valid_to",
            ),
            "target_fact_id": request.target_fact_id,
        }
        return "sha256:" + hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()

    def apply(
        self,
        request: FactMutationRequest,
        *,
        created_at: Optional[datetime] = None,
    ) -> FactMutationResult:
        at = self._utc(
            created_at or datetime.now(timezone.utc)
        )
        with self.db.transaction(immediate=True) as conn:
            event = self.event_repo.get(
                conn, request.source_event_id
            )
            if event is None:
                raise KeyError(
                    "unknown source event %s"
                    % request.source_event_id
                )
            self.admission_policy.require(
                event,
                request.authenticated_principal_id,
            )
            source_ingest_revision = (
                self.event_repo.get_ingest_revision(
                    conn, event.event_id
                )
            )
            principal_scope = (
                request.principal_scope or event.principal_id
            )
            if principal_scope != request.authenticated_principal_id:
                raise FactMutationError(
                    "owner mutation principal scope mismatch"
                )

            key = FactKey(
                identity_id=event.identity_id,
                principal_scope=principal_scope,
                context_space=event.context_space,
                subject=request.subject,
                predicate=request.predicate,
                cardinality=request.cardinality,
            )
            fact_key = key.token()
            mutation_digest = self._mutation_digest(
                request, fact_key
            )

            existing = self.temporal_repo.mutation_by_id(
                conn, request.mutation_id
            )
            if existing is not None:
                if (
                    str(existing["mutation_digest"])
                    != mutation_digest
                ):
                    raise MutationIdConflict(
                        "mutation id reused with different semantics"
                    )
                fact_row = conn.execute(
                    """SELECT fact_id FROM temporal_facts
                       WHERE mutation_id=?
                       ORDER BY revision DESC LIMIT 1""",
                    (request.mutation_id,),
                ).fetchone()
                state = self.temporal_repo.revision_state(
                    conn, event.identity_id, fact_key
                )
                return FactMutationResult(
                    request.mutation_id,
                    fact_key,
                    int(existing["result_revision"]),
                    int(state["erasure_generation"]),
                    None
                    if fact_row is None
                    else str(fact_row["fact_id"]),
                )

            state = self.temporal_repo.revision_state(
                conn, event.identity_id, fact_key
            )
            if (
                request.expected_revision
                != state["current_revision"]
            ):
                raise FactRevisionConflict(
                    "expected revision %d, current revision %d"
                    % (
                        request.expected_revision,
                        state["current_revision"],
                    )
                )

            fence = self.temporal_repo.latest_erasure_fence(
                conn, event.identity_id, fact_key
            )
            if (
                fence is not None
                and request.operation
                != FactMutationOperation.DELETE
                and fence["source_ingest_revision"] is not None
                and source_ingest_revision
                <= int(fence["source_ingest_revision"])
            ):
                raise DeletedFactReplay(
                    "source predates fact deletion fence"
                )

            if (
                source_ingest_revision
                < state["last_source_ingest_revision"]
            ):
                raise StaleSourceEvent(
                    "older source event cannot overwrite newer authority"
                )

            revision = state["current_revision"] + 1
            erasure_generation = state["erasure_generation"]
            valid_from = self._utc(
                request.valid_from or event.observed_at
            )
            valid_to = (
                None
                if request.valid_to is None
                else self._utc(request.valid_to)
            )
            if (
                valid_to is not None
                and valid_to <= valid_from
            ):
                raise FactMutationError(
                    "valid interval is half-open and requires valid_to > valid_from"
                )

            claim_id = self._claim_id(request)
            self.claim_repo.insert(
                conn,
                claim_id=claim_id,
                event=event,
                subject=request.subject,
                predicate=request.predicate,
                value=request.value,
                confidence=1.0,
                status="CONFIRMED",
                created_at=at,
                mutation_id=request.mutation_id,
                principal_scope=principal_scope,
                decision_reason=(
                    "AUTHENTICATED_OWNER_"
                    + request.operation.value
                ),
            )

            fact_id = self._apply_operation(
                conn=conn,
                request=request,
                event=event,
                fact_key=fact_key,
                claim_id=claim_id,
                principal_scope=principal_scope,
                revision=revision,
                valid_from=valid_from,
                valid_to=valid_to,
                recorded_at=at,
            )

            if request.operation == FactMutationOperation.DELETE:
                erasure_generation = max(
                    erasure_generation + 1,
                    self.temporal_repo.next_erasure_generation(
                        conn, event.identity_id
                    ),
                )
                self.temporal_repo.insert_erasure_fence(
                    conn,
                    erasure_id="erasure:" + request.mutation_id,
                    identity_id=event.identity_id,
                    fact_key=fact_key,
                    generation=erasure_generation,
                    source_event_id=event.event_id,
                    source_ingest_revision=
                        source_ingest_revision,
                    mutation_id=request.mutation_id,
                    created_at=at,
                )

            self.temporal_repo.update_revision(
                conn,
                identity_id=event.identity_id,
                fact_key=fact_key,
                revision=revision,
                source_ingest_revision=source_ingest_revision,
                erasure_generation=erasure_generation,
                updated_at=at,
            )
            self.temporal_repo.record_mutation(
                conn,
                mutation_id=request.mutation_id,
                identity_id=event.identity_id,
                source_event_id=event.event_id,
                source_ingest_revision=source_ingest_revision,
                claim_id=claim_id,
                fact_key=fact_key,
                operation=request.operation.value,
                mutation_digest=mutation_digest,
                expected_revision=request.expected_revision,
                result_revision=revision,
                request_json=canonical_json(request.to_dict()),
                created_at=at,
            )
            self.temporal_repo.invalidate_projection(
                conn,
                identity_id=event.identity_id,
                fact_key=fact_key,
                revision=revision,
                erasure_generation=erasure_generation,
                mutation_id=request.mutation_id,
                invalidated_at=at,
            )

            return FactMutationResult(
                request.mutation_id,
                fact_key,
                revision,
                erasure_generation,
                fact_id,
            )

    def _apply_operation(
        self,
        *,
        conn,
        request: FactMutationRequest,
        event,
        fact_key: str,
        claim_id: str,
        principal_scope: str,
        revision: int,
        valid_from: datetime,
        valid_to: Optional[datetime],
        recorded_at: datetime,
    ) -> Optional[str]:
        current = self.temporal_repo.current_facts(
            conn, event.identity_id, fact_key
        )

        if request.operation == FactMutationOperation.DELETE:
            self.temporal_repo.set_all_fact_state(
                conn,
                event.identity_id,
                fact_key,
                "DELETED",
            )
            return None

        if request.operation == FactMutationOperation.RETRACT:
            if request.cardinality == FactCardinality.SINGLE:
                if len(current) != 1:
                    raise FactConflict(
                        "single fact retract requires exactly one current fact"
                    )
                target = current[0]
            else:
                target = self._resolve_set_target(
                    conn,
                    event.identity_id,
                    fact_key,
                    request,
                )
            self.temporal_repo.set_fact_state(
                conn,
                str(target["fact_id"]),
                "RETRACTED",
                valid_to=valid_from,
            )
            return None

        if request.operation == FactMutationOperation.CORRECT:
            if request.cardinality != FactCardinality.SINGLE:
                raise FactConflict(
                    "SET correction requires retract + assert in v1"
                )
            if len(current) != 1:
                raise FactConflict(
                    "single correction requires exactly one current fact"
                )
            previous = current[0]
            corrected_from = (
                valid_from
                if request.valid_from is not None
                else datetime_from_text(
                    str(previous["valid_from"]),
                    "valid_from",
                )
            )
            self.temporal_repo.set_fact_state(
                conn,
                str(previous["fact_id"]),
                "SUPERSEDED",
            )
            fact_id = self._fact_id(
                request.mutation_id, fact_key
            )
            self.temporal_repo.insert_fact(
                conn,
                fact_id=fact_id,
                identity_id=event.identity_id,
                claim_id=claim_id,
                fact_key=fact_key,
                principal_scope=principal_scope,
                context_space=event.context_space,
                cardinality=request.cardinality.value,
                subject=request.subject,
                predicate=request.predicate,
                value=request.value,
                valid_from=corrected_from,
                valid_to=valid_to,
                recorded_at=recorded_at,
                revision=revision,
                mutation_id=request.mutation_id,
                supersedes_fact_id=str(previous["fact_id"]),
            )
            return fact_id

        if request.operation != FactMutationOperation.ASSERT:
            raise FactMutationError(
                "unsupported operation %s"
                % request.operation.value
            )

        if request.cardinality == FactCardinality.SET:
            duplicate = self.temporal_repo.current_fact_by_value(
                conn,
                event.identity_id,
                fact_key,
                request.value,
            )
            if duplicate is not None:
                raise FactConflict(
                    "set value is already current"
                )
            fact_id = self._fact_id(
                request.mutation_id, fact_key
            )
            self.temporal_repo.insert_fact(
                conn,
                fact_id=fact_id,
                identity_id=event.identity_id,
                claim_id=claim_id,
                fact_key=fact_key,
                principal_scope=principal_scope,
                context_space=event.context_space,
                cardinality=request.cardinality.value,
                subject=request.subject,
                predicate=request.predicate,
                value=request.value,
                valid_from=valid_from,
                valid_to=valid_to,
                recorded_at=recorded_at,
                revision=revision,
                mutation_id=request.mutation_id,
            )
            return fact_id

        if len(current) > 1:
            raise FactConflict(
                "single fact invariant violated: multiple current facts"
            )
        if len(current) == 1:
            previous = current[0]
            previous_value = canonical_json(
                json.loads(previous["value_json"])
            )
            if previous_value == canonical_json(request.value):
                raise FactConflict(
                    "same single fact value is already current"
                )
            previous_from = datetime_from_text(
                str(previous["valid_from"]),
                "valid_from",
            )
            if valid_from <= previous_from:
                raise FactConflict(
                    "overlapping single fact requires CORRECT"
                )
            self.temporal_repo.set_fact_state(
                conn,
                str(previous["fact_id"]),
                "HISTORICAL",
                valid_to=valid_from,
            )
            supersedes = str(previous["fact_id"])
        else:
            supersedes = None

        fact_id = self._fact_id(
            request.mutation_id, fact_key
        )
        self.temporal_repo.insert_fact(
            conn,
            fact_id=fact_id,
            identity_id=event.identity_id,
            claim_id=claim_id,
            fact_key=fact_key,
            principal_scope=principal_scope,
            context_space=event.context_space,
            cardinality=request.cardinality.value,
            subject=request.subject,
            predicate=request.predicate,
            value=request.value,
            valid_from=valid_from,
            valid_to=valid_to,
            recorded_at=recorded_at,
            revision=revision,
            mutation_id=request.mutation_id,
            supersedes_fact_id=supersedes,
        )
        return fact_id

    def _resolve_set_target(
        self,
        conn,
        identity_id: str,
        fact_key: str,
        request: FactMutationRequest,
    ):
        if request.target_fact_id is not None:
            row = conn.execute(
                """SELECT * FROM temporal_facts
                   WHERE fact_id=? AND identity_id=? AND fact_key=?
                     AND status='CURRENT'""",
                (
                    request.target_fact_id,
                    identity_id,
                    fact_key,
                ),
            ).fetchone()
        else:
            row = self.temporal_repo.current_fact_by_value(
                conn,
                identity_id,
                fact_key,
                request.value,
            )
        if row is None:
            raise FactConflict(
                "set retract target is not current"
            )
        return row

    def get_fact_at_time(
        self,
        *,
        identity_id: str,
        fact_key: str,
        at: datetime,
    ) -> list[dict]:
        """Valid-time query only; this is not a transaction-time query."""
        query_time = self._utc(at)
        with self.db.transaction() as conn:
            rows = self.temporal_repo.facts_at(
                conn,
                identity_id,
                fact_key,
                query_time,
            )
            return [dict(row) for row in rows]

    def rebuild_into(
        self,
        target_db: Database,
        *,
        identity_id: str,
    ) -> dict:
        if target_db.path.resolve() == self.db.path.resolve():
            raise ValueError("rebuild target must be a different database")
        apply_migrations(target_db)

        with self.db.transaction() as source_conn:
            events = self.event_repo.list_ingest_order(
                source_conn, identity_id
            )
            mutations = self.temporal_repo.ordered_mutations(
                source_conn, identity_id
            )

        target_event_repo = CanonicalEventRepository()
        with target_db.transaction(immediate=True) as target_conn:
            for event in events:
                target_event_repo.append_or_get(
                    target_conn, event
                )

        target_service = TemporalFactService(target_db)
        replayed = 0
        for row in mutations:
            request_json = row["request_json"]
            if request_json is None:
                raise FactMutationError(
                    "mutation %s lacks replay request"
                    % row["mutation_id"]
                )
            request = FactMutationRequest.from_dict(
                json.loads(request_json)
            )
            target_service.apply(
                request,
                created_at=datetime_from_text(
                    str(row["created_at"]),
                    "created_at",
                ),
            )
            replayed += 1

        return {
            "events": len(events),
            "mutations": replayed,
            "snapshot": target_service.authority_snapshot(
                identity_id=identity_id
            ),
        }

    def authority_snapshot(
        self,
        *,
        identity_id: str,
    ) -> dict:
        with self.db.transaction() as conn:
            facts = [
                dict(row)
                for row in conn.execute(
                    """SELECT fact_id,fact_key,value_json,valid_from,valid_to,
                              status,supersedes_fact_id,revision,mutation_id
                       FROM temporal_facts
                       WHERE identity_id=?
                       ORDER BY fact_key,revision,fact_id""",
                    (identity_id,),
                ).fetchall()
            ]
            revisions = [
                dict(row)
                for row in conn.execute(
                    """SELECT fact_key,current_revision,
                              last_source_ingest_revision,
                              erasure_generation
                       FROM fact_authority_revisions
                       WHERE identity_id=?
                       ORDER BY fact_key""",
                    (identity_id,),
                ).fetchall()
            ]
            fences = [
                dict(row)
                for row in conn.execute(
                    """SELECT target_id,erasure_generation,
                              source_ingest_revision,mutation_id
                       FROM erasure_tombstones
                       WHERE identity_id=? AND target_type='fact_key'
                       ORDER BY erasure_generation,target_id""",
                    (identity_id,),
                ).fetchall()
            ]
            invalidations = [
                dict(row)
                for row in conn.execute(
                    """SELECT fact_key,source_revision,
                              erasure_generation,mutation_id
                       FROM projection_invalidations
                       WHERE identity_id=?
                       ORDER BY fact_key,source_revision""",
                    (identity_id,),
                ).fetchall()
            ]
        return {
            "facts": facts,
            "revisions": revisions,
            "fences": fences,
            "invalidations": invalidations,
        }

    def freshness(
        self,
        *,
        identity_id: str,
        fact_key: str,
    ) -> dict:
        with self.db.transaction() as conn:
            return self.temporal_repo.revision_state(
                conn, identity_id, fact_key
            )
