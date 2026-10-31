"""Tests for the evaluation metrics (FR-9). Pure calculations on small hand-made records; no network."""

import unittest

from iqm_rag.evaluation.metrics import (OUTCOME_PASSES, aggregate, article_rank, citation_scores, cost_usd, describe,
                                        evidence_ranks, percentile, ratio, recall_at, reciprocal_rank, status_outcome)

URL1, URL2, URL3 = (f"https://help.iqm.com/en/articles/{n}-x" for n in (1, 2, 3))


def question(**overrides) -> dict:
    base = {"id": "q1", "split": "dev", "category": "direct_factual", "should_abstain": False, "expected_source_urls": [URL1],
            "related_urls": [], "evidence": [{"article_id": "1", "url": URL1, "section_heading": "H", "required": True,
                                              "quote": "Daily Pacing **updates** every hour."}]}
    base.update(overrides)
    return base


def chunk(article: str, text: str) -> dict:
    return {"article_id": article, "article_url": f"https://help.iqm.com/en/articles/{article}-x", "text": text}


class EvidenceRankTests(unittest.TestCase):
    def test_the_rank_is_that_of_the_first_chunk_from_the_right_article_containing_the_quote(self):
        chunks = [chunk("2", "Daily Pacing updates every hour."), chunk("1", "unrelated"), chunk("1", "### H\n\nDaily Pacing updates every hour.")]
        self.assertEqual(evidence_ranks(question(), chunks), [3])

    def test_markdown_marks_and_whitespace_do_not_prevent_a_match(self):
        self.assertEqual(evidence_ranks(question(), [chunk("1", "Daily   Pacing\n`updates` every hour.")]), [1])

    def test_a_quote_that_was_not_retrieved_has_no_rank(self):
        self.assertEqual(evidence_ranks(question(), [chunk("1", "something else")]), [None])

    def test_the_same_quote_in_another_article_does_not_count(self):
        self.assertEqual(evidence_ranks(question(), [chunk("2", "Daily Pacing updates every hour.")]), [None])

    def test_only_required_evidence_is_ranked_and_each_item_gets_its_own_rank(self):
        q = question(evidence=[
            {"article_id": "1", "url": URL1, "quote": "alpha", "required": True},
            {"article_id": "2", "url": URL2, "quote": "beta", "required": True},
            {"article_id": "3", "url": URL3, "quote": "gamma", "required": False}])
        chunks = [chunk("2", "beta"), chunk("3", "gamma"), chunk("1", "alpha")]
        self.assertEqual(evidence_ranks(q, chunks), [3, 1])

    def test_a_question_that_should_abstain_has_no_evidence_to_rank(self):
        self.assertEqual(evidence_ranks(question(evidence=[], should_abstain=True), [chunk("1", "x")]), [])


class RankMetricTests(unittest.TestCase):
    def test_recall_is_the_share_of_required_evidence_within_the_cut_off(self):
        self.assertEqual(recall_at([1, 7], 5), 0.5)
        self.assertEqual(recall_at([1, 7], 8), 1.0)
        self.assertEqual(recall_at([None, None], 8), 0.0)

    def test_recall_is_undefined_without_evidence(self):
        self.assertIsNone(recall_at([], 5))

    def test_reciprocal_rank_uses_the_first_evidence_found(self):
        self.assertEqual(reciprocal_rank([4, 2]), 0.5)
        self.assertEqual(reciprocal_rank([None, 3]), 1 / 3)
        self.assertEqual(reciprocal_rank([None]), 0.0)
        self.assertIsNone(reciprocal_rank([]))

    def test_article_rank_finds_the_first_chunk_from_an_expected_article(self):
        self.assertEqual(article_rank(question(), [chunk("2", "x"), chunk("1", "y")]), 2)
        self.assertIsNone(article_rank(question(), [chunk("2", "x")]))


class OutcomeTests(unittest.TestCase):
    def test_every_combination_of_expectation_and_status_has_a_named_outcome(self):
        answerable, abstain = question(), question(should_abstain=True)
        self.assertEqual(status_outcome(answerable, "answered"), "answered")
        self.assertEqual(status_outcome(answerable, "not_covered"), "wrongful_abstention")
        self.assertEqual(status_outcome(answerable, "clarification"), "over_clarified")
        self.assertEqual(status_outcome(abstain, "not_covered"), "correct_abstention")
        self.assertEqual(status_outcome(abstain, "answered"), "invented_answer")
        self.assertEqual(status_outcome(abstain, "clarification"), "clarified_instead")

    def test_only_a_right_answer_or_a_right_abstention_passes(self):
        self.assertEqual(OUTCOME_PASSES, {"answered", "correct_abstention"})


class CitationTests(unittest.TestCase):
    def test_precision_and_recall_against_the_expected_sources(self):
        q = question(expected_source_urls=[URL1, URL2])
        scores = citation_scores(q, [URL1, URL3])
        self.assertEqual((scores["precision"], scores["recall"], scores["wrong"], scores["clean"]), (0.5, 0.5, [URL3], False))

    def test_a_related_article_is_an_allowed_citation(self):
        scores = citation_scores(question(related_urls=[URL2]), [URL1, URL2])
        self.assertEqual((scores["precision"], scores["recall"], scores["clean"]), (1.0, 1.0, True))

    def test_citing_nothing_has_no_precision_and_zero_recall(self):
        scores = citation_scores(question(), [])
        self.assertEqual((scores["precision"], scores["recall"]), (None, 0.0))

    def test_an_abstention_that_cites_anything_is_wrong_and_one_that_cites_nothing_is_clean(self):
        q = question(should_abstain=True, expected_source_urls=[], evidence=[])
        self.assertTrue(citation_scores(q, [])["clean"])
        self.assertFalse(citation_scores(q, [URL1])["clean"])
        self.assertIsNone(citation_scores(q, [])["recall"])


