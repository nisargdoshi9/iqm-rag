"""One chat session (FR-6): the turns so far and the bounded history passed to the chain.

Each session owns its own `Conversation`, so sessions cannot mix. The chain stays stateless. A turn that fails is not
recorded, so an error never pollutes the history. Abstentions are recorded: the user can follow up on them.
"""

import uuid
from dataclasses import dataclass

from iqm_rag.generation.chain import Answer, AnswerChain
from iqm_rag.history import MAX_HISTORY_EXCHANGES, Message, trim_history


@dataclass(frozen=True)
class Turn:
    question: str
    answer: Answer


class Conversation:
    def __init__(self, max_exchanges: int = MAX_HISTORY_EXCHANGES) -> None:
        self._max_exchanges = max_exchanges
        self._turns: list[Turn] = []
        self.session_id = uuid.uuid4().hex  # groups this chat's traces into one thread

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    def history(self) -> list[Message]:
        """The last few exchanges as messages: the user's questions and the answers shown to them."""
        messages = [m for turn in self._turns for m in (Message("user", turn.question), Message("assistant", turn.answer.text))]
        return trim_history(messages, self._max_exchanges)

    def record(self, answer: Answer) -> None:
        """Add a finished turn. Used by `ask`, and by callers that run the chain elsewhere (for example in a worker thread)."""
        self._turns.append(Turn(answer.question, answer))

    def ask(self, chain: AnswerChain, question: str) -> Answer:
        answer = chain.answer(question, self.history(), session_id=self.session_id)
        self.record(answer)
        return answer

    def reset(self) -> None:
        self._turns.clear()
        self.session_id = uuid.uuid4().hex
