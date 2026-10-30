"""The RAG chain (FR-5): retrieve, build context, prompt, model, check the output.

Built from LangChain runnables with named steps so tracing shows each one. Retrieval is separate from generation:
the chain only calls the retriever and reads its result. Chat history and the follow-up rewrite are added by the
conversation ticket; this chain answers one self-contained question.
"""

import time
from dataclasses import dataclass
from typing import Optional

from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from langchain_openai import ChatOpenAI
from openai import OpenAIError

from iqm_rag import config
from iqm_rag.generation.citations import Citation, ResolvedAnswer, resolve_answer
from iqm_rag.generation.context import ContextDoc, build_context_docs, format_context
from iqm_rag.generation.prompts import PROMPT_VERSION, AnswerDraft, build_prompt
from iqm_rag.retrieval.retriever import RetrievalResult, Retriever, default_retriever

MAX_OUTPUT_TOKENS = 700
MAX_RETRIES = 3  # the OpenAI client retries rate limits, timeouts and 5xx errors with backoff
REQUEST_TIMEOUT_SECONDS = 60.0
MS_PER_SECOND = 1000.0


class GenerationError(RuntimeError):
    """The model call failed or returned output we cannot use. Nothing is guessed."""


@dataclass(frozen=True)
class Usage:
    """Token counts as reported by the provider; None where it did not report them."""

    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]


@dataclass(frozen=True)
class Answer:
    question: str
    answerable: bool
    text: str
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...]
    retrieval: RetrievalResult
    docs: list[ContextDoc]
    draft: Optional[AnswerDraft]  # what the model returned before the checks; None if the model was not called
    model: str
    prompt_version: str
    usage: Optional[Usage]
    llm_ms: float

    def to_dict(self) -> dict:
        return {
            "question": self.question, "answerable": self.answerable, "answer": self.text,
            "citations": [{"url": c.url, "article_title": c.article_title, "sections": list(c.sections)} for c in self.citations],
            "warnings": list(self.warnings), "model": self.model, "prompt_version": self.prompt_version,
            "usage": None if self.usage is None else vars(self.usage), "llm_ms": self.llm_ms,
            "draft": None if self.draft is None else self.draft.model_dump(),
            "context_docs": [{"number": d.number, "chunk_ids": list(d.chunk_ids), "header": d.header} for d in self.docs],
            "retrieval": self.retrieval.to_dict(),
        }


def build_llm(model: Optional[str] = None) -> Runnable:
    """The chat model with structured output: returns {"raw", "parsed", "parsing_error"} for an AnswerDraft."""
    chat = ChatOpenAI(model=model or config.chat_model(), temperature=0, api_key=config.openai_api_key(),
                      max_retries=MAX_RETRIES, timeout=REQUEST_TIMEOUT_SECONDS, max_tokens=MAX_OUTPUT_TOKENS)
    return chat.with_structured_output(AnswerDraft, method="json_schema", strict=True, include_raw=True)


def _usage(raw) -> Optional[Usage]:
    meta = getattr(raw, "usage_metadata", None)
    if not meta:
        return None
    return Usage(meta.get("input_tokens"), meta.get("output_tokens"), meta.get("total_tokens"))


def _parsed_draft(output: dict) -> AnswerDraft:
    draft, error = output.get("parsed"), output.get("parsing_error")
    if draft is not None and error is None:
        return draft
    refusal = getattr(output.get("raw"), "additional_kwargs", {}).get("refusal")
    reason = f"the model refused: {refusal}" if refusal else f"output did not match the expected format: {error}"
    raise GenerationError(f"The model returned no usable answer ({reason}).")


class AnswerChain:
    def __init__(self, retriever: Retriever, llm: Runnable, model: str) -> None:
        self._retriever = retriever
        self._model = model
        self._prompted_llm = build_prompt() | llm
        self.chain = (
            RunnablePassthrough.assign(retrieval=RunnableLambda(self._retrieve).with_config(run_name="retrieve"))
            | RunnablePassthrough.assign(docs=RunnableLambda(self._build_docs).with_config(run_name="build_context"))
            | RunnableLambda(self._generate).with_config(run_name="generate")
            | RunnableLambda(self._finish).with_config(run_name="check_output")
        )

    def answer(self, question: str) -> Answer:
        text = question.strip()
        if not text:
            raise ValueError("The question is empty.")
        return self.chain.invoke({"question": text})

    def _retrieve(self, state: dict) -> RetrievalResult:
        return self._retriever.retrieve(state["question"])

    @staticmethod
    def _build_docs(state: dict) -> list[ContextDoc]:
        return build_context_docs(state["retrieval"].hits)

    def _generate(self, state: dict) -> dict:
        """Call the model, unless there is no evidence to give it."""
        if not state["docs"]:
            return {**state, "output": None, "llm_ms": 0.0}
        started = time.perf_counter()
        try:
            output = self._prompted_llm.invoke({"context": format_context(state["docs"]), "question": state["question"]})
        except OpenAIError as exc:
            raise GenerationError(f"The model request failed ({self._model}): {type(exc).__name__}: {exc}") from exc
        return {**state, "output": output, "llm_ms": (time.perf_counter() - started) * MS_PER_SECOND}

    def _finish(self, state: dict) -> Answer:
        output = state["output"]
        draft = None if output is None else _parsed_draft(output)
        resolved: ResolvedAnswer = resolve_answer(draft or AnswerDraft(answerable=False, answer="", sources=[]), state["docs"])
        return Answer(
            question=state["question"], answerable=resolved.answerable, text=resolved.text, citations=resolved.citations,
            warnings=resolved.warnings, retrieval=state["retrieval"], docs=state["docs"], draft=draft, model=self._model,
            prompt_version=PROMPT_VERSION, usage=None if output is None else _usage(output.get("raw")), llm_ms=state["llm_ms"],
        )


def default_chain() -> AnswerChain:
    """The chain configured in the environment (OPENAI_API_KEY, CHAT_MODEL, EMBEDDING_MODEL, RETRIEVAL_TOP_K)."""
    model = config.chat_model()
    return AnswerChain(default_retriever(), build_llm(model), model)
