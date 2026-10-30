"""The RAG chain (FR-5, FR-6): rewrite, retrieve, build context, prompt, model, check the output.

Built from LangChain runnables with named steps so tracing shows each one. Retrieval is separate from generation:
the chain only calls the retriever and reads its result. The chain is stateless; the caller passes the history, and
`Conversation` keeps it per session. A reply cut off at the length limit is retried once with a higher limit and a
request to be concise; if that also fails the user gets a plain message, never an error caused by our own cap.
"""

import time
from dataclasses import dataclass
from typing import Optional, Sequence

from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from langchain_openai import ChatOpenAI
from openai import LengthFinishReasonError, OpenAIError

from iqm_rag import config
from iqm_rag.generation.citations import Citation, ResolvedAnswer, resolve_answer
from iqm_rag.generation.context import ContextDoc, build_context_docs, format_context
from iqm_rag.generation.prompts import CONCISE_NOTE, PROMPT_VERSION, AnswerDraft, Status, build_prompt, render_history_block
from iqm_rag.history import Message, trim_history
from iqm_rag.retrieval.query_rewriting import QueryRewriter, RewriteResult, default_rewriter
from iqm_rag.retrieval.retriever import RetrievalResult, Retriever, default_retriever
from iqm_rag.usage import Usage, usage_from_message

MAX_OUTPUT_TOKENS = 2000
RETRY_MAX_OUTPUT_TOKENS = 4000  # used once, only when the first reply was cut off at the limit
MS_PER_SECOND = 1000.0
TRUNCATED_MESSAGE = (
    "The full answer to this is longer than I can write in one message. "
    "Please ask about one part at a time, for example a single step or setting."
)


class GenerationError(RuntimeError):
    """The model call failed or returned output we cannot use. Nothing is guessed."""


@dataclass(frozen=True)
class Answer:
    question: str  # the user's own message
    status: Status  # answered, not_covered (the Help Center does not cover it) or clarification (we ask the user)
    text: str
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...]
    rewrite: RewriteResult  # the query retrieval used and how it was made
    history: tuple[Message, ...]  # the history shown to the rewrite and the answer step
    retrieval: RetrievalResult
    docs: list[ContextDoc]
    draft: Optional[AnswerDraft]  # what the model returned before the checks; None if the model was not called or cut off
    model: str
    prompt_version: str
    usage: Optional[Usage]
    llm_ms: float
    llm_attempts: int  # 0 when no evidence was retrieved, 2 when the first reply was cut off

    @property
    def answerable(self) -> bool:
        return self.status == "answered"

    def to_dict(self) -> dict:
        return {
            "question": self.question, "status": self.status, "answerable": self.answerable, "answer": self.text,
            "citations": [{"url": c.url, "article_title": c.article_title, "sections": list(c.sections)} for c in self.citations],
            "warnings": list(self.warnings), "rewrite": self.rewrite.to_dict(),
            "history": [{"role": m.role, "content": m.content} for m in self.history],
            "model": self.model, "prompt_version": self.prompt_version, "llm_attempts": self.llm_attempts,
            "usage": None if self.usage is None else vars(self.usage), "llm_ms": self.llm_ms,
            "draft": None if self.draft is None else self.draft.model_dump(),
            "context_docs": [{"number": d.number, "chunk_ids": list(d.chunk_ids), "header": d.header} for d in self.docs],
            "retrieval": self.retrieval.to_dict(),
        }


def build_llm(model: Optional[str] = None, max_tokens: int = MAX_OUTPUT_TOKENS) -> Runnable:
    """The chat model with structured output: returns {"raw", "parsed", "parsing_error"} for an AnswerDraft."""
    chat = ChatOpenAI(model=model or config.chat_model(), temperature=0, api_key=config.openai_api_key(),
                      max_retries=config.LLM_MAX_RETRIES, timeout=config.LLM_TIMEOUT_SECONDS, max_tokens=max_tokens)
    return chat.with_structured_output(AnswerDraft, method="json_schema", strict=True, include_raw=True)


def _cut_off(output: dict) -> bool:
    return getattr(output.get("raw"), "response_metadata", {}).get("finish_reason") == "length"


def _parsed_draft(output: dict) -> AnswerDraft:
    draft, error = output.get("parsed"), output.get("parsing_error")
    if draft is not None and error is None:
        return draft
    refusal = getattr(output.get("raw"), "additional_kwargs", {}).get("refusal")
    reason = f"the model refused: {refusal}" if refusal else f"output did not match the expected format: {error}"
    raise GenerationError(f"The model returned no usable answer ({reason}).")


