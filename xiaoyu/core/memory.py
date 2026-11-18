from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import sqlite3
from typing import Any, Optional, Protocol, Sequence

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


class RetrievalRankerError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemorySearchDocument:
    fact_id: str
    text: str
    revision: int


class MemoryRanker(Protocol):
    def rank(
        self,
        documents: Sequence[MemorySearchDocument],
        query: str,
        *,
        limit: int,
    ) -> list[str]:
        ...


def reciprocal_rank_scores(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = 60,
) -> dict[str, float]:
    scores: Counter[str] = Counter()
    for ranking in rankings:
        seen = set()
        for position, value in enumerate(ranking, 1):
            fact_id = str(value)
            if fact_id in seen:
                continue
            seen.add(fact_id)
            scores[fact_id] += 1.0 / float(k + position)
    return dict(scores)


class SQLiteFTS5MemoryRanker:
    """Ephemeral lexical ranking over already-authorized candidate facts.

    SQLite owns the inverted index/tokenization. No lexical posting structure
    is maintained by XiaoYu. The index is transient so correction/delete
    semantics continue to come solely from the R9 candidate query.
    """

    def __init__(self, *, source_depth: int = 100) -> None:
        self.source_depth = max(1, min(int(source_depth), 1000))

    @staticmethod
    def _quoted_or(terms: Sequence[str]) -> str:
        clean = []
        seen = set()
        for value in terms:
            term = str(value).strip()
            if not term or term in seen:
                continue
            seen.add(term)
            clean.append('"' + term.replace('"', '""') + '"')
        return " OR ".join(clean)

    @staticmethod
    def _english_terms(query: str) -> list[str]:
        return re.findall(r"[a-z0-9_]{2,}", str(query).casefold())[:32]

    @staticmethod
    def _cjk_trigrams(query: str) -> list[str]:
        result = []
        seen = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", str(query)):
            for index in range(max(0, len(run) - 2)):
                token = run[index:index + 3]
                if token not in seen:
                    seen.add(token)
                    result.append(token)
                    if len(result) >= 48:
                        return result
        return result

    def _query(
        self,
        conn: sqlite3.Connection,
        table: str,
        expression: str,
    ) -> list[str]:
        if not expression:
            return []
        try:
            rows = conn.execute(
                "SELECT fact_id,bm25(%s) AS score "
                "FROM %s WHERE %s MATCH ? "
                "ORDER BY score,fact_id LIMIT ?"
                % (table, table, table),
                (expression, self.source_depth),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise RetrievalRankerError(
                "SQLite FTS5 lexical ranking failed"
            ) from exc
        return [str(row[0]) for row in rows]

    def rank(
        self,
        documents: Sequence[MemorySearchDocument],
        query: str,
        *,
        limit: int,
    ) -> list[str]:
        docs = list(documents)
        if not docs or not str(query).strip():
            return []
        conn = sqlite3.connect(":memory:")
        try:
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE words USING "
                    "fts5(fact_id UNINDEXED, content, tokenize='unicode61')"
                )
                conn.execute(
                    "CREATE VIRTUAL TABLE grams USING "
                    "fts5(fact_id UNINDEXED, content, tokenize='trigram')"
                )
            except sqlite3.OperationalError as exc:
                raise RetrievalRankerError(
                    "SQLite runtime does not provide required FTS5 tokenizers"
                ) from exc

            payload = [(doc.fact_id, doc.text) for doc in docs]
            conn.executemany(
                "INSERT INTO words(fact_id,content) VALUES(?,?)",
                payload,
            )
            conn.executemany(
                "INSERT INTO grams(fact_id,content) VALUES(?,?)",
                payload,
            )
            word_rank = self._query(
                conn,
                "words",
                self._quoted_or(self._english_terms(query)),
            )
            trigram_rank = self._query(
                conn,
                "grams",
                self._quoted_or(self._cjk_trigrams(query)),
            )
        finally:
            conn.close()

        scores = reciprocal_rank_scores((word_rank, trigram_rank))
        ranked = sorted(
            scores,
            key=lambda fact_id: (-scores[fact_id], fact_id),
        )
        return ranked[: max(1, min(int(limit), self.source_depth))]


