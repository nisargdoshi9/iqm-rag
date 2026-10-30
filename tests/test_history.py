"""Tests for chat messages and the history window (FR-6). No network calls."""

import unittest

from iqm_rag.history import MAX_HISTORY_EXCHANGES, Message, format_history, messages_from_dicts, trim_history


def user(text: str) -> Message:
    return Message("user", text)


def assistant(text: str) -> Message:
    return Message("assistant", text)


def exchanges(n: int) -> list[Message]:
    return [m for i in range(1, n + 1) for m in (user(f"q{i}"), assistant(f"a{i}"))]


class MessageTests(unittest.TestCase):
    def test_roles_are_limited_to_user_and_assistant(self):
        with self.assertRaisesRegex(ValueError, "role"):
            Message("system", "text")

    def test_blank_content_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            Message("user", "   ")

    def test_messages_load_from_the_evaluation_set_format(self):
        loaded = messages_from_dicts([{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}])
        self.assertEqual(loaded, [user("Hi"), assistant("Hello")])

    def test_a_dict_missing_a_field_is_reported_clearly(self):
        with self.assertRaisesRegex(ValueError, "content"):
            messages_from_dicts([{"role": "user"}])


class TrimTests(unittest.TestCase):
    def test_the_default_window_is_three_exchanges(self):
        self.assertEqual(MAX_HISTORY_EXCHANGES, 3)

    def test_only_the_last_exchanges_are_kept_oldest_dropped(self):
        trimmed = trim_history(exchanges(5), 3)
        self.assertEqual([m.content for m in trimmed], ["q3", "a3", "q4", "a4", "q5", "a5"])

    def test_a_short_history_is_kept_whole(self):
        self.assertEqual(trim_history(exchanges(2), 3), exchanges(2))

    def test_a_trailing_question_without_an_answer_counts_as_an_exchange(self):
        trimmed = trim_history(exchanges(2) + [user("q3")], 2)
        self.assertEqual([m.content for m in trimmed], ["q2", "a2", "q3"])

    def test_a_leading_assistant_message_is_dropped(self):
        self.assertEqual(trim_history([assistant("welcome")] + exchanges(1), 3), exchanges(1))

    def test_no_user_message_means_no_history(self):
        self.assertEqual(trim_history([assistant("welcome")], 3), [])
        self.assertEqual(trim_history([], 3), [])

    def test_a_window_below_one_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exchange"):
            trim_history(exchanges(1), 0)


class FormatTests(unittest.TestCase):
    def test_each_message_is_labelled_by_speaker_in_order(self):
        self.assertEqual(format_history(exchanges(1)), "User: q1\nAssistant: a1")

    def test_no_history_gives_an_empty_string(self):
        self.assertEqual(format_history([]), "")


if __name__ == "__main__":
    unittest.main()
