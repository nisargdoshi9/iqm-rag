"""Tests for small-talk replies. Whole-message rules only; a real question must never be caught."""

import json
import unittest

import hermetic  # noqa: F401  (keeps tracing off in tests)
from iqm_rag.generation import smalltalk
from iqm_rag.generation.chain import AnswerChain
from test_generation import ChainTestCase, FakeLLM, RecordingRetriever, draft


class RuleTests(unittest.TestCase):
    def test_greetings_thanks_goodbyes_acknowledgements_and_capability_questions_are_recognised(self):
        cases = {
            "Hi": smalltalk.GREETING, "hello there!": smalltalk.GREETING, "Good morning": smalltalk.GREETING, "hey 👋": smalltalk.GREETING,
            "thanks": smalltalk.THANKS, "Thank you so much!": smalltalk.THANKS, "ok thanks": smalltalk.THANKS, "great, thanks": smalltalk.THANKS,
            "bye": smalltalk.GOODBYE, "That's all": smalltalk.GOODBYE, "that’s all for now": smalltalk.GOODBYE,
            "ok": smalltalk.ACKNOWLEDGEMENT, "Got it.": smalltalk.ACKNOWLEDGEMENT,
            "what can you do?": smalltalk.CAPABILITIES, "Who are you": smalltalk.CAPABILITIES, "help": smalltalk.CAPABILITIES,
        }
        for message, kind in cases.items():
            self.assertEqual(smalltalk.kind_of(message), kind, message)

    def test_real_questions_are_never_small_talk(self):
        for message in ("How do I schedule a report?", "hi, how do I schedule a report", "thanks, but how do I export it?",
                        "help me create a campaign", "what can you do with frequency capping", "ok so how do I upload a creative",
                        "Can I say hello in a campaign name?", "", "   ", "?!"):
            self.assertIsNone(smalltalk.kind_of(message), message)

    def test_every_kind_has_a_reply_and_no_reply_contains_a_url_or_number_reference(self):
        self.assertEqual(set(smalltalk.PATTERNS), set(smalltalk.REPLIES))
        for reply in smalltalk.REPLIES.values():
            self.assertNotIn("http", reply)


class ChainTests(ChainTestCase):
    def test_small_talk_gets_a_reply_without_searching_or_calling_the_model(self):
        llm, recorder = FakeLLM(draft([1])), RecordingRetriever(self.retriever)
        answer = AnswerChain(recorder, llm.runnable, "fake-chat-model").answer("thanks!")
        self.assertEqual((answer.status, answer.citations, answer.answerable), ("smalltalk", (), False))
        self.assertEqual(answer.text, smalltalk.REPLIES[smalltalk.THANKS])
        self.assertEqual((recorder.queries, llm.prompts), ([], []))
        self.assertEqual((answer.retrieval.hits, answer.docs, answer.llm_attempts, answer.usage), ([], [], 0, None))

    def test_the_small_talk_answer_is_json_serialisable_and_summarisable(self):
        answer = AnswerChain(self.retriever, FakeLLM(draft([1])).runnable, "fake-chat-model").answer("hello")
        self.assertEqual(json.loads(json.dumps(answer.to_dict()))["status"], "smalltalk")
        self.assertEqual(answer.trace_summary()["status"], "smalltalk")

    def test_a_real_question_still_takes_the_normal_path(self):
        llm = FakeLLM(draft([1]))
        answer = self.chain(llm).answer("schedule a report")
        self.assertEqual(answer.status, "answered")
        self.assertEqual(len(llm.prompts), 1)


if __name__ == "__main__":
    unittest.main()
