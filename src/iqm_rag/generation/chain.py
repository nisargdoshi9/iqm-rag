"""The RAG chain (FR-5, FR-6): rewrite, retrieve, build context, prompt, model, check the output.

Built from LangChain runnables with named steps so tracing shows each one. Retrieval is separate from generation:
the chain only calls the retriever and reads its result. The chain is stateless; the caller passes the history, and
`Conversation` keeps it per session. A reply cut off at the length limit is retried once with a higher limit and a
request to be concise; if that also fails the user gets a plain message, never an error caused by our own cap.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence

from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from langchain_openai import ChatOpenAI
from langsmith import traceable, tracing_context
from langsmith.run_helpers import get_current_run_tree
from openai import LengthFinishReasonError, OpenAIError

from iqm_rag import config
from iqm_rag.generation.citations import Citation, ResolvedAnswer, resolve_answer
from iqm_rag.generation.context import ContextDoc, build_context_docs, format_context
from iqm_rag.generation.prompts import CONCISE_NOTE, PROMPT_VERSION, AnswerDraft, Status, build_prompt, render_history_block
from iqm_rag.history import Message, trim_history
from iqm_rag.observability.tracing import Held, build_run_metadata, build_tags, configure_tracing
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
    trace_id: str  # our id for this request; it is the LangSmith run id when tracing is on
    traced: bool  # the request was sent to LangSmith

    @property
    def answerable(self) -> bool:
        return self.status == "answered"

    def dict(self) -> dict:
        """The hook LangSmith uses (pydantic-v1 style) to log this object: the compact summary, not every chunk's text."""
        return self.trace_summary()

    def trace_summary(self) -> dict:
        """What is logged as the output of the whole request: compact, with no chunk text (the child steps hold that)."""
        return {
            "status": self.status, "answer": self.text, "citations": [c.url for c in self.citations],
            "search_query": self.rewrite.query, "rewritten": self.rewrite.rewritten,
            "retrieved_chunk_ids": [hit.chunk["chunk_id"] for hit in self.retrieval.hits],
            "usage": None if self.usage is None else vars(self.usage), "llm_ms": round(self.llm_ms, 1),
            "llm_attempts": self.llm_attempts, "warnings": list(self.warnings), "trace_id": self.trace_id,
        }

    def trace_metadata(self) -> dict:
        """What is added to the request's run once it has finished, so runs can be filtered by outcome."""
        return {"status": self.status, "abstained": self.status == "not_covered", "rewritten": self.rewrite.rewritten,
                "citation_count": len(self.citations), "llm_attempts": self.llm_attempts, "warning_count": len(self.warnings)}

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id, "traced": self.traced,
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


def _trace_inputs(inputs: dict) -> dict:
    state = inputs["state"]
    return {"question": state["question"], "history": [{"role": m.role, "content": m.content} for m in state["history"]]}


def _trace_outputs(answer: Optional["Answer"]) -> dict:
    return {} if answer is None else answer.trace_summary()  # on an error the run has no answer to summarise


@traceable(name="rag_answer", run_type="chain", process_inputs=_trace_inputs, process_outputs=_trace_outputs)
def _run_chain(chain: Runnable, state: dict) -> "Answer":
    """One request, as a single traced run. The chain's steps nest under it as child runs."""
    answer = chain.invoke(state).value
    run = get_current_run_tree()
    if run is not None:
        run.add_metadata(answer.trace_metadata())
    return answer


