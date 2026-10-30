"""Tests for what the interface shows (FR-7). Pure display logic; no Streamlit, no network."""

import random
import unittest

from iqm_rag.generation.chain import GenerationError
from iqm_rag.ingestion.embeddings import EmbeddingError
from iqm_rag.ui.view import (EXAMPLE_QUESTIONS, LOADING_MESSAGES, STATUS_LABELS, build_answer_view, build_error_view,
                             evidence_counts, loading_message, pick_examples, source_label)
from test_generation import ChainTestCase, FakeLLM, draft


class AnswerViewTests(ChainTestCase):
    def view(self, llm: FakeLLM, question: str = "schedule a report"):
        return build_answer_view(self.chain(llm).answer(question))

    def test_an_answer_shows_its_label_text_and_links(self):
        view = self.view(FakeLLM(draft([1])))
        self.assertEqual((view.status, view.label, view.text), ("answered", "From the Help Center", "Use the Reports tab."))
        self.assertEqual([(s.title, s.sections) for s in view.sources], [("Title", ("A › B1",))])
        self.assertEqual(source_label(view.sources[0]), "Title: A › B1")

    def test_each_source_carries_an_extract_of_the_section_it_was_used_for(self):
        view = self.view(FakeLLM(draft([1])))
        self.assertEqual(view.sources[0].previews, ("schedule schedule a report",))

    def test_the_three_outcomes_have_distinct_labels(self):
        labels = {status: STATUS_LABELS[status] for status in ("answered", "not_covered", "clarification")}
        self.assertEqual(len(set(labels.values())), 3)
        self.assertEqual(self.view(FakeLLM(draft([], status="not_covered", answer="Not here."))).label, "Not in the Help Center")
        self.assertEqual(self.view(FakeLLM(draft([], status="clarification", answer="Which one?"))).label, "A quick question")

    def test_only_an_answer_has_source_links(self):
        self.assertEqual(self.view(FakeLLM(draft([1], status="not_covered", answer="Not here."))).sources, ())

    def test_every_retrieved_passage_is_listed_in_rank_order_and_the_cited_one_is_marked(self):
        view = self.view(FakeLLM(draft([1])))
        self.assertEqual([item.rank for item in view.evidence], [1, 2, 3])
        self.assertEqual([item.cited for item in view.evidence], [True, False, False])
        self.assertEqual(evidence_counts(view.evidence), (3, 1))
        self.assertTrue(all(0 <= item.similarity <= 1 for item in view.evidence))

    def test_the_snippet_skips_the_heading_line_and_markdown_marks(self):
        from iqm_rag.ui.view import _snippet

        self.assertEqual(_snippet("### Edit or stop\n\nFollow **these** steps:\n1. Do it"), "Follow these steps: 1. Do it")

    def test_a_long_passage_is_cut_to_a_short_snippet(self):
        item = self.view(FakeLLM(draft([1]))).evidence[0]
        self.assertLessEqual(len(item.snippet), 241)

    def test_the_developer_details_cover_the_rewrite_model_tokens_and_timing(self):
        details = dict(self.view(FakeLLM(draft([1]))).details)
        for label in ("Question as typed", "Search query", "Rewrite", "Answer model", "Embedding model", "Tokens", "Time"):
            self.assertIn(label, details)
        self.assertIn("in 100 · out 20", details["Tokens"])
        self.assertIn("prompt v4", details["Answer model"])

    def test_warnings_reach_the_developer_details(self):
        view = self.view(FakeLLM(draft([1, 99])))
        self.assertTrue(any(label == "Warning" for label, _ in view.details))


class ErrorViewTests(unittest.TestCase):
    def test_service_failures_get_a_friendly_message_without_technical_detail(self):
        for exc in (EmbeddingError("boom"), GenerationError("boom")):
            view = build_error_view(exc)
            self.assertEqual(view.status, "error")
            self.assertNotIn("boom", view.text)
            self.assertIn("boom", dict(view.details)["Error"])

    def test_an_unusable_question_explains_why(self):
        self.assertIn("The query is empty.", build_error_view(ValueError("The query is empty.")).text)

    def test_an_unexpected_failure_is_generic(self):
        self.assertIn("unexpected", build_error_view(KeyError("x")).text)


class LoadingAndExampleTests(unittest.TestCase):
    def test_there_are_a_dozen_distinct_loading_messages(self):
        self.assertEqual(len(LOADING_MESSAGES), len(set(LOADING_MESSAGES)))
        self.assertTrue(10 <= len(LOADING_MESSAGES) <= 12)

    def test_loading_messages_are_general_and_never_name_a_product_area(self):
        specific = ("campaign", "creative", "report", "dashboard", "audience", "bid", "iqm", "budget", "pixel")
        for message in LOADING_MESSAGES:
            self.assertFalse(any(word in message.lower() for word in specific), message)

    def test_loading_messages_go_round_robin_from_any_start(self):
        n = len(LOADING_MESSAGES)
        self.assertEqual([loading_message(5, t) for t in range(3)], [LOADING_MESSAGES[5], LOADING_MESSAGES[6], LOADING_MESSAGES[7]])
        self.assertEqual(loading_message(n - 1, 1), LOADING_MESSAGES[0])
        self.assertEqual(loading_message(0, n), LOADING_MESSAGES[0])

    def test_three_distinct_examples_are_picked_from_the_list(self):
        picked = pick_examples(random.Random(1))
        self.assertEqual(len(set(picked)), 3)
        self.assertTrue(set(picked) <= set(EXAMPLE_QUESTIONS))


if __name__ == "__main__":
    unittest.main()
