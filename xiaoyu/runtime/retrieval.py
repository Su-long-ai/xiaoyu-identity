from __future__ import annotations

from importlib import metadata
import math
from typing import Any, Optional, Sequence

from xiaoyu.core.memory import (
    MemorySearchDocument,
    RetrievalRankerError,
)


class FastEmbedUnavailable(RetrievalRankerError):
    pass


class FastEmbedSemanticRanker:
    """Optional semantic ranker behind XiaoYu's authorized candidate set."""

    DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
    REVIEWED_FASTEMBED_VERSION = "0.9.1"

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        embedding_model: Optional[Any] = None,
        required_fastembed_version: Optional[str] = (
            REVIEWED_FASTEMBED_VERSION
        ),
    ) -> None:
        self.model_name = str(model_name).strip()
        if not self.model_name:
            raise ValueError("model_name is required")

        if embedding_model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore
            except ImportError as exc:
                raise FastEmbedUnavailable(
                    "fastembed is not installed"
                ) from exc
            if required_fastembed_version is not None:
                try:
                    installed = metadata.version("fastembed")
                except metadata.PackageNotFoundError as exc:
                    raise FastEmbedUnavailable(
                        "fastembed package metadata is unavailable"
                    ) from exc
                if installed != required_fastembed_version:
                    raise FastEmbedUnavailable(
                        "fastembed version %s is not the reviewed %s"
                        % (installed, required_fastembed_version)
                    )
            try:
                embedding_model = TextEmbedding(self.model_name)
            except Exception as exc:
                raise FastEmbedUnavailable(
                    "fastembed model initialization failed"
                ) from exc
        self.embedding_model = embedding_model

    @staticmethod
    def _normalized(vector: Any) -> tuple[float, ...]:
        try:
            values = tuple(float(value) for value in vector)
        except (TypeError, ValueError) as exc:
            raise RetrievalRankerError(
                "embedding vector is not numeric"
            ) from exc
        if not values or any(not math.isfinite(value) for value in values):
            raise RetrievalRankerError(
                "embedding vector is empty or non-finite"
            )
        norm = math.sqrt(sum(value * value for value in values))
        if not math.isfinite(norm) or norm <= 1e-12:
            raise RetrievalRankerError(
                "embedding vector has zero/invalid norm"
            )
        return tuple(value / norm for value in values)

    def _document_embeddings(
        self,
        texts: Sequence[str],
    ) -> list[tuple[float, ...]]:
        model = self.embedding_model
        try:
            if callable(getattr(model, "passage_embed", None)):
                raw = list(model.passage_embed(list(texts)))
            else:
                raw = list(model.embed(list(texts)))
        except Exception as exc:
            raise RetrievalRankerError(
                "semantic document embedding failed"
            ) from exc
        return [self._normalized(vector) for vector in raw]

    def _query_embedding(self, query: str) -> tuple[float, ...]:
        model = self.embedding_model
        try:
            if callable(getattr(model, "query_embed", None)):
                raw = list(model.query_embed(str(query)))
            else:
                raw = list(model.embed([str(query)]))
        except Exception as exc:
            raise RetrievalRankerError(
                "semantic query embedding failed"
            ) from exc
        if len(raw) != 1:
            raise RetrievalRankerError(
                "semantic query embedding returned wrong cardinality"
            )
        return self._normalized(raw[0])

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
        vectors = self._document_embeddings(
            [document.text for document in docs]
        )
        if len(vectors) != len(docs):
            raise RetrievalRankerError(
                "semantic document embedding returned wrong cardinality"
            )
        query_vector = self._query_embedding(query)
        dimension = len(query_vector)
        scored = []
        for document, vector in zip(docs, vectors):
            if len(vector) != dimension:
                raise RetrievalRankerError(
                    "semantic embedding dimension mismatch"
                )
            score = sum(
                left * right
                for left, right in zip(vector, query_vector)
            )
            scored.append((score, document.fact_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            fact_id
            for _, fact_id in scored[: max(1, min(int(limit), len(scored)))]
        ]


def build_fastembed_memory_retriever(
    db,
    *,
    repository=None,
    model_name: str = FastEmbedSemanticRanker.DEFAULT_MODEL,
    embedding_model=None,
):
    """Opt-in shadow factory; authority filtering remains in MemoryRetriever."""
    from xiaoyu.core.memory import MemoryRetriever

    return MemoryRetriever(
        db,
        repository=repository,
        semantic_ranker=FastEmbedSemanticRanker(
            model_name=model_name,
            embedding_model=embedding_model,
            required_fastembed_version=(
                None if embedding_model is not None
                else FastEmbedSemanticRanker.REVIEWED_FASTEMBED_VERSION
            ),
        ),
    )
