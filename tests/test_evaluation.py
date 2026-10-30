"""Tests for the evaluation set validator."""

import copy
import unittest

from iqm_rag import config
from iqm_rag.evaluation.dataset import load_questions, validate_dataset
from iqm_rag.scraping.normalization import read_jsonl, sha256_text

ARTICLE = {
    "article_id": "1", "canonical_url": "https://help.iqm.com/en/articles/1-x", "cleaned_markdown": "Pacing text.",
    "sections": [{"heading": "Pacing", "blocks": [{"type": "paragraph", "text": "Daily Pacing updates every hour."}],
                  "level": 1, "content_hash": ""}],
}


def make_question(**overrides) -> dict:
    article = copy.deepcopy(ARTICLE)
    from iqm_rag.scraping.normalization import section_markdown
    article["sections"][0]["content_hash"] = sha256_text(section_markdown(article["sections"][0]))
    evidence = {"article_id": "1", "url": article["canonical_url"], "section_heading": "Pacing",
                "section_content_hash": article["sections"][0]["content_hash"],
                "quote": "Daily Pacing updates every hour.", "required": True}
    question = {"id": "q1", "category": "direct_factual", "split": "dev", "question": "How often?", "history": [],
                "expected_answer": "Hourly", "key_facts": ["hourly"], "expected_source_urls": [evidence["url"]],
                "evidence": [evidence], "should_abstain": False}
    question.update(overrides)
    return question, article


def run(question: dict, article: dict, extra: int = 14) -> list[str]:
    filler = [{**question, "id": f"f{n}"} for n in range(extra)]
    return validate_dataset([question] + filler, [article])


class ValidatorTests(unittest.TestCase):
    def test_a_grounded_question_passes(self):
        question, article = make_question()
        self.assertEqual(run(question, article), [])

    def test_a_quote_not_in_the_section_is_rejected(self):
        question, article = make_question()
        question["evidence"][0]["quote"] = "Weekly pacing updates every day."
        self.assertTrue(any("quote not found" in e for e in run(question, article)))

    def test_a_changed_section_is_detected(self):
        question, article = make_question()
        article["sections"][0]["content_hash"] = "different"
        self.assertTrue(any("section changed" in e for e in run(question, article)))

    def test_an_unanswerable_question_must_use_absent_terms(self):
        question, article = make_question(should_abstain=True, evidence=[], expected_source_urls=[],
                                          absence_check={"terms": ["pacing"], "corpus_hits": 0})
        self.assertTrue(any("present in the corpus" in e for e in run(question, article)))

    def test_fewer_than_fifteen_questions_is_rejected(self):
        question, article = make_question()
        self.assertTrue(any("fewer than" in e for e in validate_dataset([question], [article])))

    def test_follow_up_needs_history(self):
        question, article = make_question(category="follow_up")
        self.assertTrue(any("history" in e for e in run(question, article)))


@unittest.skipUnless(config.PROCESSED_ARTICLES_JSONL.exists(), "cleaned corpus not generated; run scripts/normalize.py")
class RealSetTests(unittest.TestCase):
    def test_the_evaluation_set_is_grounded_in_the_current_corpus(self):
        errors = validate_dataset(load_questions(), read_jsonl(config.PROCESSED_ARTICLES_JSONL))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