class MemoryRetriever:
    def __init__(
        self,
        db: Database,
        repository=None,
        *,
        lexical_ranker: Optional[MemoryRanker] = None,
        semantic_ranker: Optional[MemoryRanker] = None,
    ) -> None:
        self.db = db
        self.repository = repository or MemoryContextRepository()
        self.lexical_ranker = lexical_ranker or SQLiteFTS5MemoryRanker()
        self.semantic_ranker = semantic_ranker

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

        candidates: list[MemoryCandidate] = []
        documents: list[MemorySearchDocument] = []
        for row in rows:
            value = json.loads(row["value_json"])
            if str(row["predicate"]) == CANONICAL_MEMORY_PREDICATE:
                control_state = MemoryControlState(
                    value.get(
                        "control_state",
                        MemoryControlState.NORMAL.value,
                    )
                )
                if (
                    control_state is MemoryControlState.MUTED
                    or bool(value.get("archived", False))
                ):
                    continue
            fact_id = str(row["fact_id"])
            searchable = " ".join(
                (
                    str(row["subject"]),
                    str(row["predicate"]),
                    canonical_json(value),
                )
            )
            documents.append(
                MemorySearchDocument(
                    fact_id=fact_id,
                    text=searchable,
                    revision=int(row["revision"]),
                )
            )
            candidates.append(
                MemoryCandidate(
                    fact_id=fact_id,
                    fact_key=str(row["fact_key"]),
                    subject=str(row["subject"]),
                    predicate=str(row["predicate"]),
                    value=value,
                    revision=int(row["revision"]),
                    relevance=0.0,
                    audience_scope=str(row["audience_scope"]),
                )
            )

        if not candidates:
            return []

        depth = max(20, min(len(candidates), 100))
        rankings = []
        try:
            lexical = self.lexical_ranker.rank(
                documents,
                query,
                limit=depth,
            )
        except RetrievalRankerError:
            lexical = []
        if lexical:
            rankings.append(lexical)

        if self.semantic_ranker is not None:
            try:
                semantic = self.semantic_ranker.rank(
                    documents,
                    query,
                    limit=depth,
                )
            except RetrievalRankerError:
                semantic = []
            if semantic:
                rankings.append(semantic)

        scores = reciprocal_rank_scores(rankings)
        by_id = {item.fact_id: item for item in candidates}

        # External ranking runs outside the authority-read transaction. Re-read
        # the authorized CURRENT set before returning so correction/retract/
        # delete/MUTED/archive/audience changes during ranking cannot disclose a
        # stale candidate snapshot.
        with self.db.transaction() as conn:
            fresh_rows = self.repository.current_fact_candidates(
                conn,
                identity_id=identity_id,
                principal_scope=principal_scope,
                context_space=context_space,
                allowed_audiences=allowed_audiences,
            )
        fresh_by_id = {
            str(row["fact_id"]): row
            for row in fresh_rows
        }

        def still_authorized(item: MemoryCandidate) -> bool:
            fresh = fresh_by_id.get(item.fact_id)
            if fresh is None:
                return False
            try:
                fresh_value = json.loads(str(fresh["value_json"]))
                if str(fresh["predicate"]) == CANONICAL_MEMORY_PREDICATE:
                    control_state = MemoryControlState(
                        fresh_value.get(
                            "control_state",
                            MemoryControlState.NORMAL.value,
                        )
                    )
                    if (
                        control_state is MemoryControlState.MUTED
                        or bool(fresh_value.get("archived", False))
                    ):
                        return False
                return (
                    int(fresh["revision"]) == item.revision
                    and str(fresh["fact_key"]) == item.fact_key
                    and str(fresh["subject"]) == item.subject
                    and str(fresh["predicate"]) == item.predicate
                    and str(fresh["audience_scope"]) == item.audience_scope
                    and canonical_json(fresh_value)
                        == canonical_json(item.value)
                )
            except (KeyError, TypeError, ValueError):
                return False
        # An external ranker can only reorder the pre-authorized candidate
        # set. Unknown IDs are ignored and cannot widen privacy/authority.
        ranked_ids = [
            fact_id
            for fact_id in sorted(
                scores,
                key=lambda value: (-scores[value], value),
            )
            if fact_id in by_id and still_authorized(by_id[fact_id])
        ]
        for item in sorted(
            candidates,
            key=lambda value: (
                -value.revision,
                value.predicate,
                value.fact_id,
            ),
        ):
            if (
                item.fact_id not in ranked_ids
                and still_authorized(item)
            ):
                ranked_ids.append(item.fact_id)

        output = []
        for fact_id in ranked_ids[: max(1, min(int(limit), 50))]:
            item = by_id[fact_id]
            output.append(
                MemoryCandidate(
                    fact_id=item.fact_id,
                    fact_key=item.fact_key,
                    subject=item.subject,
                    predicate=item.predicate,
                    value=item.value,
                    revision=item.revision,
                    relevance=float(scores.get(fact_id, 0.0)),
                    audience_scope=item.audience_scope,
                )
            )
        return output



