"""Tests for FR-4 retrieval. A topic-based fake embedder and a throwaway local Chroma folder; no network calls."""

import json
import tempfile
import unittest
from pathlib import Path

from iqm_rag import config
from iqm_rag.ingestion.embeddings import EmbeddingError, EmbeddingResult
from iqm_rag.ingestion.indexing import IndexMismatchError, IndexNotBuiltError, run_indexing
from iqm_rag.retrieval.retriever import MAX_QUERY_CHARS, Retriever, RetrievalError
from test_indexing import make_chunk

TOPICS = ("schedule", "export", "budget", "audience")  # one vector dimension per topic word


class TopicEmbedder:
    """Vector = how often each topic word appears, plus a tiny constant so no vector is all zeros."""

    def __init__(self, model: str = "topic-model", fail: bool = False, dimension: int = len(TOPICS)) -> None:
        self.model = model
        self.fail = fail
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("simulated outage")
        vectors = [[text.lower().count(topic) + 0.01 for topic in TOPICS][:self.dimension] + [0.01] * (self.dimension - len(TOPICS))
                   for text in texts]
        return EmbeddingResult(vectors=vectors, tokens=sum(len(t.split()) for t in texts))


def topic_chunk(n: int, text: str) -> dict:
    chunk = make_chunk(n)
    chunk.update({"text": text, "content_hash": f"hash-{n}"})
    return chunk


CHUNKS = [
    topic_chunk(1, "schedule schedule a report"),
    topic_chunk(2, "export export a report to csv"),
    topic_chunk(3, "budget budget pacing"),
    topic_chunk(4, "audience audience segments"),
    topic_chunk(5, "schedule and export together"),
]


class RetrieverTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "chroma"
        self.addCleanup(self.tmp.cleanup)
        self.embedder = TopicEmbedder()
        run_indexing(CHUNKS, self.embedder, self.path)
        self.embedder.calls.clear()

    def retriever(self, **kwargs) -> Retriever:
        return Retriever(self.embedder, self.path, **kwargs)


class RankingTests(RetrieverTestCase):
    def test_the_closest_chunk_comes_first_with_ranks_from_one(self):
        result = self.retriever().retrieve("schedule")
        self.assertEqual(result.hits[0].chunk["chunk_id"], "1:s1:p1")
        self.assertEqual([hit.rank for hit in result.hits], [1, 2, 3, 4, 5])

    def test_distances_are_ascending_and_similarity_is_one_minus_distance(self):
        hits = self.retriever().retrieve("export").hits
        distances = [hit.distance for hit in hits]
        self.assertEqual(distances, sorted(distances))
        for hit in hits:
            self.assertAlmostEqual(hit.similarity, 1.0 - hit.distance)
        self.assertEqual(hits[0].chunk["chunk_id"], "1:s2:p1")

    def test_the_second_topic_surfaces_a_chunk_that_covers_both(self):
        ids = [hit.chunk["chunk_id"] for hit in self.retriever().retrieve("schedule export", top_k=3).hits]
        self.assertIn("1:s5:p1", ids)

    def test_a_hit_carries_the_full_stored_chunk(self):
        hit = self.retriever().retrieve("budget").hits[0]
        self.assertEqual(hit.chunk, CHUNKS[2])

    def test_the_same_query_gives_the_same_order(self):
        retriever = self.retriever()
        first = [h.chunk["chunk_id"] for h in retriever.retrieve("audience").hits]
        second = [h.chunk["chunk_id"] for h in retriever.retrieve("audience").hits]
        self.assertEqual(first, second)


class TopKTests(RetrieverTestCase):
    def test_default_top_k_is_eight(self):
        self.assertEqual(config.DEFAULT_TOP_K, 8)
        self.assertEqual(self.retriever().top_k, 8)

    def test_top_k_limits_the_number_of_hits(self):
        self.assertEqual(len(self.retriever(top_k=2).retrieve("schedule").hits), 2)

    def test_a_per_call_top_k_overrides_the_default(self):
        result = self.retriever(top_k=2).retrieve("schedule", top_k=4)
        self.assertEqual((len(result.hits), result.top_k), (4, 4))

    def test_fewer_chunks_than_top_k_returns_all_of_them(self):
        result = self.retriever(top_k=8).retrieve("schedule")
        self.assertEqual((len(result.hits), result.top_k), (5, 8))

    def test_invalid_top_k_is_rejected(self):
        for bad in (0, -1, config.MAX_TOP_K + 1):
            with self.assertRaisesRegex(ValueError, "top_k"):
                self.retriever(top_k=bad)
        with self.assertRaisesRegex(ValueError, "top_k"):
            self.retriever().retrieve("schedule", top_k=0)