class AnswerChain:
    def __init__(self, retriever: Retriever, llm: Runnable, model: str, rewriter: Optional[QueryRewriter] = None,
                 retry_llm: Optional[Runnable] = None, tracing: bool = False) -> None:
        self.tracing_enabled = tracing  # off by default, so tests and scripts never reach the network
        self._retriever = retriever
        self._rewriter = rewriter
        self._model = model
        self._prompted_llm = build_prompt() | llm
        self._retry_llm = None if retry_llm is None else build_prompt() | retry_llm
        # one visible step per stage (no assign/parallel wrappers), so a trace reads: rewrite, retrieve, build_context, generate, check_output
        self.chain = (
            RunnableLambda(self._rewrite_step).with_config(run_name="rewrite")
            | RunnableLambda(self._retrieve_step).with_config(run_name="retrieve")
            | RunnableLambda(self._context_step).with_config(run_name="build_context")
            | RunnableLambda(self._generate).with_config(run_name="generate")
            | RunnableLambda(self._finish).with_config(run_name="check_output")
        )

    def describe(self) -> dict:
        """The setup of this chain, recorded with evaluation results so a run can be reproduced."""
        return {"chat_model": self._model, "rewrite_model": getattr(self._rewriter, "model", None),
                "embedding_model": getattr(self._retriever, "embedding_model", None), "top_k": getattr(self._retriever, "top_k", None),
                "index_chunks": getattr(self._retriever, "chunk_count", None), "prompt_version": PROMPT_VERSION, "tracing": self.tracing_enabled}

    def answer(self, question: str, history: Sequence[Message] = (), session_id: Optional[str] = None,
               tags: Sequence[str] = (), metadata: Optional[dict] = None) -> Answer:
        """Answer one question. `session_id`, `tags` and `metadata` only describe the request in the trace."""
        text = question.strip()
        if not text:
            raise ValueError("The question is empty.")
        trimmed = tuple(trim_history(history))
        run_id = uuid.uuid4()
        state = {"question": text, "history": trimmed, "trace_id": str(run_id)}
        extra = {"run_id": run_id, "tags": build_tags(PROMPT_VERSION, self._model, tags),
                 "metadata": build_run_metadata(PROMPT_VERSION, self._model, getattr(self._rewriter, "model", None),
                                                getattr(self._retriever, "embedding_model", None), getattr(self._retriever, "top_k", None),
                                                len(trimmed), len(text), session_id, metadata)}
        with tracing_context(enabled=self.tracing_enabled, **({"project_name": config.langsmith_project()} if self.tracing_enabled else {})):
            return _run_chain(self.chain, state, langsmith_extra=extra)

    def _rewrite_step(self, state: dict) -> dict:
        if self._rewriter is None:
            return {**state, "rewrite": RewriteResult(state["question"], state["question"], False, None, None, None, 0.0)}
        return {**state, "rewrite": self._rewriter.rewrite(state["question"], state["history"])}

    def _retrieve_step(self, state: dict) -> dict:
        result = self._retriever.retrieve(state["rewrite"].query)
        return {**state, "retrieval": Held(result, f"{len(result.hits)} chunks retrieved (see vector_search)")}

    @staticmethod
    def _context_step(state: dict) -> dict:
        docs = build_context_docs(state["retrieval"].value.hits)
        return {**state, "docs": Held(docs, f"{len(docs)} numbered documents (the prompt holds their text)")}

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
        docs = state["docs"].value
        if not docs:
            return {**state, "output": None, "truncated": False, "attempts": 0, "llm_ms": 0.0}
        variables = {"history_block": render_history_block(state["history"]), "context": format_context(docs),
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
        return draft, resolve_answer(draft or AnswerDraft(status="not_covered", answer="", sources=[]), state["docs"].value)

    def _finish(self, state: dict) -> Held:
        """The checked answer, held so this step's trace shows a one-line summary (the whole request's summary is on the root run)."""
        draft, resolved = self._resolve(state)
        output, rewrite = state["output"], state["rewrite"]
        warnings = resolved.warnings + ((rewrite.fallback_reason,) if rewrite.fallback_reason else ())
        answer = Answer(
            question=state["question"], status=resolved.status, text=resolved.text, citations=resolved.citations,
            warnings=warnings, rewrite=rewrite, history=state["history"], retrieval=state["retrieval"].value, docs=state["docs"].value,
            draft=draft, model=self._model, prompt_version=PROMPT_VERSION,
            usage=None if output is None else usage_from_message(output.get("raw")), llm_ms=state["llm_ms"],
            llm_attempts=state["attempts"], trace_id=state["trace_id"], traced=self.tracing_enabled,
        )
        return Held(answer, f"{answer.status}; {len(answer.citations)} source(s); {len(answer.warnings)} warning(s)")


def default_chain() -> AnswerChain:
    """The chain configured in the environment (OPENAI_API_KEY, CHAT_MODEL, REWRITE_MODEL, EMBEDDING_MODEL, RETRIEVAL_TOP_K)."""
    model = config.chat_model()
    return AnswerChain(default_retriever(), build_llm(model), model, default_rewriter(),
                       build_llm(model, RETRY_MAX_OUTPUT_TOKENS), tracing=configure_tracing())