CANONICAL_MEMORY_PREDICATE = "remembered_item"


class MemoryControlState(StringEnum):
    PINNED = "PINNED"
    NORMAL = "NORMAL"
    LOW = "LOW"
    MUTED = "MUTED"


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
    control_state: MemoryControlState = MemoryControlState.NORMAL
    archived: bool = False


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
        control_state: MemoryControlState = MemoryControlState.NORMAL,
        archived: bool = False,
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
            "control_state": MemoryControlState(control_state).value,
            "archived": bool(archived),
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
        control_state: MemoryControlState = MemoryControlState.NORMAL,
        archived: bool = False,
        created_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        value = self._value(
            memory_id=memory_id,
            text=text,
            category=category,
            priority=priority,
            control_state=control_state,
            archived=archived,
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
        control_state: Optional[MemoryControlState] = None,
        archived: Optional[bool] = None,
        created_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        current = self.get(memory_id)
        value = self._value(
            memory_id=memory_id,
            text=text,
            category=category,
            priority=priority,
            control_state=(
                current.control_state
                if control_state is None
                else MemoryControlState(control_state)
            ),
            archived=(
                current.archived
                if archived is None
                else bool(archived)
            ),
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
                    """SELECT tf.*,cs.event_id AS source_event_id
                       FROM temporal_facts tf
                       JOIN claims c ON c.claim_id=tf.claim_id
                       JOIN claim_sources cs ON cs.claim_id=c.claim_id
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
                    """SELECT tf.*,cs.event_id AS source_event_id
                       FROM temporal_facts tf
                       JOIN claims c ON c.claim_id=tf.claim_id
                       JOIN claim_sources cs ON cs.claim_id=c.claim_id
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
            control_state=MemoryControlState(
                value.get("control_state", MemoryControlState.NORMAL.value)
            ),
            archived=bool(value.get("archived", False)),
        )

    def set_control_state(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        expected_revision: int,
        control_state: MemoryControlState,
        created_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        current = self.get(memory_id)
        return self.correct(
            memory_id=memory_id,
            mutation_id=mutation_id,
            source_event_id=source_event_id,
            principal_id=principal_id,
            expected_revision=expected_revision,
            text=current.text,
            category=current.category,
            priority=current.priority,
            control_state=MemoryControlState(control_state),
            archived=current.archived,
            created_at=created_at,
        )

    def archive(
        self,
        *,
        memory_id: str,
        mutation_id: str,
        source_event_id: str,
        principal_id: str,
        expected_revision: int,
        archived: bool = True,
        created_at: Optional[datetime] = None,
    ) -> CanonicalMemoryItem:
        current = self.get(memory_id)
        return self.correct(
            memory_id=memory_id,
            mutation_id=mutation_id,
            source_event_id=source_event_id,
            principal_id=principal_id,
            expected_revision=expected_revision,
            text=current.text,
            category=current.category,
            priority=current.priority,
            control_state=current.control_state,
            archived=bool(archived),
            created_at=created_at,
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
                """SELECT tf.*,cs.event_id AS source_event_id
                   FROM temporal_facts tf
                   JOIN claims c ON c.claim_id=tf.claim_id
                   JOIN claim_sources cs ON cs.claim_id=c.claim_id
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
