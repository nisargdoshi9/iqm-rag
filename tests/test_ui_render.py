"""Tests for the HTML snippets (FR-7): escaping, safe links and the pieces that must be present."""

import unittest

from iqm_rag.ui.render import (badge_html, brand_html, trust_html, details_html, evidence_html, evidence_section_html, evidence_title,
                               hero_html, loading_html, sources_html)
from iqm_rag.ui.view import AnswerView, EvidenceItem, SourceLink

EVIL = '<script>alert("x")</script>'


class SourcesTests(unittest.TestCase):
    def link(self, n: int = 1, title: str = "Reports", sections=("Send a report", "Edit")) -> SourceLink:
        return SourceLink(title, tuple(sections), f"https://help.iqm.com/en/articles/{n}-x")

    def test_no_sources_gives_no_markup(self):
        self.assertEqual(sources_html(()), "")

    def test_a_source_is_a_pill_link_that_opens_in_a_new_tab_safely(self):
        html = sources_html([self.link()])
        self.assertIn('href="https://help.iqm.com/en/articles/1-x"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('<span class="src-text">Reports</span>', html)

    def test_the_tooltip_adds_the_section_an_extract_and_the_destination(self):
        link = SourceLink("Reports", ("Send a report", "Edit"), "https://help.iqm.com/en/articles/1-x", ("Follow these steps to send.", "Pick the pencil icon."))
        tip = sources_html([link]).split('<span class="tip">')[1]
        self.assertIn('<span class="tip-sec">Send a report</span><span class="tip-prev">“Follow these steps to send.”</span>', tip)
        self.assertIn('<span class="tip-sec">Edit</span><span class="tip-prev">“Pick the pencil icon.”</span>', tip)
        self.assertIn("Opens help.iqm.com in a new tab", tip)

    def test_the_tooltip_does_not_repeat_a_title_that_the_pill_already_shows(self):
        html = sources_html([self.link(title="Short title")])
        self.assertEqual(html.count("Short title"), 1)

    def test_a_long_title_that_the_pill_cuts_off_is_shown_in_full_in_the_tooltip(self):
        title = "A very long article title that will be cut short on the pill"
        html = sources_html([self.link(title=title)])
        self.assertIn(f'<span class="tip-title">{title}</span>', html)

    def test_a_section_without_a_preview_still_gets_a_tooltip(self):
        html = sources_html([self.link()])
        self.assertIn('<span class="tip-sec">Send a report</span>', html)
        self.assertNotIn("tip-prev", html)

    def test_the_label_tells_the_user_that_sources_can_be_opened(self):
        self.assertIn("hover for details, click to open", sources_html([self.link()]))

    def test_up_to_three_sources_show_with_no_more_toggle(self):
        html = sources_html([self.link(n) for n in range(1, 4)])
        self.assertEqual(html.count('class="src"'), 3)
        self.assertNotIn("more", html.replace("more_", ""))

    def test_extra_sources_sit_behind_a_plus_n_more_toggle(self):
        html = sources_html([self.link(n, title=f"Article {n}") for n in range(1, 6)])
        self.assertIn("+2 more", html)
        self.assertIn('<span class="when-open">Show less</span>', html)
        visible, hidden = html.split('<details class="more">')
        self.assertEqual(visible.count('class="src"'), 3)
        self.assertEqual(hidden.count('class="src"'), 2)
        self.assertIn("Article 5", hidden)

    def test_titles_and_sections_are_escaped(self):
        html = sources_html([SourceLink(EVIL, (EVIL,), "https://help.iqm.com/x")])
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_a_non_http_url_is_never_made_a_link(self):
        html = sources_html([SourceLink("T", ("S",), "javascript:alert(1)")])
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<a ", html)


class EvidenceTests(unittest.TestCase):
    ITEMS = (EvidenceItem(1, 0.73, "Title › A", "Some text", "https://help.iqm.com/x", True),
             EvidenceItem(2, 0.5, "Other › B", EVIL, "https://help.iqm.com/y", False))

    def test_each_passage_shows_rank_score_and_whether_it_was_used(self):
        html = evidence_html(self.ITEMS)
        self.assertEqual(html.count('<span class="pill">used</span>'), 1)
        self.assertIn("<span>0.73</span>", html)
        self.assertIn('style="width:73%"', html)

    def test_passage_text_is_escaped(self):
        self.assertNotIn("<script>", evidence_html(self.ITEMS))

    def test_the_title_counts_passages_and_used_ones(self):
        self.assertEqual(evidence_title(self.ITEMS), "Retrieved passages · 2 searched, 1 used in the answer")

    def test_the_section_is_empty_without_passages_and_has_a_heading_with_them(self):
        self.assertEqual(evidence_section_html(()), "")
        self.assertIn("Retrieved passages", evidence_section_html(self.ITEMS))

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

    def test_the_hero_trust_points_and_brand_state_the_grounding_promise(self):
        self.assertIn("only from the IQM Help Center", hero_html())
        self.assertIn("help.iqm.com", trust_html())
        self.assertIn("help.iqm.com", brand_html())


if __name__ == "__main__":
    unittest.main()
