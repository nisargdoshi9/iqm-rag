"""Chat messages and the history window shared by query rewriting, answering and the conversation helper (FR-6).

History is bounded to the last few exchanges and nothing is summarised. Earlier answers are context for understanding
what the user refers to, never evidence; answers must be grounded in documents retrieved for the current question.
"""

from dataclasses import dataclass
from typing import Sequence

MAX_HISTORY_EXCHANGES = 3  # judgement, not tuned: covers short pronoun chains and limits topic-switch drift
ROLES = ("user", "assistant")
SPEAKER_LABELS = {"user": "User", "assistant": "Assistant"}


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"A message role must be one of {ROLES}, got {self.role!r}.")
        if not self.content.strip():
            raise ValueError("A message cannot have empty content.")


def messages_from_dicts(items: Sequence[dict]) -> list[Message]:
    """Messages from the evaluation set's {"role", "content"} format."""
    messages = []
    for item in items:
        missing = [key for key in ("role", "content") if key not in item]
        if missing:
            raise ValueError(f"A history message is missing {missing}: {item!r}.")
        messages.append(Message(item["role"], item["content"]))
    return messages


def trim_history(history: Sequence[Message], max_exchanges: int = MAX_HISTORY_EXCHANGES) -> list[Message]:
    """The last `max_exchanges` exchanges (a user message and the reply that follows it), oldest dropped."""
    if max_exchanges < 1:
        raise ValueError(f"max_exchanges must be at least 1 exchange, got {max_exchanges}.")
    user_positions = [i for i, message in enumerate(history) if message.role == "user"]
    if not user_positions:
        return []
    return list(history[user_positions[-max_exchanges:][0]:])


def format_history(history: Sequence[Message]) -> str:
    return "\n".join(f"{SPEAKER_LABELS[m.role]}: {m.content}" for m in history)