class QueryTests(RetrieverTestCase):
    def test_blank_queries_are_rejected_without_calling_the_embedder(self):
        retriever = self.retriever()
        for blank in ("", "   ", "\n\t"):
            with self.assertRaisesRegex(ValueError, "empty"):
                retriever.retrieve(blank)
        self.assertEqual(self.embedder.calls, [])

    def test_an_overlong_query_is_rejected_not_truncated(self):
        with self.assertRaisesRegex(ValueError, "characters"):
            self.retriever().retrieve("x" * (MAX_QUERY_CHARS + 1))
        self.assertEqual(self.embedder.calls, [])

    def test_only_the_trimmed_query_is_embedded_with_no_context_header(self):
        result = self.retriever().retrieve("  schedule a report \n")
        self.assertEqual(self.embedder.calls, [["schedule a report"]])
        self.assertEqual(result.query, "schedule a report")


class DiagnosticsTests(RetrieverTestCase):
    def test_the_result_reports_what_was_run(self):
        result = self.retriever(top_k=3).retrieve("schedule a report")
        self.assertEqual((result.top_k, result.embedding_model, result.embedding_tokens), (3, "topic-model", 3))
        self.assertGreaterEqual(result.embed_ms, 0)
        self.assertGreaterEqual(result.search_ms, 0)

    def test_to_dict_is_json_serialisable_and_lists_every_hit(self):
        data = json.loads(json.dumps(self.retriever(top_k=2).retrieve("export").to_dict()))
        self.assertEqual(data["query"], "export")
        self.assertEqual(len(data["hits"]), 2)
        first = data["hits"][0]
        self.assertEqual((first["rank"], first["chunk_id"]), (1, "1:s2:p1"))
        self.assertEqual(first["article_url"], CHUNKS[1]["article_url"])
        for key in ("distance", "similarity", "article_title", "section_path", "media_section_ids", "text"):
            self.assertIn(key, first)


class FailureTests(RetrieverTestCase):
    def test_a_missing_index_is_reported_clearly(self):
        with self.assertRaisesRegex(IndexNotBuiltError, "scripts/index.py"):
            Retriever(self.embedder, Path(self.tmp.name) / "nowhere")

    def test_an_empty_index_is_reported_clearly(self):
        empty = Path(self.tmp.name) / "empty"
        run_indexing([], self.embedder, empty)
        with self.assertRaisesRegex(IndexNotBuiltError, "empty"):
            Retriever(self.embedder, empty)

    def test_a_different_embedding_model_is_refused(self):
        with self.assertRaisesRegex(IndexMismatchError, "topic-model"):
            Retriever(TopicEmbedder(model="other-model"), self.path)

    def test_a_query_vector_of_the_wrong_size_is_refused(self):
        retriever = Retriever(TopicEmbedder(dimension=3), self.path)
        with self.assertRaisesRegex(IndexMismatchError, "dimension"):
            retriever.retrieve("schedule")

    def test_an_embedding_failure_is_not_swallowed(self):
        retriever = Retriever(TopicEmbedder(fail=True), self.path)
        with self.assertRaises(EmbeddingError):
            retriever.retrieve("schedule")

    def test_a_search_failure_names_the_query_problem(self):
        retriever = self.retriever()

        class Broken:
            def count(self):
                return 5

            def query(self, **kwargs):
                from chromadb.errors import ChromaError
                raise ChromaError("boom")

        retriever._collection = Broken()
        with self.assertRaisesRegex(RetrievalError, "boom"):
            retriever.retrieve("schedule")


if __name__ == "__main__":
    unittest.main()
