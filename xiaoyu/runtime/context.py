from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Optional

from xiaoyu.contracts.common import canonical_json
from xiaoyu.core.memory import (
    AdaptiveMemoryUseGate,
    FidelityClass,
    MemoryRetriever,
    MemoryUseDecision,
)
from xiaoyu.core.profile import ProfileService
from xiaoyu.core.relationship import RelationshipService
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.context import MemoryContextRepository
from xiaoyu.persistence.repositories.events import CanonicalEventRepository


@dataclass(frozen=True)
class ContextBlock:
    kind: str
    fidelity: FidelityClass
    payload: Any
    source_ids: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class ContextRequest:
    identity_id: str
    principal_id: str
    audience_scope: str
    context_space: str
    turn_text: str
    identity_block: dict[str, Any]
    explicit_recall: bool = False
    continuation: bool = False
    include_lossy_summaries: bool = True
    max_memory_facts: int = 6
    max_summaries: int = 2
    viewer_principal_ids: tuple[str, ...] = ()
    shared_identity_block: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class AssembledContext:
    memory_decision: MemoryUseDecision
    memory_reason: str
    blocks: tuple[ContextBlock, ...]


class ContextSummaryError(RuntimeError):
    pass


class ContextSummaryService:
    BUILDER_VERSION = "r11.summary.v1"

    def __init__(
        self,
        db: Database,
        repository=None,
        event_repository=None,
    ) -> None:
        self.db = db
        self.repository = repository or MemoryContextRepository()
        self.event_repository = (
            event_repository or CanonicalEventRepository()
        )

    def create(
        self,
        *,
        summary_id: str,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        audience_scope: str,
        summary_text: str,
        source_event_ids: list[str],
        fidelity_class: FidelityClass = FidelityClass.LOSSY_ALLOWED,
        created_at: Optional[datetime] = None,
    ) -> str:
        if fidelity_class != FidelityClass.LOSSY_ALLOWED:
            raise ContextSummaryError(
                "only LOSSY_ALLOWED content may become a summary projection"
            )
        if not summary_text.strip():
            raise ContextSummaryError("summary_text is required")
        if not source_event_ids:
            raise ContextSummaryError(
                "summary needs canonical source events"
            )
        if len(set(source_event_ids)) != len(source_event_ids):
            raise ContextSummaryError("duplicate source event ids")
        at = created_at or datetime.now(timezone.utc)

        with self.db.transaction(immediate=True) as conn:
            rows = self.repository.source_events(
                conn, source_event_ids
            )
            if len(rows) != len(source_event_ids):
                raise ContextSummaryError(
                    "all summary sources must be canonical events"
                )
            evidence = []
            for row in rows:
                if str(row["identity_id"]) != identity_id:
                    raise ContextSummaryError(
                        "summary source identity mismatch"
                    )
                if str(row["context_space"]) != context_space:
                    raise ContextSummaryError(
                        "summary source context mismatch"
                    )
                if str(row["audience_scope"]) != audience_scope:
                    raise ContextSummaryError(
                        "summary cannot widen/narrow source audience"
                    )
                row_principal = row["principal_id"]
                if (
                    row_principal is not None
                    and str(row_principal) != principal_scope
                ):
                    raise ContextSummaryError(
                        "summary source principal mismatch"
                    )
                evidence.append(
                    {
                        "event_id": str(row["event_id"]),
                        "semantic_digest": str(
                            row["semantic_digest"] or ""
                        ),
                    }
                )

            source_revision, erasure_generation = (
                self.repository.authority_freshness(
                    conn, identity_id=identity_id
                )
            )
            source_digest = "sha256:" + hashlib.sha256(
                canonical_json(evidence).encode("utf-8")
            ).hexdigest()
            self.repository.insert_summary(
                conn,
                summary_id=summary_id,
                identity_id=identity_id,
                principal_scope=principal_scope,
                context_space=context_space,
                audience_scope=audience_scope,
                fidelity_class=fidelity_class.value,
                summary_text=summary_text.strip(),
                source_event_ids=source_event_ids,
                source_digest=source_digest,
                source_revision=source_revision,
                erasure_generation=erasure_generation,
                builder_version=self.BUILDER_VERSION,
                created_at=at,
            )
        return summary_id

    def fresh(
        self,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        audience_scope: str,
        limit: int = 2,
    ) -> list[dict]:
        with self.db.transaction() as conn:
            current_revision, current_erasure = (
                self.repository.authority_freshness(
                    conn, identity_id=identity_id
                )
            )
            rows = self.repository.summaries_for_scope(
                conn,
                identity_id=identity_id,
                principal_scope=principal_scope,
                context_space=context_space,
                audience_scope=audience_scope,
                limit=limit,
            )
            result = []
            for row in rows:
                if (
                    str(row["builder_version"]) != self.BUILDER_VERSION
                    or int(row["source_revision"]) != current_revision
                    or int(row["erasure_generation"]) != current_erasure
                ):
                    continue
                item = dict(row)
                item["source_event_ids"] = json.loads(
                    item.pop("source_event_ids_json")
                )
                result.append(item)
            return result