class SummaryStatTests(unittest.TestCase):
    def test_percentile_is_nearest_rank(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual((percentile(values, 50), percentile(values, 90), percentile(values, 100)), (5, 9, 10))

    def test_describe_handles_no_values(self):
        self.assertEqual(describe([]), {"n": 0, "median": None, "p90": None, "mean": None, "max": None})
        self.assertEqual(describe([2.0, 4.0])["mean"], 3.0)

    def test_ratio_keeps_the_raw_count(self):
        self.assertEqual(ratio(3, 4), {"count": 3, "of": 4, "percent": 75.0})
        self.assertEqual(ratio(0, 0), {"count": 0, "of": 0, "percent": None})

    def test_cost_uses_stated_prices_and_never_guesses_for_an_unknown_model(self):
        self.assertAlmostEqual(cost_usd("gpt-4.1-mini", 2965, 125), 0.001386, places=6)
        self.assertAlmostEqual(cost_usd("text-embedding-3-large", 1_000_000, 0), 0.13)
        self.assertIsNone(cost_usd("some-new-model", 100, 10))
        self.assertIsNone(cost_usd("gpt-4.1-mini", None, 10))


def record(**overrides) -> dict:
    base = {"id": "q1", "split": "dev", "category": "direct_factual", "should_abstain": False, "status": "answered",
            "outcome": "answered", "evidence_ranks": [1], "recall_at": {1: 1.0, 3: 1.0, 5: 1.0, 8: 1.0}, "rr": 1.0, "article_rank": 1,
            "citation": {"precision": 1.0, "recall": 1.0, "clean": True, "wrong": []},
            "judge": {"facts_covered": 2, "facts_total": 2, "faithful": True, "error": None}, "wall_s": 3.0, "error": None}
    base.update(overrides)
    return base


class AggregateTests(unittest.TestCase):
    def test_counts_are_raw_numbers_with_a_percentage(self):
        records = [record(), record(id="q2", evidence_ranks=[None], recall_at={1: 0.0, 3: 0.0, 5: 0.0, 8: 0.0}, rr=0.0, article_rank=None,
                                    status="not_covered", outcome="wrongful_abstention", judge=None)]
        summary = aggregate(records)
        self.assertEqual(summary["questions"], 2)
        self.assertEqual(summary["retrieval"]["recall@8"], {"count": 1, "of": 2, "percent": 50.0})
        self.assertEqual(summary["retrieval"]["mrr"], 0.5)
        self.assertEqual(summary["retrieval"]["article_hit"]["count"], 1)
        self.assertEqual(summary["outcomes"]["wrongful_abstention"], 1)
        self.assertEqual(summary["abstention"]["passed"], {"count": 1, "of": 2, "percent": 50.0})

    def test_abstention_questions_are_left_out_of_retrieval_metrics_but_counted_for_abstention(self):
        records = [record(), record(id="q2", should_abstain=True, status="not_covered", outcome="correct_abstention", evidence_ranks=[],
                                    recall_at={1: None, 3: None, 5: None, 8: None}, rr=None, article_rank=None, judge=None,
                                    citation={"precision": None, "recall": None, "clean": True, "wrong": []})]
        summary = aggregate(records)
        self.assertEqual(summary["retrieval"]["recall@8"]["of"], 1)
        self.assertEqual(summary["abstention"]["correct_abstentions"], {"count": 1, "of": 1, "percent": 100.0})

    def test_generation_counts_only_judged_answers_and_reports_judge_errors(self):
        records = [record(), record(id="q2", judge={"facts_covered": 1, "facts_total": 2, "faithful": False, "error": None}),
                   record(id="q3", judge={"facts_covered": None, "facts_total": 2, "faithful": None, "error": "boom"})]
        generation = aggregate(records)["generation"]
        self.assertEqual(generation["judged"], 2)
        self.assertEqual(generation["all_facts_covered"], {"count": 1, "of": 2, "percent": 50.0})
        self.assertEqual(generation["faithful"], {"count": 1, "of": 2, "percent": 50.0})
        self.assertEqual(generation["mean_fact_coverage"], 0.75)
        self.assertEqual(generation["judge_errors"], 1)

    def test_end_to_end_correctness_counts_every_answerable_question(self):
        records = [record(), record(id="q2", status="not_covered", outcome="wrongful_abstention", judge=None)]
        self.assertEqual(aggregate(records)["generation"]["end_to_end_correct"], {"count": 1, "of": 2, "percent": 50.0})

    def test_a_question_that_errored_is_counted_and_does_not_break_the_summary(self):
        summary = aggregate([record(), {"id": "q2", "split": "dev", "category": "x", "should_abstain": False, "error": "boom"}])
        self.assertEqual(summary["errors"], 1)

    def test_latency_is_summarised(self):
        wall = aggregate([record(wall_s=2.0), record(id="q2", wall_s=4.0)])["operational"]["wall_s"]
        self.assertEqual((wall["median"], wall["p90"], wall["max"]), (3.0, 4.0, 4.0))

    def test_an_empty_run_is_summarised_without_error(self):
        self.assertEqual(aggregate([])["questions"], 0)


if __name__ == "__main__":
    unittest.main()
