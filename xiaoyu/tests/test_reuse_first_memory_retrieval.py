from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaoyu.core.memory import (
    MemoryRetriever,
    MemorySearchDocument,
    RetrievalRankerError,
    SQLiteFTS5MemoryRanker,
)
from xiaoyu.persistence import Database, apply_migrations
from xiaoyu.runtime import FastEmbedSemanticRanker


class FakeRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def current_fact_candidates(
        self,
        conn,
        *,
        identity_id,
        principal_scope,
        context_space,
        allowed_audiences,
    ):
        self.calls.append(
            (
                identity_id,
                principal_scope,
                context_space,
                allowed_audiences,
            )
        )
        return list(self.rows)


class FixedRanker:
    def __init__(self, ids):
        self.ids = list(ids)
        self.seen_documents = []

    def rank(self, documents, query, *, limit):
        self.seen_documents = list(documents)
        return self.ids[:limit]


class BrokenRanker:
    def rank(self, documents, query, *, limit):
        raise RetrievalRankerError("synthetic semantic outage")


class MutingRanker:
    def __init__(self, repository, ids):
        self.repository = repository
        self.ids = list(ids)

    def rank(self, documents, query, *, limit):
        current = dict(self.repository.rows[0])
        current["value_json"] = (
            '{"memory_id":"coffee","text":"private old value",'
            '"category":"preference","priority":4,'
            '"control_state":"MUTED","archived":false}'
        )
        current["revision"] = int(current["revision"]) + 1
        self.repository.rows = [current]
        return self.ids[:limit]


class FakeEmbeddingModel:
    def passage_embed(self, texts):
        for text in texts:
            if "coffee" in text or "咖啡" in text:
                yield [1.0, 0.0, 0.0]
            elif "tea" in text or "乌龙茶" in text:
                yield [0.0, 1.0, 0.0]
            else:
                yield [0.0, 0.0, 1.0]

    def query_embed(self, query):
        if "coffee" in query or "咖啡" in query:
            yield [1.0, 0.0, 0.0]
        elif "tea" in query or "乌龙茶" in query:
            yield [0.0, 1.0, 0.0]
        else:
            yield [0.0, 0.0, 1.0]


def row(
    fact_id,
    *,
    subject,
    predicate,
    value_json,
    revision,
    audience="PRIVATE",
):
    return {
        "fact_id": fact_id,
        "fact_key": "key:" + fact_id,
        "subject": subject,
        "predicate": predicate,
        "value_json": value_json,
        "revision": revision,
        "cardinality": "SINGLE",
        "audience_scope": audience,
        "eligible_for_memory": 1,
    }


