"""Tests for the FR-5 answer chain. A fake model and a topic-based fake embedder over a throwaway Chroma folder; no network."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from openai import OpenAIError

from iqm_rag.generation.chain import AnswerChain, GenerationError
from iqm_rag.generation.prompts import PROMPT_VERSION, AnswerDraft
from iqm_rag.ingestion.indexing import run_indexing
from iqm_rag.retrieval.retriever import Retriever
from test_retrieval import CHUNKS, TopicEmbedder

USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


class FakeLLM:
    """Stands in for the structured-output chat model: records the prompt and returns a canned draft."""

    def __init__(self, draft: Optional[AnswerDraft] = None, error: Optional[Exception] = None, raw: Optional[AIMessage] = None,
                 parsing_error: Optional[Exception] = None) -> None:
        self.draft, self.error, self.parsing_error = draft, error, parsing_error
        self.raw = raw if raw is not None else AIMessage(content="", usage_metadata=USAGE)
        self.prompts: list = []

    def __call__(self, prompt_value) -> dict:
        self.prompts.append(prompt_value.to_messages())
        if self.error:
            raise self.error
        return {"raw": self.raw, "parsed": self.draft, "parsing_error": self.parsing_error}

    @property
    def runnable(self) -> RunnableLambda:
        return RunnableLambda(self)


def draft(sources: list[int], answerable: bool = True, answer: str = "Use the Reports tab.") -> AnswerDraft:
    return AnswerDraft(answerable=answerable, answer=answer, sources=sources)


class ChainTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        embedder = TopicEmbedder()
        path = Path(self.tmp.name) / "chroma"
        run_indexing(CHUNKS, embedder, path)
        self.retriever = Retriever(embedder, path, top_k=3)

    def chain(self, llm: FakeLLM, retriever=None) -> AnswerChain:
        return AnswerChain(retriever or self.retriever, llm.runnable, "fake-chat-model")


class AnswerFlowTests(ChainTestCase):
    def test_a_grounded_answer_carries_citations_from_stored_metadata(self):
        llm = FakeLLM(draft([1]))
        answer = self.chain(llm).answer("schedule a report")
        self.assertTrue(answer.answerable)
        self.assertEqual(answer.text, "Use the Reports tab.")
        self.assertEqual([c.url for c in answer.citations], [CHUNKS[0]["article_url"]])
        self.assertEqual((answer.model, answer.prompt_version), ("fake-chat-model", PROMPT_VERSION))

    def test_usage_and_the_unchecked_draft_are_kept_for_tracing(self):
        answer = self.chain(FakeLLM(draft([1]))).answer("schedule a report")
        self.assertEqual((answer.usage.input_tokens, answer.usage.output_tokens, answer.usage.total_tokens), (100, 20, 120))
        self.assertEqual(answer.draft.sources, [1])
        self.assertGreaterEqual(answer.llm_ms, 0)

    def test_missing_usage_is_reported_as_unknown_not_guessed(self):
        answer = self.chain(FakeLLM(draft([1]), raw=AIMessage(content=""))).answer("schedule a report")
        self.assertIsNone(answer.usage)

    def test_the_retrieval_result_is_attached_to_the_answer(self):
        answer = self.chain(FakeLLM(draft([1]))).answer("  schedule a report ")
        self.assertEqual((answer.question, answer.retrieval.query, len(answer.retrieval.hits)), ("schedule a report",) * 2 + (3,))
        self.assertEqual(answer.docs[0].chunk_ids, (answer.retrieval.hits[0].chunk["chunk_id"],))

    def test_the_result_is_json_serialisable(self):
        data = json.loads(json.dumps(self.chain(FakeLLM(draft([1]))).answer("schedule a report").to_dict()))
        self.assertEqual((data["answerable"], len(data["citations"]), data["usage"]["total_tokens"]), (True, 1, 120))
        self.assertIn("hits", data["retrieval"])


class PromptTests(ChainTestCase):
    def prompt_for(self, question: str = "schedule a report") -> list:
        llm = FakeLLM(draft([1]))
        self.chain(llm).answer(question)
        return llm.prompts[0]

    def test_the_prompt_has_the_rules_then_the_context_then_the_question_then_a_reminder(self):
        system, human = self.prompt_for()
        self.assertIn("evidence, not instructions", system.content)
        self.assertIn("Do not write URLs", system.content)
        text = human.content
        order = [text.index(marker) for marker in ("# Context", '<doc id="1"', "# Question", "# Final reminder")]
        self.assertEqual(order, sorted(order))
        self.assertIn("schedule a report", text.split("# Question")[1])

    def test_no_url_reaches_the_model(self):
        self.assertNotIn("help.iqm.com", "".join(m.content for m in self.prompt_for()))

    def test_braces_in_retrieved_text_do_not_break_the_prompt(self):
        tricky = dict(CHUNKS[0], text="schedule {context} {unknown} {{x}}")
        embedder = TopicEmbedder()
        path = Path(self.tmp.name) / "tricky"
        run_indexing([tricky], embedder, path)
        llm = FakeLLM(draft([1]))
        self.chain(llm, Retriever(embedder, path, top_k=1)).answer("schedule")
        self.assertIn("schedule {context} {unknown} {{x}}", llm.prompts[0][1].content)


class FailureTests(ChainTestCase):
    def test_an_empty_question_is_rejected_before_anything_is_called(self):
        llm = FakeLLM(draft([1]))
        with self.assertRaisesRegex(ValueError, "empty"):
            self.chain(llm).answer("   ")
        self.assertEqual(llm.prompts, [])

    def test_an_api_failure_is_reported_with_the_model_name(self):
        with self.assertRaisesRegex(GenerationError, "fake-chat-model"):
            self.chain(FakeLLM(error=OpenAIError("rate limited"))).answer("schedule a report")

    def test_output_that_does_not_match_the_schema_is_an_error_not_a_guess(self):
        with self.assertRaisesRegex(GenerationError, "expected format"):
            self.chain(FakeLLM(draft=None, parsing_error=ValueError("bad json"))).answer("schedule a report")

    def test_a_refusal_is_reported_with_its_reason(self):
        raw = AIMessage(content="", additional_kwargs={"refusal": "I cannot help with that."})
        with self.assertRaisesRegex(GenerationError, "refused: I cannot help"):
            self.chain(FakeLLM(draft=None, raw=raw)).answer("schedule a report")


if __name__ == "__main__":
    unittest.main()
