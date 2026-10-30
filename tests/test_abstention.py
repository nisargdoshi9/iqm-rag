"""Tests for abstention behaviour through the whole FR-5 chain. Fake model, fake embedder; no network."""

import unittest

from iqm_rag.generation.citations import ABSTENTION_MESSAGE
from iqm_rag.retrieval.retriever import RetrievalResult
from test_generation import ChainTestCase, FakeLLM, draft


class EmptyRetriever:
    """A retriever that finds nothing."""

    def retrieve(self, query: str) -> RetrievalResult:
        return RetrievalResult(query, 8, "fake", 0, 0.0, 0.0, [])


class AbstentionTests(ChainTestCase):
    def test_the_models_abstention_is_shown_without_links(self):
        answer = self.chain(FakeLLM(draft([], answerable=False, answer="The Help Center does not cover TikTok."))).answer("tiktok")
        self.assertFalse(answer.answerable)
        self.assertEqual((answer.text, answer.citations), ("The Help Center does not cover TikTok.", ()))

    def test_sources_listed_on_an_abstention_are_not_shown(self):
        answer = self.chain(FakeLLM(draft([1, 2], answerable=False, answer="Not covered."))).answer("tiktok")
        self.assertEqual(answer.citations, ())
        self.assertTrue(answer.warnings)

    def test_an_answer_citing_only_an_invented_number_becomes_an_abstention(self):
        answer = self.chain(FakeLLM(draft([99]))).answer("schedule a report")
        self.assertFalse(answer.answerable)
        self.assertEqual((answer.text, answer.citations), (ABSTENTION_MESSAGE, ()))
        self.assertTrue(any("99" in w for w in answer.warnings))

    def test_the_unchecked_draft_stays_available_to_show_what_was_overridden(self):
        answer = self.chain(FakeLLM(draft([99], answer="Invented claim."))).answer("schedule a report")
        self.assertEqual(answer.draft.answer, "Invented claim.")
        self.assertNotIn("Invented claim", answer.text)

    def test_no_retrieved_evidence_means_no_model_call_and_an_abstention(self):
        llm = FakeLLM(draft([1]))
        answer = self.chain(llm, retriever=EmptyRetriever()).answer("schedule a report")
        self.assertEqual(llm.prompts, [])
        self.assertFalse(answer.answerable)
        self.assertEqual((answer.text, answer.citations, answer.usage), (ABSTENTION_MESSAGE, (), None))


if __name__ == "__main__":
    unittest.main()
