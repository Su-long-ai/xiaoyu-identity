from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Optional

from xiaoyu.contracts.common import StringEnum, canonical_json
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.context import MemoryContextRepository
from xiaoyu.core.temporal import (
    FactCardinality,
    FactMutationOperation,
    FactMutationRequest,
    TemporalFactService,
)


class MemoryUseDecision(StringEnum):
    USE = "USE"
    ABSTAIN = "ABSTAIN"


class FidelityClass(StringEnum):
    NEVER_LOSSY = "NEVER_LOSSY"
    QUERY_TIME_SELECT = "QUERY_TIME_SELECT"
    LOSSY_ALLOWED = "LOSSY_ALLOWED"


@dataclass(frozen=True)
class MemoryGateResult:
    decision: MemoryUseDecision
    reason: str


@dataclass(frozen=True)
class MemoryCandidate:
    fact_id: str
    fact_key: str
    subject: str
    predicate: str
    value: Any
    revision: int
    relevance: float
    audience_scope: str


class AdaptiveMemoryUseGate:
    """Cheap conservative gate that runs before retrieval."""

    CASUAL = {
        "hi", "hello", "hey", "thanks", "thank you", "ok", "okay",
        "你好", "嗨", "谢谢", "好的", "好", "嗯", "行", "收到",
    }
    RECALL_CUES = (
        "remember", "last time", "before", "previously",
        "my preference", "what did i", "what do i like",
        "记得", "还记得", "之前", "上次", "以前", "我的偏好",
        "我喜欢", "我住", "我说过", "你记得",
    )
    CONTINUATION_CUES = (
        "continue", "resume", "pick up", "接着", "继续", "上次那个",
    )

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.strip().lower().split())

    def decide(
        self,
        text: str,
        *,
        explicit_recall: bool = False,
        continuation: bool = False,
        active_purpose: bool = False,
    ) -> MemoryGateResult:
        normalized = self._normalize(text)
        if explicit_recall:
            return MemoryGateResult(
                MemoryUseDecision.USE,
                "EXPLICIT_RECALL",
            )
        if any(cue in normalized for cue in self.RECALL_CUES):
            return MemoryGateResult(
                MemoryUseDecision.USE,
                "RECALL_CUE",
            )
        if continuation or any(
            cue in normalized for cue in self.CONTINUATION_CUES
        ):
            if active_purpose:
                return MemoryGateResult(
                    MemoryUseDecision.USE,
                    "ACTIVE_PURPOSE_CONTINUATION",
                )
        if normalized in self.CASUAL or not normalized:
            return MemoryGateResult(
                MemoryUseDecision.ABSTAIN,
                "CASUAL_OR_EMPTY",
            )
        return MemoryGateResult(
            MemoryUseDecision.ABSTAIN,
            "NO_MEMORY_SIGNAL",
        )


class MemoryRetriever:
    def __init__(self, db: Database, repository=None) -> None:
        self.db = db
        self.repository = repository or MemoryContextRepository()

    @staticmethod
    def _units(text: str) -> set[str]:
        normalized = text.lower()
        words = set(re.findall(r"[a-z0-9_]+", normalized))
        cjk = "".join(
            ch for ch in normalized
            if "\u4e00" <= ch <= "\u9fff"
        )
        chars = set(cjk)
        bigrams = {
            cjk[index:index + 2]
            for index in range(max(0, len(cjk) - 1))
        }
        return words | chars | bigrams

    def retrieve(
        self,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str,
        allowed_audiences: tuple[str, ...],
        query: str,
        limit: int = 6,
    ) -> list[MemoryCandidate]:
        with self.db.transaction() as conn:
            rows = self.repository.current_fact_candidates(
                conn,
                identity_id=identity_id,
                principal_scope=principal_scope,
                context_space=context_space,
                allowed_audiences=allowed_audiences,
            )

        query_units = self._units(query)
        candidates: list[MemoryCandidate] = []
        for row in rows:
            value = json.loads(row["value_json"])
            searchable = " ".join(
                (
                    str(row["subject"]),
                    str(row["predicate"]),
                    canonical_json(value),
                )
            )
            candidate_units = self._units(searchable)
            overlap = len(query_units.intersection(candidate_units))
            relevance = (
                float(overlap) / float(max(1, len(query_units)))
                if query_units
                else 0.0
            )
            candidates.append(
                MemoryCandidate(
                    fact_id=str(row["fact_id"]),
                    fact_key=str(row["fact_key"]),
                    subject=str(row["subject"]),
                    predicate=str(row["predicate"]),
                    value=value,
                    revision=int(row["revision"]),
                    relevance=relevance,
                    audience_scope=str(row["audience_scope"]),
                )
            )

        candidates.sort(
            key=lambda item: (
                -item.relevance,
                -item.revision,
                item.predicate,
                item.fact_id,
            )
        )
        return candidates[: max(1, min(int(limit), 50))]



