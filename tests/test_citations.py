"""Tests for the output checks that turn the model's draft into a safe answer (FR-5). No network calls."""

import unittest

from iqm_rag.generation.citations import ABSTENTION_MESSAGE, CLARIFICATION_FALLBACK, resolve_answer
from iqm_rag.generation.context import build_context_docs
from iqm_rag.generation.prompts import AnswerDraft
from test_context import hit

DOCS = build_context_docs([hit(1, 1, "alpha", article="10"), hit(2, 2, "beta", article="10"), hit(3, 3, "gamma", article="20")])


def draft(sources: list[int], status: str = "answered", answer: str = "An answer.") -> AnswerDraft:
    return AnswerDraft(status=status, answer=answer, sources=sources)


class CitationMappingTests(unittest.TestCase):
    def test_numbers_become_urls_from_stored_metadata(self):
        result = resolve_answer(draft([3]), DOCS)
        self.assertTrue(result.answerable)
        self.assertEqual([c.url for c in result.citations], ["https://help.iqm.com/en/articles/20-t"])
        self.assertEqual((result.citations[0].article_title, result.citations[0].sections), ("Title", ("A › B3",)))

    def test_two_sections_of_one_article_give_one_link_with_both_sections(self):
        result = resolve_answer(draft([2, 1]), DOCS)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].sections, ("A › B2", "A › B1"))

    def test_links_follow_the_order_first_cited(self):
        result = resolve_answer(draft([3, 1]), DOCS)
        self.assertEqual([c.url.split("/")[-1] for c in result.citations], ["20-t", "10-t"])

    def test_a_repeated_number_is_counted_once(self):
        result = resolve_answer(draft([1, 1, 1]), DOCS)
        self.assertEqual(result.citations[0].sections, ("A › B1",))

    def test_an_answer_keeps_its_text(self):
        self.assertEqual(resolve_answer(draft([1], answer="  Use the Reports tab. "), DOCS).text, "Use the Reports tab.")


class SafetyNetTests(unittest.TestCase):
    def test_a_number_that_was_not_supplied_is_dropped_and_the_rest_are_kept(self):
        result = resolve_answer(draft([1, 9, 0, -2]), DOCS)
        self.assertTrue(result.answerable)
        self.assertEqual(len(result.citations), 1)
        self.assertTrue(any("9" in w for w in result.warnings))

    def test_an_answer_with_no_valid_source_becomes_an_abstention(self):
        for sources in ([], [9]):
            result = resolve_answer(draft(sources), DOCS)
            self.assertFalse(result.answerable)
            self.assertEqual((result.text, result.citations), (ABSTENTION_MESSAGE, ()))
            self.assertTrue(result.warnings)

    def test_an_abstention_ignores_listed_sources(self):
        result = resolve_answer(draft([1, 2], status="not_covered", answer="The documentation does not cover TikTok."), DOCS)
        self.assertFalse(result.answerable)
        self.assertEqual((result.text, result.citations), ("The documentation does not cover TikTok.", ()))
        self.assertTrue(result.warnings)

    def test_an_abstention_without_text_uses_the_standard_message(self):
        result = resolve_answer(draft([], status="not_covered", answer="  "), DOCS)
        self.assertEqual(result.text, ABSTENTION_MESSAGE)
        self.assertEqual(result.warnings, ())

    def test_a_clarifying_question_is_kept_without_links_and_is_not_an_abstention(self):
        result = resolve_answer(draft([1], status="clarification", answer="Which settings do you mean?"), DOCS)
        self.assertEqual((result.status, result.text, result.citations), ("clarification", "Which settings do you mean?", ()))
        self.assertFalse(result.answerable)
        self.assertTrue(result.warnings)

    def test_a_clarification_without_text_uses_a_neutral_question(self):
        result = resolve_answer(draft([], status="clarification", answer=""), DOCS)
        self.assertEqual((result.status, result.text), ("clarification", CLARIFICATION_FALLBACK))

    def test_the_status_is_reported_for_each_outcome(self):
        self.assertEqual(resolve_answer(draft([1]), DOCS).status, "answered")
        self.assertEqual(resolve_answer(draft([], status="not_covered"), DOCS).status, "not_covered")
        self.assertEqual(resolve_answer(draft([9]), DOCS).status, "not_covered")  # invented source: shown as not covered

    def test_an_unknown_status_is_rejected_by_the_schema(self):
        with self.assertRaises(ValueError):
            AnswerDraft(status="maybe", answer="x", sources=[])

    def test_a_blank_answer_cannot_pass_as_an_answer(self):
        result = resolve_answer(draft([1], answer="   "), DOCS)
        self.assertFalse(result.answerable)
        self.assertEqual(result.text, ABSTENTION_MESSAGE)

    def test_nothing_to_cite_from_means_abstention(self):
        result = resolve_answer(draft([1]), [])
        self.assertFalse(result.answerable)


if __name__ == "__main__":
    unittest.main()