class ReuseFirstMemoryRetrievalTests(unittest.TestCase):
    def _db(self, td):
        db = Database(Path(td) / "identity.sqlite3")
        apply_migrations(db)
        return db

    def test_fts5_english_ranks_relevant_fact_first(self):
        ranker = SQLiteFTS5MemoryRanker()
        docs = [
            MemorySearchDocument(
                "project",
                'owner project {"text":"finish report"}',
                9,
            ),
            MemorySearchDocument(
                "coffee",
                'owner preference {"text":"favorite coffee drink"}',
                2,
            ),
        ]
        ranked = ranker.rank(docs, "what coffee do I like", limit=5)
        self.assertEqual(ranked[0], "coffee")

    def test_fts5_trigram_ranks_chinese_phrase_without_custom_postings(self):
        ranker = SQLiteFTS5MemoryRanker()
        docs = [
            MemorySearchDocument(
                "deadline",
                'owner project {"text":"项目明天截止"}',
                8,
            ),
            MemorySearchDocument(
                "oolong",
                'owner preference {"text":"我喜欢乌龙茶"}',
                1,
            ),
        ]
        ranked = ranker.rank(
            docs,
            "你还记得我喜欢乌龙茶吗",
            limit=5,
        )
        self.assertEqual(ranked[0], "oolong")

    def test_fastembed_adapter_uses_query_and_passage_paths(self):
        ranker = FastEmbedSemanticRanker(
            embedding_model=FakeEmbeddingModel(),
        )
        docs = [
            MemorySearchDocument("tea", "我喜欢乌龙茶", 1),
            MemorySearchDocument("coffee", "我喜欢咖啡", 2),
        ]
        self.assertEqual(
            ranker.rank(docs, "咖啡偏好", limit=2),
            ["coffee", "tea"],
        )

    def test_semantic_ranker_can_recover_nonlexical_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repository = FakeRepository(
                [
                    row(
                        "older-semantic",
                        subject="owner",
                        predicate="drink_preference",
                        value_json='{"text":"coffee"}',
                        revision=1,
                    ),
                    row(
                        "newer-unrelated",
                        subject="owner",
                        predicate="project",
                        value_json='{"text":"deadline"}',
                        revision=7,
                    ),
                ]
            )
            semantic = FixedRanker(
                ["older-semantic", "newer-unrelated"]
            )
            retriever = MemoryRetriever(
                db,
                repository=repository,
                semantic_ranker=semantic,
            )
            result = retriever.retrieve(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="beverage I usually order",
                limit=2,
            )
            self.assertEqual(result[0].fact_id, "older-semantic")
            self.assertGreater(result[0].relevance, 0.0)

    def test_external_ranker_cannot_inject_unknown_or_private_fact_id(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repository = FakeRepository(
                [
                    row(
                        "group-safe",
                        subject="owner",
                        predicate="shared_topic",
                        value_json='{"text":"group-safe"}',
                        revision=2,
                        audience="GROUP",
                    )
                ]
            )
            semantic = FixedRanker(
                ["forged-owner-private", "group-safe"]
            )
            retriever = MemoryRetriever(
                db,
                repository=repository,
                lexical_ranker=FixedRanker([]),
                semantic_ranker=semantic,
            )
            result = retriever.retrieve(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("GROUP",),
                query="shared topic",
                limit=5,
            )
            self.assertEqual(
                [item.fact_id for item in result],
                ["group-safe"],
            )
            self.assertEqual(
                [doc.fact_id for doc in semantic.seen_documents],
                ["group-safe"],
            )

    def test_memory_muted_during_external_ranking_is_not_returned(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repository = FakeRepository(
                [
                    row(
                        "memory-current",
                        subject="memory:coffee",
                        predicate="remembered_item",
                        value_json=(
                            '{"memory_id":"coffee","text":"private old value",'
                            '"category":"preference","priority":4,'
                            '"control_state":"NORMAL","archived":false}'
                        ),
                        revision=4,
                    )
                ]
            )
            semantic = MutingRanker(repository, ["memory-current"])
            retriever = MemoryRetriever(
                db,
                repository=repository,
                lexical_ranker=FixedRanker([]),
                semantic_ranker=semantic,
            )
            result = retriever.retrieve(
                identity_id="fish-r20",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="private old value",
                limit=5,
            )
            self.assertEqual(result, [])
            self.assertGreaterEqual(len(repository.calls), 2)

    def test_semantic_failure_degrades_to_fts5_not_to_broader_scope(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repository = FakeRepository(
                [
                    row(
                        "coffee",
                        subject="owner",
                        predicate="preference",
                        value_json='{"text":"favorite coffee"}',
                        revision=1,
                    ),
                    row(
                        "project",
                        subject="owner",
                        predicate="project",
                        value_json='{"text":"weekly report"}',
                        revision=5,
                    ),
                ]
            )
            retriever = MemoryRetriever(
                db,
                repository=repository,
                semantic_ranker=BrokenRanker(),
            )
            result = retriever.retrieve(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="coffee",
                limit=2,
            )
            self.assertEqual(result[0].fact_id, "coffee")

    def test_ranker_receives_only_repository_authorized_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            repository = FakeRepository(
                [
                    row(
                        "only-current",
                        subject="owner",
                        predicate="preference",
                        value_json='{"text":"current"}',
                        revision=3,
                    )
                ]
            )
            semantic = FixedRanker(["only-current"])
            retriever = MemoryRetriever(
                db,
                repository=repository,
                semantic_ranker=semantic,
            )
            retriever.retrieve(
                identity_id="fish-1",
                principal_scope="owner",
                context_space="PERSONAL",
                allowed_audiences=("PRIVATE",),
                query="anything",
                limit=3,
            )
            self.assertEqual(len(semantic.seen_documents), 1)
            self.assertEqual(
                semantic.seen_documents[0].fact_id,
                "only-current",
            )
            self.assertEqual(
                repository.calls,
                [
                    (
                        "fish-1",
                        "owner",
                        "PERSONAL",
                        ("PRIVATE",),
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
