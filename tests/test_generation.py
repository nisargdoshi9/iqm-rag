"""Tests for the FR-5 answer chain. A fake model and a topic-based fake embedder over a throwaway Chroma folder; no network."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from openai import LengthFinishReasonError, OpenAIError
from types import SimpleNamespace

from iqm_rag.generation.chain import TRUNCATED_MESSAGE, AnswerChain, GenerationError
from iqm_rag.generation.prompts import PROMPT_VERSION, AnswerDraft
from iqm_rag.history import Message
from iqm_rag.ingestion.indexing import run_indexing
from iqm_rag.retrieval.query_rewriting import QueryRewriter
from iqm_rag.retrieval.retriever import Retriever
from test_query_rewriting import FakeRewriteLLM
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


class RecordingRetriever:
    """Wraps the real retriever and remembers the queries it was asked."""

    def __init__(self, retriever: Retriever) -> None:
        self._retriever, self.queries = retriever, []

    def retrieve(self, query: str):
        self.queries.append(query)
        return self._retriever.retrieve(query)


def exchanges(n: int) -> list[Message]:
    return [m for i in range(1, n + 1) for m in (Message("user", f"earlier question {i}"), Message("assistant", f"earlier answer {i}"))]


class FollowUpTests(ChainTestCase):
    def follow_up_chain(self, rewrite_llm: FakeRewriteLLM, answer_llm: FakeLLM):
        recorder = RecordingRetriever(self.retriever)
        rewriter = QueryRewriter(RunnableLambda(rewrite_llm), "fake-rewrite-model")
        return AnswerChain(recorder, answer_llm.runnable, "fake-chat-model", rewriter), recorder

    def test_retrieval_searches_with_the_rewritten_query_and_the_answer_keeps_the_original_question(self):
        chain, recorder = self.follow_up_chain(FakeRewriteLLM("export a report to csv"), FakeLLM(draft([1])))
        answer = chain.answer("how do I do that?", exchanges(1))
        self.assertEqual(recorder.queries, ["export a report to csv"])
        self.assertEqual(answer.retrieval.hits[0].chunk["chunk_id"], "1:s2:p1")
        self.assertEqual((answer.question, answer.rewrite.query, answer.rewrite.rewritten), ("how do I do that?", "export a report to csv", True))

    def test_the_answer_model_sees_the_users_message_and_a_labelled_history_before_the_context(self):
        llm = FakeLLM(draft([1]))
        chain, _ = self.follow_up_chain(FakeRewriteLLM("export a report to csv"), llm)
        chain.answer("how do I do that?", exchanges(1))
        text = llm.prompts[0][1].content
        self.assertIn("not evidence", text.split("# Context")[0])
        self.assertIn("User: earlier question 1\nAssistant: earlier answer 1", text.split("# Context")[0])
        self.assertIn("how do I do that?", text.split("# Question")[1])
        self.assertNotIn("export a report to csv", text.split("# Question")[1])

    def test_the_first_turn_has_no_history_block_and_no_rewrite_call(self):
        rewrite_llm, llm = FakeRewriteLLM("unused"), FakeLLM(draft([1]))
        chain, _ = self.follow_up_chain(rewrite_llm, llm)
        answer = chain.answer("schedule a report")
        self.assertEqual(rewrite_llm.prompts, [])
        self.assertNotIn("Conversation so far", llm.prompts[0][1].content)
        self.assertEqual((answer.rewrite.model, answer.history), (None, ()))

    def test_only_the_last_three_exchanges_reach_the_rewrite_and_the_answer(self):
        rewrite_llm, llm = FakeRewriteLLM("schedule"), FakeLLM(draft([1]))
        chain, _ = self.follow_up_chain(rewrite_llm, llm)
        answer = chain.answer("and then?", exchanges(5))
        self.assertEqual(len(answer.history), 6)
        for prompt_text in (rewrite_llm.prompts[0][1].content, llm.prompts[0][1].content):
            self.assertIn("earlier question 3", prompt_text)
            self.assertNotIn("earlier question 2", prompt_text)

    def test_a_failed_rewrite_falls_back_to_the_raw_question_and_is_reported(self):
        chain, recorder = self.follow_up_chain(FakeRewriteLLM(error=OpenAIError("down")), FakeLLM(draft([1])))
        answer = chain.answer("schedule a report", exchanges(1))
        self.assertEqual(recorder.queries, ["schedule a report"])
        self.assertTrue(answer.answerable)
        self.assertTrue(any("original question" in w for w in answer.warnings))

    def test_the_trace_data_records_the_rewrite_and_the_history_used(self):
        chain, _ = self.follow_up_chain(FakeRewriteLLM("export a report to csv"), FakeLLM(draft([1])))
        data = json.loads(json.dumps(chain.answer("how do I do that?", exchanges(1)).to_dict()))
        self.assertEqual((data["rewrite"]["original"], data["rewrite"]["query"], data["rewrite"]["rewritten"]),
                         ("how do I do that?", "export a report to csv", True))
        self.assertEqual(data["history"][0], {"role": "user", "content": "earlier question 1"})
        self.assertEqual(data["rewrite"]["usage"]["total_tokens"], 62)


class ScriptedLLM:
    """Returns or raises the next scripted outcome on each call and records every prompt."""

    def __init__(self, *outcomes) -> None:
        self.outcomes, self.prompts = list(outcomes), []

    def __call__(self, prompt_value):
        self.prompts.append(prompt_value.to_messages())
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def runnable(self) -> RunnableLambda:
        return RunnableLambda(self)


def good_output(sources: list[int]) -> dict:
    return {"raw": AIMessage(content="", usage_metadata=USAGE, response_metadata={"finish_reason": "stop"}),
            "parsed": draft(sources), "parsing_error": None}


def length_error() -> LengthFinishReasonError:
    return LengthFinishReasonError(completion=SimpleNamespace(usage=None))


class TruncationTests(ChainTestCase):
    def chain_with(self, first: ScriptedLLM, retry: ScriptedLLM = None) -> AnswerChain:
        return AnswerChain(self.retriever, first.runnable, "fake-chat-model", None, None if retry is None else retry.runnable)

    def test_a_cut_off_reply_is_retried_once_asking_for_a_concise_answer(self):
        first, retry = ScriptedLLM(length_error()), ScriptedLLM(good_output([1]))
        answer = self.chain_with(first, retry).answer("schedule a report")
        self.assertTrue(answer.answerable)
        self.assertEqual(answer.llm_attempts, 2)
        self.assertNotIn("cut off for length", first.prompts[0][1].content)
        self.assertIn("cut off for length", retry.prompts[0][1].content)

    def test_a_reply_that_finishes_with_length_is_also_retried(self):
        cut = good_output([1])
        cut["raw"] = AIMessage(content="", response_metadata={"finish_reason": "length"})
        answer = self.chain_with(ScriptedLLM(cut), ScriptedLLM(good_output([1]))).answer("schedule a report")
        self.assertEqual((answer.answerable, answer.llm_attempts), (True, 2))

    def test_a_first_reply_that_fits_is_never_retried(self):
        retry = ScriptedLLM(good_output([1]))
        answer = self.chain_with(ScriptedLLM(good_output([1])), retry).answer("schedule a report")
        self.assertEqual((answer.llm_attempts, retry.prompts), (1, []))

    def test_two_cut_off_replies_give_a_friendly_message_not_an_error(self):
        answer = self.chain_with(ScriptedLLM(length_error()), ScriptedLLM(length_error())).answer("schedule a report")
        self.assertEqual((answer.answerable, answer.text, answer.citations, answer.llm_attempts), (False, TRUNCATED_MESSAGE, (), 2))
        self.assertTrue(any("cut off" in w for w in answer.warnings))

    def test_without_a_retry_model_a_cut_off_reply_still_gives_the_friendly_message(self):
        answer = self.chain_with(ScriptedLLM(length_error())).answer("schedule a report")
        self.assertEqual((answer.text, answer.llm_attempts), (TRUNCATED_MESSAGE, 1))

    def test_other_api_errors_are_not_retried_and_still_raise(self):
        retry = ScriptedLLM(good_output([1]))
        with self.assertRaises(GenerationError):
            self.chain_with(ScriptedLLM(OpenAIError("rate limited")), retry).answer("schedule a report")
        self.assertEqual(retry.prompts, [])


if __name__ == "__main__":
    unittest.main()