CANONICAL_MEMORY_PREDICATE = "remembered_item"


@dataclass(frozen=True)
class CanonicalMemoryItem:
    memory_id: str
    fact_id: str
    fact_key: str
    revision: int
    text: str
    category: str
    priority: int
    source_event_id: str


class CanonicalMemoryService:
    """Product memory API backed entirely by R9 temporal authority."""

    CATEGORIES = {
        "shared",
        "preference",
        "relationship",
        "project",
        "other",
    }

    def __init__(
        self,
        db: Database,
        *,
        temporal_service: Optional[TemporalFactService] = None,
    ) -> None:
        self.db = db
        self.temporal_service = (
            temporal_service or TemporalFactService(db)
        )

    @staticmethod
    def subject(memory_id: str) -> str:
        value = str(memory_id).strip()
        if not value:
            raise ValueError("memory_id is required")
        return "memory:" + value

    @classmethod
    def _value(
        cls,
        *,
        memory_id: str,
        text: str,
        category: str,
        priority: int,
    ) -> dict:
        clean = str(text).strip()
        if not 2 <= len(clean) <= 1500:
            raise ValueError("memory text must be 2-1500 characters")
        normalized_category = str(category).strip().lower()
        if normalized_category == "legacy":
            normalized_category = "other"
        if normalized_category not in cls.CATEGORIES:
            normalized_category = "other"
        p = int(priority)
        if not 1 <= p <= 5:
            raise ValueError("priority must be between 1 and 5")
        return {
            "memory_id": str(memory_id),
            "text": clean,
            "category": normalized_category,
            "priority": p,
        }

    def _mutate(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        operation: FactMutationOperation,
        expected_revision: int,
        value: Optional[dict],
        created_at: Optional[datetime],
    ):
        return self.temporal_service.apply(
            FactMutationRequest(
                mutation_id=mutation_id,
                source_event_id=source_event_id,
                authenticated_principal_id=principal_id,
                subject=self.subject(memory_id),
                predicate=CANONICAL_MEMORY_PREDICATE,
                operation=operation,
                expected_revision=int(expected_revision),
                value=value,
                cardinality=FactCardinality.SINGLE,
                principal_scope=principal_id,
            ),
            created_at=created_at or datetime.now(timezone.utc),
        )

    def save(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        text: str,
        category: str = "shared",
        priority: int = 3,
        created_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        value = self._value(
            memory_id=memory_id,
            text=text,
            category=category,
            priority=priority,
        )
        result = self._mutate(
            memory_id=memory_id,
            mutation_id=mutation_id,
            source_event_id=source_event_id,
            principal_id=principal_id,
            operation=FactMutationOperation.ASSERT,
            expected_revision=0,
            value=value,
            created_at=created_at,
        )
        return self.get(memory_id, result.fact_key)

    def correct(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        expected_revision: int,
        text: str,
        category: str,
        priority: int,
        created_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        value = self._value(
            memory_id=memory_id,
            text=text,
            category=category,
            priority=priority,
        )
        result = self._mutate(
            memory_id=memory_id,
            mutation_id=mutation_id,
            source_event_id=source_event_id,
            principal_id=principal_id,
            operation=FactMutationOperation.CORRECT,
            expected_revision=expected_revision,
            value=value,
            created_at=created_at,
        )
        return self.get(memory_id, result.fact_key)

    def retract(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        expected_revision: int,
        created_at: Optional[datetime] = None,
    ):
        return self._mutate(
            memory_id=memory_id,
            mutation_id=mutation_id,
            source_event_id=source_event_id,
            principal_id=principal_id,
            operation=FactMutationOperation.RETRACT,
            expected_revision=expected_revision,
            value=None,
            created_at=created_at,
        )

    def delete(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        expected_revision: int,
        created_at: Optional[datetime] = None,
    ):
        return self._mutate(
            memory_id=memory_id,
            mutation_id=mutation_id,
            source_event_id=source_event_id,
            principal_id=principal_id,
            operation=FactMutationOperation.DELETE,
            expected_revision=expected_revision,
            value=None,
            created_at=created_at,
        )

    def get(
        self,
        memory_id: str,
        fact_key: Optional[str] = None,
    ) -> CanonicalMemoryItem:
        with self.db.transaction() as conn:
            if fact_key is None:
                row = conn.execute(
                    """SELECT tf.*,c.source_event_id
                       FROM temporal_facts tf
                       JOIN claims c ON c.claim_id=tf.claim_id
                       WHERE tf.subject=?
                         AND tf.predicate=?
                         AND tf.status='CURRENT'
                       ORDER BY tf.revision DESC LIMIT 1""",
                    (
                        self.subject(memory_id),
                        CANONICAL_MEMORY_PREDICATE,
                    ),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT tf.*,c.source_event_id
                       FROM temporal_facts tf
                       JOIN claims c ON c.claim_id=tf.claim_id
                       WHERE tf.fact_key=? AND tf.status='CURRENT'
                       ORDER BY tf.revision DESC LIMIT 1""",
                    (fact_key,),
                ).fetchone()
        if row is None:
            raise KeyError("active canonical memory not found")
        value = json.loads(str(row["value_json"]))
        return CanonicalMemoryItem(
            memory_id=str(value["memory_id"]),
            fact_id=str(row["fact_id"]),
            fact_key=str(row["fact_key"]),
            revision=int(row["revision"]),
            text=str(value["text"]),
            category=str(value["category"]),
            priority=int(value["priority"]),
            source_event_id=str(row["source_event_id"]),
        )

    def list_current(
        self,
        *,
        identity_id: str,
        principal_scope: str,
        context_space: str = "PERSONAL",
    ) -> list[CanonicalMemoryItem]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                """SELECT tf.*,c.source_event_id
                   FROM temporal_facts tf
                   JOIN claims c ON c.claim_id=tf.claim_id
                   WHERE tf.identity_id=?
                     AND tf.principal_scope=?
                     AND tf.context_space=?
                     AND tf.predicate=?
                     AND tf.subject LIKE 'memory:%'
                     AND tf.status='CURRENT'
                   ORDER BY tf.recorded_at,tf.fact_id""",
                (
                    identity_id,
                    principal_scope,
                    context_space,
                    CANONICAL_MEMORY_PREDICATE,
                ),
            ).fetchall()
        result = []
        for row in rows:
            value = json.loads(str(row["value_json"]))
            result.append(
                CanonicalMemoryItem(
                    memory_id=str(value["memory_id"]),
                    fact_id=str(row["fact_id"]),
                    fact_key=str(row["fact_key"]),
                    revision=int(row["revision"]),
                    text=str(value["text"]),
                    category=str(value["category"]),
                    priority=int(value["priority"]),
                    source_event_id=str(row["source_event_id"]),
                )
            )
        return result
