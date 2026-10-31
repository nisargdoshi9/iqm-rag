"""Per-request tracing with LangSmith (FR-8): retrieved chunks, prompt, response, latency and token usage.

Tracing is off unless a LangSmith key is configured, so local development and the tests never touch the network. The
chain's LangChain steps are traced automatically; this module configures it, builds the tags and metadata we add, and
formats retrieved chunks the way LangSmith displays retriever results. No secret and no question text goes into metadata.
"""

import os
from typing import Optional, Sequence

from iqm_rag import config

BASE_TAG = "rag"


class Held:
    """Carries a value from one chain step to the next without LangChain writing all of it into every step's trace.

    LangChain logs a step's whole output; for our dataclasses that would copy every chunk's text into several steps. A
    held value is logged as its short label instead (the `vector_search` step holds the chunks, the prompt holds the text).
    """

    __slots__ = ("value", "label")

    def __init__(self, value, label: str) -> None:
        self.value = value
        self.label = label

    def __repr__(self) -> str:
        return self.label


def configure_tracing() -> bool:
    """Set the variables the LangSmith SDK reads, if tracing is enabled. Values that are already set are kept."""
    if not config.tracing_enabled():
        return False
    if not os.environ.get("LANGSMITH_TRACING", "").strip():
        os.environ["LANGSMITH_TRACING"] = "true"
    if not os.environ.get("LANGSMITH_PROJECT", "").strip():
        os.environ["LANGSMITH_PROJECT"] = config.langsmith_project()
    return True


def flush_traces() -> None:
    """Send any traces still queued. Short-lived scripts call this before they exit; failures are not fatal."""
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers
        from langsmith.run_trees import get_cached_client

        wait_for_all_tracers()
        get_cached_client().flush()
    except Exception:  # tracing must never break the application
        pass


def build_tags(prompt_version: str, chat_model: str, extra: Sequence[str] = ()) -> list[str]:
    tags = [BASE_TAG, f"prompt:{prompt_version}", f"model:{chat_model}"]
    tags += [tag for tag in extra if tag not in tags]
    return list(dict.fromkeys(tags))


def build_run_metadata(prompt_version: str, chat_model: str, rewrite_model: Optional[str], embedding_model: Optional[str],
                       top_k: Optional[int], history_messages: int, question_chars: int, session_id: Optional[str] = None,
                       extra: Optional[dict] = None) -> dict:
    """What describes the setup of one request. It holds no secrets and not the question text (the run's input has that)."""
    metadata = {"prompt_version": prompt_version, "chat_model": chat_model, "rewrite_model": rewrite_model,
                "embedding_model": embedding_model, "top_k": top_k, "history_messages": history_messages,
                "question_chars": question_chars}
    if session_id:
        metadata["session_id"] = session_id  # LangSmith groups runs with the same session_id into one thread
    metadata.update(extra or {})
    return metadata


def retrieval_documents(result) -> dict:
    """A retrieval result as LangSmith shows retriever output: documents with a score and the source, plus timings."""
    if result is None:  # the search failed, so the run has no result to show
        return {}
    documents = [
        {"page_content": hit.chunk["text"], "type": "Document",
         "metadata": {"rank": hit.rank, "similarity": round(hit.similarity, 4), "distance": round(hit.distance, 4),
                      "chunk_id": hit.chunk["chunk_id"], "header": hit.chunk["context_header"], "url": hit.chunk["article_url"]}}
        for hit in result.hits
    ]
    output = {"documents": documents, "embedding_model": result.embedding_model, "embedding_tokens": result.embedding_tokens,
              "embed_ms": round(result.embed_ms, 1), "search_ms": round(result.search_ms, 1)}
    if getattr(result, "steps", None):  # the pipeline's settings and what each stage did
        output["steps"] = result.steps
    return output
