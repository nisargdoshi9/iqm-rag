"""Tests for the retrieval pipeline: BM25, fusion, reranking, neighbour expansion and the configuration switches. No network."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (keeps tracing off in tests)
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from openai import OpenAIError

from iqm_rag import config
from iqm_rag.generation.chain import AnswerChain
from iqm_rag.ingestion.indexing import run_indexing
from iqm_rag.retrieval.fusion import reciprocal_rank_fusion
from iqm_rag.retrieval.keyword import KeywordIndex, tokenize
from iqm_rag.retrieval.pipeline import RetrievalPipeline, RetrievalSettings, neighbour_ids
from iqm_rag.retrieval.rerank import LLMReranker, Ranking, RerankOutcome, clean_order, format_passages
from iqm_rag.retrieval.retriever import Retriever
from test_generation import FakeLLM, USAGE, draft
from test_retrieval import CHUNKS, TopicEmbedder, topic_chunk

DAAST = topic_chunk(6, "daast daast embed code")  # a rare term that the topic embedder cannot tell apart from noise


def split_chunk(n: int, part: int, parts: int, text: str) -> dict:
    chunk = topic_chunk(n * 10 + part, text)
    chunk.update({"chunk_id": f"1:s{n}:p{part}", "section_ids": [f"1:s{n}"], "part": part, "parts": parts})
    return chunk


class PipelineTestCase(unittest.TestCase):
    chunks = CHUNKS + [DAAST]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        embedder = TopicEmbedder()
        path = Path(tmp.name) / "chroma"
        run_indexing(self.chunks, embedder, path)
        self.retriever = Retriever(embedder, path, top_k=2)

    def pipeline(self, **kwargs) -> RetrievalPipeline:
        settings = kwargs.pop("settings", RetrievalSettings())
        return RetrievalPipeline(self.retriever, settings, **kwargs)


class KeywordTests(unittest.TestCase):
    def test_tokenizing_lowercases_and_drops_stopwords_but_keeps_product_terms(self):
        self.assertEqual(tokenize("How do I add a DAAST XML/URL to the audio creative?"), ["add", "daast", "xml", "url", "audio", "creative"])

    def test_a_rare_term_finds_its_chunk_and_unknown_words_find_nothing(self):
        index = KeywordIndex(CHUNKS + [DAAST])
        self.assertEqual(index.search("daast", 3)[0].chunk_id, "1:s6:p1")
        self.assertEqual(index.search("zzzzz qqqqq", 3), [])
        self.assertEqual(index.search("the a of", 3), [])

    def test_results_are_best_first_limited_and_repeatable(self):
        index = KeywordIndex(CHUNKS)
        first = index.search("schedule export report", 3)
        self.assertEqual(len(first), 3)
        self.assertEqual([h.score for h in first], sorted((h.score for h in first), reverse=True))
        self.assertEqual(first, index.search("schedule export report", 3))

    def test_an_empty_index_is_refused(self):
        with self.assertRaises(ValueError):
            KeywordIndex([])


class FusionTests(unittest.TestCase):
    def test_items_in_both_rankings_beat_items_in_one(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "d"]])
        self.assertEqual([item for item, _ in fused][:2], ["c", "a"])
        self.assertEqual({item for item, _ in fused}, {"a", "b", "c", "d"})

    def test_ties_keep_first_seen_order_and_empty_input_is_fine(self):
        self.assertEqual([i for i, _ in reciprocal_rank_fusion([["a"], ["b"]])], ["a", "b"])
        self.assertEqual(reciprocal_rank_fusion([]), [])


class SettingsTests(unittest.TestCase):
    def test_labels_name_the_configuration(self):
        self.assertEqual(RetrievalSettings().label, "dense")
        self.assertEqual(RetrievalSettings("hybrid").label, "hybrid")
        self.assertEqual(RetrievalSettings("hybrid", "llm", True).label, "hybrid+llm+neighbours")

    def test_bad_values_are_rejected(self):
        for kwargs in ({"mode": "sparse"}, {"rerank": "cross"}, {"candidates": 0}, {"candidates": config.MAX_CANDIDATES + 1}):
            with self.assertRaises(ValueError):
                RetrievalSettings(**kwargs)

    def test_settings_come_from_the_environment(self):
        env = {"RETRIEVAL_MODE": "hybrid", "RERANK": "llm", "NEIGHBOURS": "1", "RETRIEVAL_CANDIDATES": "20"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(RetrievalSettings.from_env(), RetrievalSettings("hybrid", "llm", True, 20))
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "", "RERANK": "", "NEIGHBOURS": "0", "RETRIEVAL_CANDIDATES": ""}):
            self.assertEqual(RetrievalSettings.from_env(), RetrievalSettings("hybrid", "llm", False, config.DEFAULT_CANDIDATES))  # the shipped defaults
        with mock.patch.dict(os.environ, {"RETRIEVAL_MODE": "dense", "RERANK": "off"}):
            self.assertEqual(RetrievalSettings.from_env().label, "dense")

    def test_a_misspelt_environment_value_is_reported_by_name(self):
        for name, value in (("RETRIEVAL_MODE", "sparse"), ("RERANK", "yes"), ("RETRIEVAL_CANDIDATES", "lots")):
            with mock.patch.dict(os.environ, {name: value}), self.assertRaisesRegex(RuntimeError, name):
                RetrievalSettings.from_env()


class DenseTests(PipelineTestCase):
    def test_dense_mode_is_exactly_plain_vector_search(self):
        plain = self.retriever.retrieve("export")
        result = self.pipeline().retrieve("export")
        self.assertEqual([h.chunk["chunk_id"] for h in result.hits], [h.chunk["chunk_id"] for h in plain.hits])
        self.assertEqual((result.extra_hits, result.top_k), ([], 2))

    def test_the_pipeline_looks_like_a_retriever_to_the_chain(self):
        pipeline = self.pipeline()
        self.assertEqual((pipeline.top_k, pipeline.embedding_model, pipeline.chunk_count), (2, "topic-model", 6))
        self.assertEqual(pipeline.describe()["label"], "dense")


class HybridTests(PipelineTestCase):
    def test_a_keyword_match_that_vector_search_misses_is_added(self):
        self.assertNotIn("1:s6:p1", [h.chunk["chunk_id"] for h in self.retriever.retrieve("export daast").hits])
        result = self.pipeline(settings=RetrievalSettings("hybrid", candidates=4)).retrieve("export daast")
        ids = [h.chunk["chunk_id"] for h in result.hits]
        self.assertIn("1:s6:p1", ids)
        self.assertEqual([h.rank for h in result.hits], [1, 2])
        self.assertEqual(result.steps["settings"]["mode"], "hybrid")

    def test_every_hit_has_a_real_similarity_and_its_stage_scores(self):
        result = self.pipeline(settings=RetrievalSettings("hybrid", candidates=2)).retrieve("export daast", top_k=2)
        for hit in result.hits:
            self.assertTrue(0.0 <= hit.distance <= 2.0, hit.chunk["chunk_id"])
            self.assertIn("fused", hit.scores)
        keyword_only = next(h for h in result.hits if h.chunk["chunk_id"] == "1:s6:p1")
        self.assertIsNone(keyword_only.scores["dense_rank"])
        self.assertEqual(keyword_only.scores["keyword_rank"], 1)

    def test_hybrid_results_are_repeatable(self):
        pipeline = self.pipeline(settings=RetrievalSettings("hybrid", candidates=6))
        ids = lambda: [h.chunk["chunk_id"] for h in pipeline.retrieve("schedule export").hits]  # noqa: E731
        self.assertEqual(ids(), ids())


class FakeReranker:
    name = "fake"
    model = "fake-rerank-model"

    def __init__(self, order=None, fallback=None):
        self.order, self.fallback, self.calls = order, fallback, []

    def rerank(self, query, candidates, top_k):
        self.calls.append((query, [c["chunk_id"] for c in candidates], top_k))
        order = self.order if self.order is not None else list(range(min(top_k, len(candidates))))
        return RerankOutcome(order[:top_k], self.model, None, 1.0, self.fallback)


class RerankTests(PipelineTestCase):
    def test_the_reranker_chooses_the_final_order_from_the_candidates(self):
        reranker = FakeReranker(order=[3, 0])
        pipeline = self.pipeline(settings=RetrievalSettings("dense", "llm", candidates=5), reranker=reranker)
        plain = [h.chunk["chunk_id"] for h in self.retriever.retrieve("schedule", top_k=5).hits]
        result = pipeline.retrieve("schedule")
        self.assertEqual([h.chunk["chunk_id"] for h in result.hits], [plain[3], plain[0]])
        self.assertEqual([h.rank for h in result.hits], [1, 2])
        self.assertEqual([h.scores["candidate_rank"] for h in result.hits], [4, 1])
        self.assertEqual((reranker.calls[0][0], len(reranker.calls[0][1]), reranker.calls[0][2]), ("schedule", 5, 2))
        self.assertEqual(result.steps["rerank"]["model"], "fake-rerank-model")

    def test_hybrid_candidates_go_to_the_reranker(self):
        reranker = FakeReranker()
        self.pipeline(settings=RetrievalSettings("hybrid", "llm", candidates=4), reranker=reranker).retrieve("export daast")
        self.assertIn("1:s6:p1", reranker.calls[0][1])

    def test_switching_rerank_on_without_a_reranker_is_refused(self):
        with self.assertRaises(ValueError):
            self.pipeline(settings=RetrievalSettings("dense", "llm"))

    def test_a_rerank_fallback_reaches_the_answer_as_a_warning(self):
        reranker = FakeReranker(fallback="rerank request failed (boom)")
        chain = AnswerChain(self.pipeline(settings=RetrievalSettings("dense", "llm", candidates=4), reranker=reranker), FakeLLM(draft([1])).runnable, "fake-chat-model")
        answer = chain.answer("schedule a report")
        self.assertIn("rerank request failed (boom)", answer.warnings)
        self.assertEqual(answer.status, "answered")


def ranking_llm(parsed=None, error=None, parsing_error=None):
    calls = []

    def call(prompt_value):
        calls.append(prompt_value.to_messages())
        if error:
            raise error
        return {"raw": AIMessage(content="", usage_metadata=USAGE), "parsed": parsed, "parsing_error": parsing_error}

    return RunnableLambda(call), calls


class LLMRerankerTests(unittest.TestCase):
    candidates = [dict(chunk, context_header=chunk["context_header"]) for chunk in CHUNKS]

    def test_the_models_order_is_used_and_usage_is_kept(self):
        llm, calls = ranking_llm(Ranking(ranking=[3, 1]))
        outcome = LLMReranker(llm, "m").rerank("export", self.candidates, 2)
        self.assertEqual((outcome.order, outcome.fallback_reason, outcome.usage.input_tokens), ([2, 0], None, 100))
        self.assertIn('<passage id="1"', calls[0][1].content)
        self.assertIn("at most 2", calls[0][0].content)

    def test_unknown_and_repeated_numbers_are_dropped_and_the_rest_is_padded_in_order(self):
        self.assertEqual(clean_order([9, 2, 2, 0, -1], count=5, top_k=3), [1, 0, 2])
        self.assertEqual(clean_order([5, 4, 3, 2, 1], count=5, top_k=3), [4, 3, 2])
        self.assertEqual(clean_order([1], count=2, top_k=5), [0, 1])

    def test_a_failure_keeps_the_original_order_and_says_why(self):
        for llm in (ranking_llm(error=OpenAIError("down"))[0], ranking_llm(None, parsing_error=ValueError("bad"))[0],
                    ranking_llm(Ranking(ranking=[99, 100]))[0]):
            outcome = LLMReranker(llm, "m").rerank("export", self.candidates, 2)
            self.assertEqual(outcome.order, [0, 1])
            self.assertTrue(outcome.fallback_reason)

    def test_one_candidate_needs_no_model_call(self):
        llm, calls = ranking_llm(Ranking(ranking=[1]))
        outcome = LLMReranker(llm, "m").rerank("export", self.candidates[:1], 2)
        self.assertEqual((outcome.order, calls), ([0], []))

    def test_long_passages_are_cut_for_the_reranker_and_no_url_is_shown(self):
        text = format_passages([dict(self.candidates[0], text="word " * 1000)])
        self.assertLess(len(text), 1800)
        self.assertNotIn("help.iqm.com", text)


class NeighbourTests(unittest.TestCase):
    def hit(self, chunk, rank=1):
        from iqm_rag.retrieval.retriever import RetrievedChunk
        return RetrievedChunk(rank, 0.1, chunk)

    def test_adjacent_parts_of_split_sections_are_wanted(self):
        hits = [self.hit(split_chunk(1, 2, 3, "x")), self.hit(split_chunk(2, 1, 2, "y"), 2), self.hit(topic_chunk(9, "z"), 3)]
        self.assertEqual(neighbour_ids(hits), ["1:s1:p1", "1:s1:p3", "1:s2:p2"])

    def test_parts_that_are_already_hits_and_whole_sections_are_skipped_and_the_total_is_capped(self):
        hits = [self.hit(split_chunk(1, 1, 2, "x")), self.hit(split_chunk(1, 2, 2, "x"), 2)]
        self.assertEqual(neighbour_ids(hits), [])
        many = [self.hit(split_chunk(n, 2, 3, "x"), n) for n in range(1, 8)]
        self.assertEqual(len(neighbour_ids(many)), 8)


class NeighbourPipelineTests(PipelineTestCase):
    chunks = [split_chunk(1, 1, 3, "schedule one steps first"), split_chunk(1, 2, 3, "schedule schedule schedule two steps middle"),
              split_chunk(1, 3, 3, "schedule three last steps"), topic_chunk(2, "export export report")]

    def test_neighbouring_parts_join_the_context_but_not_the_ranking(self):
        result = self.pipeline(settings=RetrievalSettings(neighbours=True)).retrieve("schedule schedule schedule two", top_k=1)
        self.assertEqual([h.chunk["chunk_id"] for h in result.hits], ["1:s1:p2"])
        self.assertEqual(sorted(h.chunk["chunk_id"] for h in result.extra_hits), ["1:s1:p1", "1:s1:p3"])
        self.assertEqual(result.steps["neighbours_added"], [h.chunk["chunk_id"] for h in result.extra_hits])
        self.assertTrue(all(0.0 <= h.distance <= 2.0 for h in result.extra_hits))

    def test_the_answer_context_holds_the_whole_section_in_part_order(self):
        llm = FakeLLM(draft([1]))
        chain = AnswerChain(self.pipeline(settings=RetrievalSettings(neighbours=True)), llm.runnable, "fake-chat-model")
        answer = chain.answer("schedule schedule schedule two")
        self.assertEqual(answer.docs[0].chunk_ids[:3], ("1:s1:p1", "1:s1:p2", "1:s1:p3"))
        self.assertEqual(len(answer.retrieval.hits), 2)  # the ranking is still top_k; only the context grew
        self.assertEqual(answer.to_dict()["retrieval"]["extra_hits"][0]["scores"], {"neighbour": True})

    def test_without_the_switch_nothing_is_added(self):
        self.assertEqual(self.pipeline().retrieve("schedule schedule schedule two", top_k=1).extra_hits, [])


class ChainDescriptionTests(PipelineTestCase):
    def test_the_chain_records_the_retrieval_configuration(self):
        chain = AnswerChain(self.pipeline(settings=RetrievalSettings("hybrid")), FakeLLM(draft([1])).runnable, "fake-chat-model")
        self.assertEqual(chain.describe()["retrieval"]["label"], "hybrid")


if __name__ == "__main__":
    unittest.main()