class ContextAssembler:
    def __init__(
        self,
        db: Database,
        *,
        gate=None,
        retriever=None,
        repository=None,
        profile_service=None,
        relationship_service=None,
        summary_service=None,
    ) -> None:
        self.db = db
        self.gate = gate or AdaptiveMemoryUseGate()
        self.repository = repository or MemoryContextRepository()
        self.retriever = retriever or MemoryRetriever(
            db, repository=self.repository
        )
        self.profile_service = profile_service or ProfileService(db)
        self.relationship_service = (
            relationship_service or RelationshipService(db)
        )
        self.summary_service = (
            summary_service
            or ContextSummaryService(
                db, repository=self.repository
            )
        )

    @staticmethod
    def _allowed_audiences(audience_scope: str) -> tuple[str, ...]:
        normalized = audience_scope.upper()
        if normalized in {"PRIVATE", "OWNER_PRIVATE"}:
            return ("PRIVATE", "OWNER_PRIVATE")
        if normalized in {"GROUP", "GROUP_SHARED"}:
            return ("GROUP", "GROUP_SHARED")
        if normalized in {"SHARED", "SHARED_ACTIVITY"}:
            return ("SHARED", "SHARED_ACTIVITY", "GROUP_SHARED")
        if normalized == "GUEST":
            return ("GUEST", "PUBLIC")
        if normalized == "PUBLIC":
            return ("PUBLIC",)
        return ()

    @staticmethod
    def _is_private(audience_scope: str) -> bool:
        return audience_scope.upper() in {"PRIVATE", "OWNER_PRIVATE"}

    @classmethod
    def _identity_payload(cls, request: ContextRequest) -> dict[str, Any]:
        if cls._is_private(request.audience_scope):
            return dict(request.identity_block)
        # Non-private surfaces must not inherit an arbitrary owner-private
        # identity/persona blob. Additional fields require an explicitly
        # audience-safe projection from the caller.
        payload = {"identity_id": request.identity_id}
        if request.shared_identity_block is not None:
            payload.update(dict(request.shared_identity_block))
        payload["identity_id"] = request.identity_id
        return payload

    @staticmethod
    def _viewer_set(request: ContextRequest) -> tuple[str, ...]:
        values = set(request.viewer_principal_ids)
        if request.principal_id:
            values.add(request.principal_id)
        return tuple(sorted(str(value) for value in values if str(value)))

    @staticmethod
    def _block(
        kind: str,
        fidelity: FidelityClass,
        payload: Any,
        source_ids: tuple[str, ...] = (),
    ) -> ContextBlock:
        digest_payload = {
            "kind": kind,
            "fidelity": fidelity.value,
            "payload": payload,
            "source_ids": list(source_ids),
        }
        digest = "sha256:" + hashlib.sha256(
            canonical_json(digest_payload).encode("utf-8")
        ).hexdigest()
        return ContextBlock(
            kind=kind,
            fidelity=fidelity,
            payload=payload,
            source_ids=source_ids,
            digest=digest,
        )

    def assemble(
        self,
        request: ContextRequest,
        *,
        now: Optional[datetime] = None,
    ) -> AssembledContext:
        current = now or datetime.now(timezone.utc)
        allowed_audiences = self._allowed_audiences(
            request.audience_scope
        )
        private_scope = self._is_private(request.audience_scope)
        viewer_set = self._viewer_set(request)
        with self.db.transaction() as conn:
            active_purposes = self.repository.active_purposes(
                conn,
                identity_id=request.identity_id,
                principal_id=request.principal_id,
                context_space=request.context_space,
                allowed_audiences=allowed_audiences,
                private_scope=private_scope,
            )
            delegations = self.repository.active_delegations(
                conn,
                identity_id=request.identity_id,
                principal_id=request.principal_id,
                context_space=request.context_space,
                allowed_audiences=allowed_audiences,
                private_scope=private_scope,
                now=current,
            )
            corrections = self.repository.current_corrections(
                conn,
                identity_id=request.identity_id,
                principal_scope=request.principal_id,
                context_space=request.context_space,
                allowed_audiences=allowed_audiences,
            )
            unresolved = self.repository.unresolved_effects(
                conn,
                identity_id=request.identity_id,
                principal_id=request.principal_id,
                context_space=request.context_space,
                allowed_audiences=allowed_audiences,
                private_scope=private_scope,
            )

        gate_result = self.gate.decide(
            request.turn_text,
            explicit_recall=request.explicit_recall,
            continuation=request.continuation,
            active_purpose=bool(active_purposes),
        )

        blocks: list[ContextBlock] = [
            self._block(
                "IDENTITY",
                FidelityClass.NEVER_LOSSY,
                self._identity_payload(request),
            ),
            self._block(
                "AUDIENCE_BOUNDARY",
                FidelityClass.NEVER_LOSSY,
                {
                    "principal_id": request.principal_id,
                    "viewer_principal_ids": list(viewer_set),
                    "audience_scope": request.audience_scope,
                    "context_space": request.context_space,
                },
            ),
        ]

        if private_scope:
            relationship = self.relationship_service.get(
                identity_id=request.identity_id,
                principal_id=request.principal_id,
            )
            blocks.append(
                self._block(
                    "RELATIONSHIP_POLICY",
                    FidelityClass.NEVER_LOSSY,
                    {
                        "state": relationship.state.value,
                        "boundaries": relationship.value.get(
                            "boundaries", {}
                        ),
                        "interaction_norms": relationship.value.get(
                            "interaction_norms", {}
                        ),
                        "proactivity_policy": relationship.value.get(
                            "proactivity_policy", {}
                        ),
                    },
                    relationship.source_event_ids,
                )
            )

        if delegations:
            blocks.append(
                self._block(
                    "PERMISSIONS",
                    FidelityClass.NEVER_LOSSY,
                    [
                        {
                            "delegation_id": str(row["delegation_id"]),
                            "actor_id": str(row["actor_id"]),
                            "purpose_id": row["purpose_id"],
                            "scope": json.loads(row["scope_json"]),
                            "valid_from": str(row["valid_from"]),
                            "expires_at": row["expires_at"],
                        }
                        for row in delegations
                    ],
                    tuple(str(row["delegation_id"]) for row in delegations),
                )
            )

        if active_purposes:
            purpose_payload = []
            for row in active_purposes:
                item = {
                    "purpose_id": str(row["purpose_id"]),
                    "owner_type": str(row["owner_type"]),
                    "owner_id": row["owner_id"],
                    "state": str(row["state"]),
                    "kind": str(row["kind"]),
                    "revision": int(row["revision"]),
                    "resolved_utc_time": row["resolved_utc_time"],
                    "timezone": row["timezone"],
                }
                if private_scope:
                    item["payload"] = json.loads(row["payload_json"])
                purpose_payload.append(item)
            blocks.append(
                self._block(
                    "ACTIVE_PURPOSES",
                    FidelityClass.NEVER_LOSSY,
                    purpose_payload,
                    tuple(
                        str(row["purpose_id"])
                        for row in active_purposes
                    ),
                )
            )

        if corrections:
            blocks.append(
                self._block(
                    "CURRENT_CORRECTIONS",
                    FidelityClass.NEVER_LOSSY,
                    [
                        {
                            "fact_id": str(row["fact_id"]),
                            "predicate": str(row["predicate"]),
                            "value": json.loads(row["value_json"]),
                            "revision": int(row["revision"]),
                            "mutation_id": str(row["mutation_id"]),
                        }
                        for row in corrections
                    ],
                    tuple(str(row["fact_id"]) for row in corrections),
                )
            )

        if unresolved:
            effect_payload = []
            for row in unresolved:
                item = {
                    "effect_id": str(row["effect_id"]),
                    "purpose_id": row["purpose_id"],
                    "actor_id": str(row["actor_id"]),
                    "action_class": str(row["action_class"]),
                    "dispatch_state": str(row["dispatch_state"]),
                }
                if private_scope:
                    item["request"] = json.loads(row["request_json"])
                effect_payload.append(item)
            blocks.append(
                self._block(
                    "UNRESOLVED_EFFECTS",
                    FidelityClass.NEVER_LOSSY,
                    effect_payload,
                    tuple(str(row["effect_id"]) for row in unresolved),
                )
            )

        if gate_result.decision == MemoryUseDecision.USE:
            candidates = self.retriever.retrieve(
                identity_id=request.identity_id,
                principal_scope=request.principal_id,
                context_space=request.context_space,
                allowed_audiences=allowed_audiences,
                query=request.turn_text,
                limit=request.max_memory_facts,
            )
            if candidates:
                blocks.append(
                    self._block(
                        "MEMORY_FACTS",
                        FidelityClass.QUERY_TIME_SELECT,
                        [
                            {
                                "fact_id": item.fact_id,
                                "predicate": item.predicate,
                                "value": item.value,
                                "revision": item.revision,
                                "relevance": item.relevance,
                            }
                            for item in candidates
                        ],
                        tuple(item.fact_id for item in candidates),
                    )
                )

            if private_scope:
                profile = self.profile_service.read_fresh(
                    identity_id=request.identity_id,
                    principal_scope=request.principal_id,
                    context_space=request.context_space,
                )
                if profile is not None and profile.fields:
                    blocks.append(
                        self._block(
                            "PROFILE",
                            FidelityClass.QUERY_TIME_SELECT,
                            {
                                "fields": profile.fields,
                                "source_revision":
                                    profile.source_revision,
                                "erasure_generation":
                                    profile.erasure_generation,
                            },
                            profile.source_fact_ids,
                        )
                    )

            if request.include_lossy_summaries:
                summaries = self.summary_service.fresh(
                    identity_id=request.identity_id,
                    principal_scope=request.principal_id,
                    context_space=request.context_space,
                    audience_scope=request.audience_scope,
                    limit=request.max_summaries,
                )
                for summary in summaries:
                    blocks.append(
                        self._block(
                            "SUMMARY",
                            FidelityClass.LOSSY_ALLOWED,
                            {
                                "summary_id": str(
                                    summary["summary_id"]
                                ),
                                "text": str(summary["summary_text"]),
                                "builder_version": str(
                                    summary["builder_version"]
                                ),
                            },
                            tuple(summary["source_event_ids"]),
                        )
                    )

        return AssembledContext(
            memory_decision=gate_result.decision,
            memory_reason=gate_result.reason,
            blocks=tuple(blocks),
        )