class AnswerChain:
    def __init__(self, retriever: Retriever, llm: Runnable, model: str, rewriter: Optional[QueryRewriter] = None,
                 retry_llm: Optional[Runnable] = None) -> None:
        self._retriever = retriever
        self._rewriter = rewriter
        self._model = model
        self._prompted_llm = build_prompt() | llm
        self._retry_llm = None if retry_llm is None else build_prompt() | retry_llm
        self.chain = (
            RunnablePassthrough.assign(rewrite=RunnableLambda(self._rewrite).with_config(run_name="rewrite"))
            | RunnablePassthrough.assign(retrieval=RunnableLambda(self._retrieve).with_config(run_name="retrieve"))
            | RunnablePassthrough.assign(docs=RunnableLambda(self._build_docs).with_config(run_name="build_context"))
            | RunnableLambda(self._generate).with_config(run_name="generate")
            | RunnableLambda(self._finish).with_config(run_name="check_output")
        )

    def answer(self, question: str, history: Sequence[Message] = ()) -> Answer:
        text = question.strip()
        if not text:
            raise ValueError("The question is empty.")
        return self.chain.invoke({"question": text, "history": tuple(trim_history(history))})

    def _rewrite(self, state: dict) -> RewriteResult:
        if self._rewriter is None:
            return RewriteResult(state["question"], state["question"], False, None, None, None, 0.0)
        return self._rewriter.rewrite(state["question"], state["history"])

    def _retrieve(self, state: dict) -> RetrievalResult:
        return self._retriever.retrieve(state["rewrite"].query)

    @staticmethod
    def _build_docs(state: dict) -> list[ContextDoc]:
        return build_context_docs(state["retrieval"].hits)

    def _attempt(self, prompted: Runnable, variables: dict) -> Optional[dict]:
        """The model's output, or None if the reply was cut off at the length limit."""
        try:
            output = prompted.invoke(variables)
        except LengthFinishReasonError:
            return None
        except OpenAIError as exc:
            raise GenerationError(f"The model request failed ({self._model}): {type(exc).__name__}: {exc}") from exc
        return None if _cut_off(output) else output

    def _generate(self, state: dict) -> dict:
        """Call the model, unless there is no evidence to give it; retry once if the reply was cut off."""
        if not state["docs"]:
            return {**state, "output": None, "truncated": False, "attempts": 0, "llm_ms": 0.0}
        variables = {"history_block": render_history_block(state["history"]), "context": format_context(state["docs"]),
                     "question": state["question"], "length_note": ""}
        started = time.perf_counter()
        output, attempts = self._attempt(self._prompted_llm, variables), 1
        if output is None and self._retry_llm is not None:
            output, attempts = self._attempt(self._retry_llm, {**variables, "length_note": CONCISE_NOTE}), 2
        elapsed = (time.perf_counter() - started) * MS_PER_SECOND
        return {**state, "output": output, "truncated": output is None, "attempts": attempts, "llm_ms": elapsed}

    def _resolve(self, state: dict) -> tuple[Optional[AnswerDraft], ResolvedAnswer]:
        if state["truncated"]:
            note = f"The reply was cut off at the length limit after {state['attempts']} attempt(s)."
            return None, ResolvedAnswer("clarification", TRUNCATED_MESSAGE, (), (note,))
        output = state["output"]
        draft = None if output is None else _parsed_draft(output)
        return draft, resolve_answer(draft or AnswerDraft(status="not_covered", answer="", sources=[]), state["docs"])

    def _finish(self, state: dict) -> Answer:
        draft, resolved = self._resolve(state)
        output, rewrite = state["output"], state["rewrite"]
        warnings = resolved.warnings + ((rewrite.fallback_reason,) if rewrite.fallback_reason else ())
        return Answer(
            question=state["question"], status=resolved.status, text=resolved.text, citations=resolved.citations,
            warnings=warnings, rewrite=rewrite, history=state["history"], retrieval=state["retrieval"], docs=state["docs"],
            draft=draft, model=self._model, prompt_version=PROMPT_VERSION,
            usage=None if output is None else usage_from_message(output.get("raw")), llm_ms=state["llm_ms"],
            llm_attempts=state["attempts"],
        )


def default_chain() -> AnswerChain:
    """The chain configured in the environment (OPENAI_API_KEY, CHAT_MODEL, REWRITE_MODEL, EMBEDDING_MODEL, RETRIEVAL_TOP_K)."""
    model = config.chat_model()
    return AnswerChain(default_retriever(), build_llm(model), model, default_rewriter(),
                       build_llm(model, RETRY_MAX_OUTPUT_TOKENS))
