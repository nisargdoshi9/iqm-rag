"""Smoke tests that drive the Streamlit page with Streamlit's own test runner and a fake model; no network."""

import logging
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from openai import OpenAIError

from iqm_rag.generation.chain import GenerationError
from iqm_rag.ui.chat_app import PLACEHOLDER_FIRST, PLACEHOLDER_FOLLOW_UP, SETUP_HELP
from test_generation import ChainTestCase, FakeLLM, draft



for _name in list(logging.root.manager.loggerDict):
    if _name.startswith("streamlit"):  # the test runner logs 'missing ScriptRunContext' on every run; expected and harmless
        logging.getLogger(_name).setLevel(logging.CRITICAL)

def app_script(factory):
    from iqm_rag.ui.chat_app import run

    run(factory)


class BrokenChain:
    def answer(self, question, history):
        raise GenerationError("model request failed: secret detail")


class PageTests(ChainTestCase):
    def page(self, llm: FakeLLM = None, chain=None) -> AppTest:
        built = chain or self.chain(llm or FakeLLM(draft([1])))
        return AppTest.from_function(app_script, args=(lambda: built,), default_timeout=10).run()

    def texts(self, at: AppTest) -> str:
        return " ".join(m.value for m in at.markdown)

    def test_the_first_screen_shows_the_welcome_and_three_example_questions(self):
        at = self.page()
        self.assertFalse(at.exception)
        self.assertIn("What can I help you find?", self.texts(at))
        self.assertEqual([b.key for b in at.button if b.key and b.key.startswith("example_")], ["example_0", "example_1", "example_2"])
        self.assertEqual(len(at.chat_message), 0)

    def test_asking_a_question_shows_the_answer_its_status_and_its_sources(self):
        at = self.page()
        at.chat_input[0].set_value("schedule a report").run()
        self.assertFalse(at.exception)
        self.assertEqual([m.name for m in at.chat_message], ["user", "assistant"])
        text = self.texts(at)
        self.assertIn("Use the Reports tab.", text)
        self.assertIn("From the Help Center", text)
        self.assertIn("https://help.iqm.com/en/articles/1-t", text)
        self.assertNotIn("What can I help you find?", text)

    def test_the_retrieved_passages_are_only_shown_in_developer_mode(self):
        at = self.page()
        at.chat_input[0].set_value("schedule a report").run()
        self.assertEqual(len(at.expander), 0)
        self.assertNotIn("Retrieved passages", self.texts(at))
        at.toggle(key="developer_mode").set_value(True).run()
        self.assertIn("Retrieved passages", self.texts(at))
        self.assertTrue(any(e.label == "Developer details" for e in at.expander))

    def test_clicking_an_example_asks_that_question(self):
        at = self.page()
        at.button(key="example_0").click().run()
        self.assertFalse(at.exception)
        self.assertEqual([m.name for m in at.chat_message], ["user", "assistant"])

    def test_a_follow_up_keeps_the_whole_transcript(self):
        at = self.page(FakeLLM(draft([1])))
        at.chat_input[0].set_value("first").run()
        at.chat_input[0].set_value("and then").run()
        self.assertEqual(len(at.chat_message), 4)

    def test_the_box_invites_a_first_question_then_a_follow_up_and_goes_back_on_new_chat(self):
        at = self.page()
        self.assertEqual(at.chat_input[0].placeholder, PLACEHOLDER_FIRST)
        at.chat_input[0].set_value("schedule a report").run()
        self.assertEqual(at.chat_input[0].placeholder, PLACEHOLDER_FOLLOW_UP)
        at.button(key="new_chat").click().run()
        self.assertEqual(at.chat_input[0].placeholder, PLACEHOLDER_FIRST)

    def test_there_is_no_copy_button_hint_or_character_counter(self):
        at = self.page()
        at.chat_input[0].set_value("schedule a report").run()
        text = self.texts(at)
        self.assertNotIn("data-copy", text)
        self.assertNotIn("input-hint", text)
        self.assertFalse(at.chat_input[0].max_chars)  # no limit, so no counter is shown

    def test_a_question_over_the_search_limit_gets_a_friendly_explanation_not_a_crash(self):
        at = self.page()
        at.chat_input[0].set_value("x" * 2500).run()
        self.assertFalse(at.exception)
        self.assertIn("couldn't use that question", self.texts(at))

    def test_the_page_is_unlocked_again_once_an_answer_is_shown(self):
        at = self.page()
        at.chat_input[0].set_value("schedule a report").run()
        self.assertIsNone(at.session_state["pending_question"])
        self.assertFalse(at.chat_input[0].disabled)
        self.assertFalse(at.button(key="new_chat").disabled)

    def test_a_follow_up_sends_the_earlier_exchange_as_history(self):
        llm = FakeLLM(draft([1]))
        at = self.page(llm)
        at.chat_input[0].set_value("schedule a report").run()
        at.chat_input[0].set_value("and then?").run()
        self.assertIn("schedule a report", llm.prompts[1][1].content.split("# Context")[0])

    def test_a_failed_question_is_not_added_to_the_history(self):
        llm = FakeLLM(draft([1]), error=OpenAIError("down"))
        at = self.page(llm)
        at.chat_input[0].set_value("schedule a report").run()
        self.assertEqual(len(at.session_state["conversation"].turns), 0)

    def test_new_chat_clears_the_transcript(self):
        at = self.page()
        at.chat_input[0].set_value("schedule a report").run()
        at.button(key="new_chat").click().run()
        self.assertEqual(len(at.chat_message), 0)
        self.assertIn("What can I help you find?", self.texts(at))

    def test_developer_mode_reveals_the_details_panel(self):
        at = self.page()
        at.chat_input[0].set_value("schedule a report").run()
        self.assertFalse(any(e.label == "Developer details" for e in at.expander))
        at.toggle(key="developer_mode").set_value(True).run()
        self.assertTrue(any(e.label == "Developer details" for e in at.expander))

    def test_a_not_covered_answer_shows_its_own_label_and_no_sources(self):
        at = self.page(FakeLLM(draft([], status="not_covered", answer="The Help Center does not cover this.")))
        at.chat_input[0].set_value("tiktok").run()
        text = self.texts(at)
        self.assertIn("Not in the Help Center", text)
        self.assertNotIn("Sources", text)

    def test_a_clarifying_question_is_not_labelled_as_missing_from_the_help_center(self):
        at = self.page(FakeLLM(draft([], status="clarification", answer="Which settings do you mean?")))
        at.chat_input[0].set_value("settings").run()
        text = self.texts(at)
        self.assertIn("A quick question", text)
        self.assertNotIn("Not in the Help Center", text)

    def test_a_failure_shows_a_friendly_message_and_hides_the_detail_until_developer_mode(self):
        at = self.page(chain=BrokenChain())
        at.chat_input[0].set_value("schedule a report").run()
        self.assertFalse(at.exception)
        self.assertIn("Something went wrong", self.texts(at))
        self.assertNotIn("secret detail", self.texts(at))
        at.toggle(key="developer_mode").set_value(True).run()
        self.assertIn("secret detail", self.texts(at))

    def test_a_startup_failure_explains_what_to_check(self):
        def failing_factory():
            raise RuntimeError("OPENAI_API_KEY is not set")

        at = AppTest.from_function(app_script, args=(failing_factory,), default_timeout=10).run()
        self.assertTrue(any(SETUP_HELP in e.value for e in at.error))
        self.assertFalse(at.exception)


class ConfigTests(unittest.TestCase):
    def test_the_theme_and_the_entry_point_exist(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('primaryColor = "#4F46E5"', (root / ".streamlit" / "config.toml").read_text())
        self.assertIn("run(default_chain)", (root / "app.py").read_text())


if __name__ == "__main__":
    unittest.main()
