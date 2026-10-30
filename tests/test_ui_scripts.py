"""Tests for the JavaScript snippets (FR-7). They check the generated text; behaviour is checked in a real browser."""

import re
import unittest

from iqm_rag.ui.scripts import INPUT_SELECTOR, MESSAGE_SELECTOR, page_script


class PageScriptTests(unittest.TestCase):
    def test_every_run_gets_different_text_so_the_browser_runs_it_again(self):
        self.assertNotEqual(page_script(1, True), page_script(2, True))

    def test_it_is_a_script_block(self):
        script = page_script(1, True)
        self.assertTrue(script.startswith("<script>") and script.endswith("</script>"))

    def test_focus_is_only_included_when_asked_for(self):
        self.assertIn(INPUT_SELECTOR, page_script(1, True))
        self.assertNotIn("tries > 30", page_script(1, False))
        self.assertIn("tries > 30", page_script(1, True))

    def test_a_forced_focus_overrides_the_do_not_steal_focus_rules(self):
        self.assertIn("})(true);", page_script(1, True, force_focus=True))
        self.assertIn("})(false);", page_script(1, True, force_focus=False))

    def test_focus_does_not_steal_from_text_selection_other_fields_or_the_sidebar(self):
        script = page_script(1, True)
        for guard in ("getSelection", "stSidebar", "isContentEditable"):
            self.assertIn(guard, script)

    def test_scroll_keeps_the_question_with_its_answer_and_starts_a_long_answer_at_its_question(self):
        script = page_script(1, False, scroll="start")
        self.assertIn("const align = 'start';", script)
        self.assertIn("align === 'start' && exchange > room", script)
        self.assertIn("question.scrollIntoView", script)
        self.assertIn("steady >= 3", script)  # waits for the layout and Streamlit's own scroll to settle first
        self.assertIn("stAppScrollToBottomContainer", script)
        self.assertIn("block: 'end'", page_script(1, False, scroll="end"))
        self.assertIn("const align = 'end';", page_script(1, False, scroll="end"))
        self.assertIn(MESSAGE_SELECTOR, page_script(1, False, scroll="end"))
        self.assertNotIn("scrollIntoView", page_script(1, False))

    def test_an_unknown_scroll_alignment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "scroll"):
            page_script(1, False, scroll="middle")

    def test_the_slash_shortcut_is_installed_only_once(self):
        script = page_script(1, False)
        self.assertIn("if (!window.__iqmUx)", script)
        self.assertIn("event.key !== '/'", script)
        self.assertNotIn("clipboard", script)

    def test_a_latest_button_appears_only_when_the_reader_is_away_from_the_bottom(self):
        script = page_script(1, False)
        self.assertIn("jump-latest", script)
        self.assertIn("button.classList.toggle('visible'", script)
        self.assertIn("> 160", script)
        click = script.split("button.addEventListener('click'")[1].split("document.body.appendChild")[0]
        self.assertIn("box.focus", click)  # after jumping down the cursor goes back to the input

    def test_an_arriving_answer_does_not_pull_the_page_if_the_reader_scrolled_up(self):
        script = page_script(1, False, scroll="start")
        self.assertIn("if (window.__iqmUserMoved)", script)
        self.assertIn("event.deltaY < 0", script)

    def test_the_users_own_send_always_scrolls_and_resets_the_reader_flag(self):
        script = page_script(1, False, scroll="end")
        self.assertIn("if (align === 'end') { window.__iqmUserMoved = false;", script)

    def test_motion_preferences_and_screen_readers_are_respected(self):
        script = page_script(1, False)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn("aria-live", script)
        self.assertIn("'log'", script)

    def test_times_are_shown_in_the_readers_time_zone(self):
        script = page_script(1, False)
        self.assertIn(".msg-time[data-ts]", script)
        self.assertIn("toLocaleTimeString", script)

    def test_the_script_text_has_nothing_the_html_sanitizer_would_strip_it_for(self):
        # st.html sanitizes with DOMPurify, which removes a script whose text contains "<" followed by a letter, "/" or "!"
        for flags in ((False, False, "", ), (True, True, "start"), (True, False, "end")):
            script = page_script(1, flags[0], flags[1], flags[2])
            body = script[len("<script>"):-len("</script>")]
            self.assertIsNone(re.search(r"<[/\w!]", body), body[:80])

    def test_the_nonce_cannot_inject_code(self):
        with self.assertRaises(ValueError):
            page_script("1; alert(1)", False)


if __name__ == "__main__":
    unittest.main()
