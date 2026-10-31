"""Tests for the LLM judge (FR-9). A fake model; no network."""

import unittest
from typing import Optional

import hermetic  # noqa: F401  (keeps tracing off in tests)
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from openai import OpenAIError

from iqm_rag.evaluation.judge import FactCheck, Judge, JudgeVerdict, should_judge
from test_generation import ChainTestCase, FakeLLM, draft

QUESTION = {"id": "q1", "question": "How do I schedule a report?", "should_abstain": False,
            "key_facts": ["Use the Reports tab", "Pick a weekly frequency"], "expected_answer": "Open Reports and choose weekly."}


class FakeJudgeLLM:
    def __init__(self, verdict: Optional[JudgeVerdict] = None, error: Optional[Exception] = None, parsing_error: Optional[Exception] = None):
        self.verdict, self.error, self.parsing_error, self.prompts = verdict, error, parsing_error, []

    def __call__(self, prompt_value):
        self.prompts.append(prompt_value.to_messages())
        if self.error:
            raise self.error
        raw = AIMessage(content="", usage_metadata={"input_tokens": 900, "output_tokens": 80, "total_tokens": 980})
        return {"raw": raw, "parsed": self.verdict, "parsing_error": self.parsing_error}

    def judge(self) -> Judge:
        return Judge(RunnableLambda(self), "fake-judge-model")


def verdict(covered=(True, True), unsupported=(), comment="none") -> JudgeVerdict:
    facts = QUESTION["key_facts"]
    return JudgeVerdict(fact_checks=[FactCheck(fact=f, covered=c, note="ok") for f, c in zip(facts, covered)],
                        unsupported_claims=list(unsupported), comment=comment)


class JudgeTests(ChainTestCase):
    def answer(self, status: str = "answered"):
        return self.chain(FakeLLM(draft([1] if status == "answered" else [], status=status, answer="Use the Reports tab."))).answer("schedule a report")

    def test_the_result_counts_covered_facts_and_faithfulness(self):
        result = FakeJudgeLLM(verdict((True, False), unsupported=["It also emails Vera."])).judge().evaluate(QUESTION, self.answer())
        self.assertEqual((result.facts_covered, result.facts_total, result.faithful, result.error), (1, 2, False, None))
        self.assertEqual(result.unsupported_claims, ["It also emails Vera."])
        self.assertEqual(result.model, "fake-judge-model")
        self.assertEqual(result.usage.total_tokens, 980)

    def test_a_fully_correct_and_supported_answer(self):
        result = FakeJudgeLLM(verdict()).judge().evaluate(QUESTION, self.answer())
        self.assertEqual((result.facts_covered, result.faithful), (2, True))

    def test_the_prompt_asks_for_strict_unbiased_judging(self):
        llm = FakeJudgeLLM(verdict())
        llm.judge().evaluate(QUESTION, self.answer())
        system, human = llm.prompts[0]
        for phrase in ("impartial", "Ignore tone, length", "not a better one", "Do not assume", "unsupported", "even if it is true in the real world"):
            self.assertIn(phrase, system.content)
        self.assertIn("covered=false", system.content)
        self.assertIn("strict", human.content.lower())

    def test_the_judge_sees_the_question_the_key_facts_the_reference_the_documents_and_the_answer(self):
        llm = FakeJudgeLLM(verdict())
        llm.judge().evaluate(QUESTION, self.answer())
        text = llm.prompts[0][1].content
        for expected in ("How do I schedule a report?", "1. Use the Reports tab", "2. Pick a weekly frequency", "Open Reports and choose weekly.",
                         '<doc id="1"', "schedule schedule a report", "Use the Reports tab."):
            self.assertIn(expected, text)

    def test_the_wrong_number_of_fact_checks_is_an_error_not_a_guess(self):
        short = JudgeVerdict(fact_checks=[FactCheck(fact="Use the Reports tab", covered=True, note="ok")], unsupported_claims=[], comment="none")
        result = FakeJudgeLLM(short).judge().evaluate(QUESTION, self.answer())
        self.assertIsNone(result.facts_covered)
        self.assertIn("1 fact checks for 2 key facts", result.error)

    def test_an_api_error_is_recorded_and_does_not_stop_the_run(self):
        result = FakeJudgeLLM(error=OpenAIError("rate limited")).judge().evaluate(QUESTION, self.answer())
        self.assertIsNone(result.facts_covered)
        self.assertIn("rate limited", result.error)

    def test_output_that_does_not_match_the_schema_is_an_error(self):
        result = FakeJudgeLLM(verdict=None, parsing_error=ValueError("bad json")).judge().evaluate(QUESTION, self.answer())
        self.assertIn("did not match", result.error)

    def test_only_answered_answerable_questions_are_judged(self):
        self.assertTrue(should_judge(QUESTION, self.answer("answered")))
        self.assertFalse(should_judge(QUESTION, self.answer("not_covered")))
        self.assertFalse(should_judge({**QUESTION, "should_abstain": True}, self.answer("answered")))

    def test_the_result_is_json_ready(self):
        import json

        data = FakeJudgeLLM(verdict()).judge().evaluate(QUESTION, self.answer()).to_dict()
        self.assertEqual(json.loads(json.dumps(data))["facts_covered"], 2)
        self.assertEqual(data["fact_checks"][0]["fact"], "Use the Reports tab")


if __name__ == "__main__":
    unittest.main()
