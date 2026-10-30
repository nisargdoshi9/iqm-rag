"""Tests for the HTML snippets (FR-7): escaping, safe links and the pieces that must be present."""

import unittest

from iqm_rag.ui.render import (actions_html, badge_html, brand_html, input_hint_html, trust_html, details_html, evidence_html, evidence_section_html, evidence_title,
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

    def test_the_sections_and_an_open_hint_are_in_the_hover_tooltip_not_on_the_pill(self):
        html = sources_html([self.link()])
        tip = html.split('<span class="tip">')[1]
        self.assertIn('<span class="tip-sec">Send a report</span><span class="tip-sec">Edit</span>', tip)
        self.assertIn("Click to open this article", tip)
        self.assertEqual(html.count("Send a report"), 1)

    def test_the_label_tells_the_user_that_sources_can_be_opened(self):
        self.assertIn("hover for details, click to open", sources_html([self.link()]))

    def test_up_to_three_sources_show_with_no_more_toggle(self):
        html = sources_html([self.link(n) for n in range(1, 4)])
        self.assertEqual(html.count('class="src"'), 3)
        self.assertNotIn("more", html.replace("more_", ""))

    def test_extra_sources_sit_behind_a_plus_n_more_toggle(self):
        html = sources_html([self.link(n, title=f"Article {n}") for n in range(1, 6)])
        self.assertIn("+2 more", html)
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

    def test_the_input_hint_names_the_keyboard_shortcuts(self):
        hint = input_hint_html()
        for key in ("Enter", "Shift", "/"):
            self.assertIn(f"<kbd>{key}</kbd>", hint)

    def test_a_multi_paragraph_answer_cannot_break_the_markup(self):
        html = actions_html("First paragraph.\n\nSecond paragraph.\r\nThird.")
        self.assertNotIn("\n", html)
        self.assertIn("First paragraph.&#10;&#10;Second paragraph.&#10;Third.", html)

    def test_the_copy_button_carries_the_answer_text_safely(self):
        html = actions_html('Click "Save" <b>now</b> & done')
        self.assertIn('data-copy="Click &quot;Save&quot; &lt;b&gt;now&lt;/b&gt; &amp; done"', html)
        self.assertNotIn("<b>", html)
        self.assertIn('class="copy-label">Copy<', html)
        self.assertNotIn("<button", html)  # the markdown sanitizer would remove it
        self.assertIn('role="button" tabindex="0"', html)


if __name__ == "__main__":
    unittest.main()
