"""Tests for the per-session conversation helper (FR-6). A stub chain; no network calls."""

import unittest
from types import SimpleNamespace

from iqm_rag.generation.conversation import Conversation
from iqm_rag.history import Message


class StubChain:
    """Records what it is asked and answers 'answer to <question>'."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Message]]] = []
        self.fail_next = False

    def answer(self, question: str, history: list[Message]):
        self.calls.append((question, list(history)))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("model unavailable")
        return SimpleNamespace(question=question.strip(), text=f"answer to {question.strip()}")


class ConversationTests(unittest.TestCase):
    def test_the_first_question_has_no_history(self):
        chain, convo = StubChain(), Conversation()
        convo.ask(chain, "q1")
        self.assertEqual(chain.calls[0], ("q1", []))

    def test_the_next_question_sees_the_previous_exchange(self):
        chain, convo = StubChain(), Conversation()
        convo.ask(chain, "q1")
        convo.ask(chain, "q2")
        self.assertEqual(chain.calls[1][1], [Message("user", "q1"), Message("assistant", "answer to q1")])

    def test_only_the_last_three_exchanges_are_passed_on(self):
        chain, convo = StubChain(), Conversation()
        for n in range(1, 6):
            convo.ask(chain, f"q{n}")
        history = chain.calls[4][1]  # the fifth question sees exchanges 2, 3 and 4
        self.assertEqual([m.content for m in history if m.role == "user"], ["q2", "q3", "q4"])
        self.assertEqual(len(convo.turns), 5)  # the transcript itself is kept whole

    def test_two_conversations_do_not_share_history(self):
        chain, first, second = StubChain(), Conversation(), Conversation()
        first.ask(chain, "from the first session")
        second.ask(chain, "from the second session")
        self.assertEqual(chain.calls[1][1], [])

    def test_reset_starts_a_fresh_conversation(self):
        chain, convo = StubChain(), Conversation()
        convo.ask(chain, "q1")
        convo.reset()
        convo.ask(chain, "q2")
        self.assertEqual((chain.calls[1][1], len(convo.turns)), ([], 1))

    def test_a_failed_turn_is_not_recorded(self):
        chain, convo = StubChain(), Conversation()
        convo.ask(chain, "q1")
        chain.fail_next = True
        with self.assertRaises(RuntimeError):
            convo.ask(chain, "q2")
        convo.ask(chain, "q3")
        self.assertEqual([m.content for m in chain.calls[2][1]], ["q1", "answer to q1"])

    def test_turns_keep_the_question_and_the_answer(self):
        chain, convo = StubChain(), Conversation()
        convo.ask(chain, "  q1 ")
        turn = convo.turns[0]
        self.assertEqual((turn.question, turn.answer.text), ("q1", "answer to q1"))

    def test_the_window_can_be_changed(self):
        chain, convo = StubChain(), Conversation(max_exchanges=1)
        for n in range(1, 4):
            convo.ask(chain, f"q{n}")
        self.assertEqual([m.content for m in chain.calls[2][1]], ["q2", "answer to q2"])


if __name__ == "__main__":
    unittest.main()
