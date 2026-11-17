from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from xiaoyu.contracts.common import StringEnum, canonical_json
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.context import MemoryContextRepository


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
