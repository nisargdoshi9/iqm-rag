"""Tests for the HTML snippets (FR-7): escaping, safe links and the pieces that must be present."""

import unittest

from iqm_rag.ui.render import (badge_html, brand_html, details_html, evidence_html, evidence_title, hero_html, loading_html,
                               sources_html)
from iqm_rag.ui.view import AnswerView, EvidenceItem, SourceLink

EVIL = '<script>alert("x")</script>'


class SourcesTests(unittest.TestCase):
    def test_no_sources_gives_no_markup(self):
        self.assertEqual(sources_html(()), "")

    def test_a_source_is_a_link_that_opens_in_a_new_tab_safely(self):
        html = sources_html([SourceLink("Reports", ("Send a report", "Edit"), "https://help.iqm.com/en/articles/1-x")])
        self.assertIn('href="https://help.iqm.com/en/articles/1-x"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('<span class="chip-sub">Send a report</span><span class="chip-sub">Edit</span>', html)

    def test_titles_and_sections_are_escaped(self):
        html = sources_html([SourceLink(EVIL, (EVIL,), "https://help.iqm.com/x")])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_a_non_http_url_is_never_made_a_link(self):
        html = sources_html([SourceLink("T", ("S",), "javascript:alert(1)")])
        self.assertNotIn("javascript:", html)


class EvidenceTests(unittest.TestCase):
    ITEMS = (EvidenceItem(1, 0.73, "Title › A", "Some text", "https://help.iqm.com/x", True),
             EvidenceItem(2, 0.5, "Other › B", EVIL, "https://help.iqm.com/y", False))

    def test_each_passage_shows_rank_match_and_whether_it_was_used(self):
        html = evidence_html(self.ITEMS)
        self.assertIn("used in answer", html)
        self.assertEqual(html.count("used in answer"), 1)
        self.assertIn("0.73 match", html)
        self.assertIn('style="width:73%"', html)

    def test_passage_text_is_escaped(self):
        self.assertNotIn("<script>", evidence_html(self.ITEMS))

    def test_the_title_counts_passages_and_used_ones(self):
        self.assertEqual(evidence_title(self.ITEMS), "Evidence · 2 passages searched, 1 used")
        self.assertEqual(evidence_title(self.ITEMS[1:]), "Evidence · 1 passages searched")

    def test_a_similarity_outside_zero_to_one_cannot_break_the_bar(self):
        html = evidence_html((EvidenceItem(1, 1.4, "T", "s", "", False), EvidenceItem(2, -0.2, "T", "s", "", False)))
        self.assertIn("width:100%", html)
        self.assertIn("width:0%", html)


class OtherPieceTests(unittest.TestCase):
    def test_badges_carry_the_status_and_its_label(self):
        self.assertIn("badge-not_covered", badge_html("not_covered"))
        self.assertIn("Not in the Help Center", badge_html("not_covered"))

    def test_developer_details_are_escaped(self):
        view = AnswerView("answered", "t", (), (), (("Question as typed", EVIL),), ())
        self.assertNotIn("<script>", details_html(view))

    def test_the_loading_message_is_escaped_and_animated(self):
        html = loading_html("Reading <b>this</b>…")
        self.assertIn("&lt;b&gt;", html)
        self.assertIn('class="dots"', html)

    def test_the_hero_and_brand_state_the_grounding_promise(self):
        self.assertIn("help.iqm.com", hero_html())
        self.assertIn("help.iqm.com", brand_html())


if __name__ == "__main__":
    unittest.main()
