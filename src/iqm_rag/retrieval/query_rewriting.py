"""Turn a follow-up question into a standalone retrieval query (FR-6).

From the second turn, a small model rewrites the user's latest message using the recent history. It returns the
message unchanged when it is already standalone. If the call fails or the reply looks wrong, the raw question is used
and the reason is recorded, so a rewrite problem never blocks an answer. Retrieval stays independent of history: the
retriever only ever receives the resulting query string.
"""

import re
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import OpenAIError

from iqm_rag import config
from iqm_rag.history import Message, format_history
from iqm_rag.usage import Usage, usage_from_message

REWRITE_MAX_CHARS = 500  # a longer reply is more likely an answer or an explanation than a question
REWRITE_MAX_OUTPUT_TOKENS = 300
MS_PER_SECOND = 1000.0
WRAPPING_QUOTES = "\"'“”‘’"

SYSTEM_PROMPT = """# Role and Objective
You rewrite the user's latest message in a support chat about the IQM platform into one standalone question that can \
be understood without the conversation, so it can be used to search the Help Center.

# Instructions
- Use the conversation only to resolve references such as "it", "that", "those settings" or "the second one".
- Keep the user's intent, constraints, entity names, product terms and requested format exactly. Do not add facts or \
details that are not in the conversation.
- If the latest message is already understandable on its own, or the user has moved to a new topic, return it \
unchanged.
- Never answer the question and never explain what you did.
- Write in the same language as the latest message.

# Output Format
Return only the standalone question, on a single line."""

HUMAN_PROMPT = """# Conversation
{history}

# Latest message
{question}

# Final reminder
Return only the standalone question on one line. If the latest message is already standalone, return it unchanged."""


@dataclass(frozen=True)
class RewriteResult:
    original: str
    query: str  # what retrieval searches with
    rewritten: bool  # the query differs from the original
    fallback_reason: Optional[str]  # set when the raw question was used because the rewrite could not be trusted
    model: Optional[str]  # None when no model was called (first turn)
    usage: Optional[Usage]
    ms: float

    def to_dict(self) -> dict:
        return {"original": self.original, "query": self.query, "rewritten": self.rewritten,
                "fallback_reason": self.fallback_reason, "model": self.model, "ms": self.ms,
                "usage": None if self.usage is None else vars(self.usage)}


def build_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)])


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _problem(reply) -> Optional[str]:
    """Why the model's reply cannot be trusted as a query, or None if it can."""
    if reply.response_metadata.get("finish_reason") == "length":
        return "the rewrite was cut off at the length limit"
    text = str(reply.content).strip().strip(WRAPPING_QUOTES).strip()
    if not text:
        return "the rewrite was empty"
    if "\n" in text:
        return "the rewrite had more than one line"
    if len(text) > REWRITE_MAX_CHARS:
        return f"the rewrite was too long ({len(text)} characters)"
    return None


class QueryRewriter:
    def __init__(self, llm: Runnable, model: str) -> None:
        self._model = model
        self._chain = build_prompt() | llm

    def rewrite(self, question: str, history: Sequence[Message]) -> RewriteResult:
        if not history:
            return RewriteResult(question, question, False, None, None, None, 0.0)
        started = time.perf_counter()
        try:
            reply = self._chain.invoke({"history": format_history(history), "question": question})
        except OpenAIError as exc:
            return self._fallback(question, f"the rewrite call failed: {type(exc).__name__}: {exc}", None, started)
        problem = _problem(reply)
        if problem:
            return self._fallback(question, problem, usage_from_message(reply), started)
        query = str(reply.content).strip().strip(WRAPPING_QUOTES).strip()
        elapsed = (time.perf_counter() - started) * MS_PER_SECOND
        return RewriteResult(question, query, _normalise(query) != _normalise(question), None, self._model,
                             usage_from_message(reply), elapsed)

    def _fallback(self, question: str, reason: str, usage: Optional[Usage], started: float) -> RewriteResult:
        elapsed = (time.perf_counter() - started) * MS_PER_SECOND
        return RewriteResult(question, question, False, f"Used the original question: {reason}.", self._model, usage, elapsed)


def default_rewriter() -> QueryRewriter:
    """The rewriter configured in the environment (OPENAI_API_KEY, REWRITE_MODEL or CHAT_MODEL)."""
    model = config.rewrite_model()
    chat = ChatOpenAI(model=model, temperature=0, api_key=config.openai_api_key(), max_retries=config.LLM_MAX_RETRIES,
                      timeout=config.LLM_TIMEOUT_SECONDS, max_tokens=REWRITE_MAX_OUTPUT_TOKENS)
    return QueryRewriter(chat, model)
