"""Tests for turning a follow-up into a standalone query (FR-6). A fake model; no network calls."""

import unittest
from typing import Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from openai import OpenAIError

from iqm_rag.history import Message
from iqm_rag.retrieval.query_rewriting import REWRITE_MAX_CHARS, QueryRewriter

HISTORY = [Message("user", "What is campaign scheduling?"), Message("assistant", "It sets when ads are shown.")]
FOLLOW_UP = "How do I remove those settings?"


class FakeRewriteLLM:
    def __init__(self, reply: str = "", error: Optional[Exception] = None, finish_reason: str = "stop") -> None:
        self.reply, self.error, self.finish_reason = reply, error, finish_reason
        self.prompts: list = []

    def __call__(self, prompt_value) -> AIMessage:
        self.prompts.append(prompt_value.to_messages())
        if self.error:
            raise self.error
        return AIMessage(content=self.reply, response_metadata={"finish_reason": self.finish_reason},
                         usage_metadata={"input_tokens": 50, "output_tokens": 12, "total_tokens": 62})

    def rewriter(self) -> QueryRewriter:
        return QueryRewriter(RunnableLambda(self), "fake-rewrite-model")


class RewriteTests(unittest.TestCase):
    def test_the_first_turn_is_not_rewritten_and_calls_no_model(self):
        llm = FakeRewriteLLM("unused")
        result = llm.rewriter().rewrite(FOLLOW_UP, [])
        self.assertEqual((result.query, result.rewritten, result.fallback_reason, result.model), (FOLLOW_UP, False, None, None))
        self.assertEqual(llm.prompts, [])

    def test_a_follow_up_is_replaced_by_the_standalone_question(self):
        llm = FakeRewriteLLM("How do I remove campaign scheduling settings from an existing campaign?")
        result = llm.rewriter().rewrite(FOLLOW_UP, HISTORY)
        self.assertEqual(result.query, "How do I remove campaign scheduling settings from an existing campaign?")
        self.assertTrue(result.rewritten)
        self.assertEqual((result.original, result.model, result.fallback_reason), (FOLLOW_UP, "fake-rewrite-model", None))
        self.assertEqual(result.usage.total_tokens, 62)

    def test_an_unchanged_question_is_reported_as_not_rewritten(self):
        result = FakeRewriteLLM("  " + FOLLOW_UP + "\n").rewriter().rewrite(FOLLOW_UP, HISTORY)
        self.assertEqual((result.query, result.rewritten, result.fallback_reason), (FOLLOW_UP, False, None))

    def test_wrapping_quotes_are_removed(self):
        result = FakeRewriteLLM('"How do I remove campaign scheduling?"').rewriter().rewrite(FOLLOW_UP, HISTORY)
        self.assertEqual(result.query, "How do I remove campaign scheduling?")

    def test_the_prompt_carries_the_history_and_the_latest_message(self):
        llm = FakeRewriteLLM(FOLLOW_UP)
        llm.rewriter().rewrite(FOLLOW_UP, HISTORY)
        system, human = llm.prompts[0]
        self.assertIn("standalone", system.content)
        self.assertIn("User: What is campaign scheduling?\nAssistant: It sets when ads are shown.", human.content)
        self.assertIn(FOLLOW_UP, human.content.split("# Latest message")[1])


class FallbackTests(unittest.TestCase):
    def assertFallsBack(self, llm: FakeRewriteLLM, reason: str) -> None:
        result = llm.rewriter().rewrite(FOLLOW_UP, HISTORY)
        self.assertEqual((result.query, result.rewritten), (FOLLOW_UP, False))
        self.assertIn(reason, result.fallback_reason)

    def test_an_api_failure_falls_back_to_the_raw_question(self):
        self.assertFallsBack(FakeRewriteLLM(error=OpenAIError("rate limited")), "failed")

    def test_an_empty_reply_falls_back(self):
        self.assertFallsBack(FakeRewriteLLM("  "), "empty")

    def test_an_over_long_reply_falls_back(self):
        self.assertFallsBack(FakeRewriteLLM("x" * (REWRITE_MAX_CHARS + 1)), "long")

    def test_a_multi_line_reply_falls_back(self):
        self.assertFallsBack(FakeRewriteLLM("The settings are removed here.\nThen click save."), "line")

    def test_a_reply_cut_off_at_the_length_limit_falls_back(self):
        self.assertFallsBack(FakeRewriteLLM("How do I remove campaign sched", finish_reason="length"), "cut off")


if __name__ == "__main__":
    unittest.main()
