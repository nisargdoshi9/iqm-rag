"""What the interface shows for an answer, kept free of Streamlit so it can be unit-tested (FR-7).

`build_answer_view` turns an `Answer` into plain data: the status label, the text, de-duplicated source links, the
retrieved evidence and a list of developer details. Nothing here calls a model or the network.
"""

import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from iqm_rag.generation.chain import Answer, GenerationError
from iqm_rag.ingestion.embeddings import EmbeddingError
from iqm_rag.retrieval.retriever import RetrievalError

STATUS_LABELS = {
    "answered": "From the Help Center",
    "not_covered": "Not in the Help Center",
    "clarification": "A quick question",
    "error": "Something went wrong",
}
SNIPPET_CHARS = 240
PREVIEW_CHARS = 130
LOADING_INTERVAL_SECONDS = 1.8
LOADING_MESSAGES = (
    "Reading your question…",
    "Flipping through the Help Center…",
    "Finding the right article…",
    "Looking up the relevant sections…",
    "Matching your words to the docs…",
    "Comparing similar sections…",
    "Picking out the most relevant steps…",
    "Checking the details…",
    "Double-checking the sources…",
    "Making sure nothing is made up…",
    "Putting the answer together…",
    "Tidying up the answer…",
)
EXAMPLE_QUESTIONS = (
    "How do I schedule a report to be emailed every week?",
    "How do I upload an image creative?",
    "What are the campaign Optimization & Delivery settings?",
    "How do I manage creatives in bulk?",
    "How do I create or manage a Political Planner plan?",
)
EXAMPLES_SHOWN = 3
SERVICE_ERRORS = (EmbeddingError, RetrievalError, GenerationError)


@dataclass(frozen=True)
class SourceLink:
    title: str
    sections: tuple[str, ...]
    url: str
    previews: tuple[str, ...] = ()  # a short extract of each cited section, in the same order as `sections`


@dataclass(frozen=True)
class EvidenceItem:
    rank: int
    similarity: float
    header: str
    snippet: str
    url: str
    cited: bool  # the answer used this passage


@dataclass(frozen=True)
class AnswerView:
    status: str  # a key of STATUS_LABELS
    text: str
    sources: tuple[SourceLink, ...]
    evidence: tuple[EvidenceItem, ...]
    details: tuple[tuple[str, str], ...]  # label and value pairs for the developer panel
    warnings: tuple[str, ...]

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """A short plain-text preview: the leading heading line is dropped because the header already names the section."""
    body = re.sub(r"\A(?:\s*#+[^\n]*\n)+", "", text)
    flat = re.sub(r"\s+", " ", re.sub(r"[#*`>]", "", body)).strip()
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"


def _previews(answer: Answer, citation) -> tuple[str, ...]:
    """An extract of the text each cited section contributed, so a source can show what it was used for."""
    by_section = {doc.section: doc.text for doc in answer.docs if doc.article_url == citation.url}
    return tuple(_snippet(by_section.get(section, ""), PREVIEW_CHARS) for section in citation.sections)


def _cited_chunk_ids(answer: Answer) -> set[str]:
    cited: dict[str, set[str]] = {}
    for citation in answer.citations:
        cited.setdefault(citation.url, set()).update(citation.sections)
    return {chunk_id for doc in answer.docs if doc.section in cited.get(doc.article_url, ()) for chunk_id in doc.chunk_ids}


def _evidence(answer: Answer) -> tuple[EvidenceItem, ...]:
    cited = _cited_chunk_ids(answer)
    return tuple(EvidenceItem(hit.rank, hit.similarity, hit.chunk["context_header"], _snippet(hit.chunk["text"]),
                              hit.chunk["article_url"], hit.chunk["chunk_id"] in cited) for hit in answer.retrieval.hits)


def _seconds(milliseconds: float) -> str:
    return f"{milliseconds / 1000:.1f} s"


def _rewrite_detail(answer: Answer) -> str:
    rewrite = answer.rewrite
    if rewrite.fallback_reason:
        return rewrite.fallback_reason
    return f"rewritten to: {rewrite.query}" if rewrite.rewritten else "not rewritten"


def _developer_details(answer: Answer) -> tuple[tuple[str, str], ...]:
    usage = answer.usage
    tokens = "not reported" if usage is None else f"in {usage.input_tokens} · out {usage.output_tokens}"
    retrieval = answer.retrieval
    pairs = [
        ("Question as typed", answer.question),
        ("Search query", answer.rewrite.query),
        ("Rewrite", _rewrite_detail(answer)),
        ("Status", answer.status),
        ("Answer model", f"{answer.model} · prompt {answer.prompt_version} · {answer.llm_attempts} attempt(s)"),
        ("Embedding model", f"{retrieval.embedding_model} · top_k {retrieval.top_k} · {retrieval.embedding_tokens} query tokens"),
        ("Tokens", tokens),
        ("Time", f"embed {_seconds(retrieval.embed_ms)} · search {_seconds(retrieval.search_ms)} · model {_seconds(answer.llm_ms)}"),
    ]
    pairs += [("Warning", warning) for warning in answer.warnings]
    return tuple(pairs)


def build_answer_view(answer: Answer) -> AnswerView:
    sources = tuple(SourceLink(c.article_title, c.sections, c.url, _previews(answer, c)) for c in answer.citations)
    return AnswerView(answer.status, answer.text, sources, _evidence(answer), _developer_details(answer), answer.warnings)


def build_error_view(exc: Exception) -> AnswerView:
    """A friendly message for the user; the technical detail only appears in developer mode."""
    if isinstance(exc, ValueError):
        text = f"I couldn't use that question. {exc}"
    elif isinstance(exc, SERVICE_ERRORS):
        text = "I'm having trouble reaching the search or language service right now. Please try again in a moment."
    else:
        text = "Something unexpected went wrong on my side. Please try again."
    return AnswerView("error", text, (), (), (("Error", f"{type(exc).__name__}: {exc}"),), ())


def loading_message(start: int, tick: int) -> str:
    """The message to show on a given tick: round robin from a random starting point."""
    return LOADING_MESSAGES[(start + tick) % len(LOADING_MESSAGES)]


def pick_examples(rng: Optional[random.Random] = None, count: int = EXAMPLES_SHOWN) -> list[str]:
    return (rng or random).sample(EXAMPLE_QUESTIONS, min(count, len(EXAMPLE_QUESTIONS)))


def source_label(link: SourceLink) -> str:
    return f"{link.title}: {'; '.join(link.sections)}"


def evidence_counts(items: Sequence[EvidenceItem]) -> tuple[int, int]:
    """(retrieved, used in the answer)."""
    return len(items), sum(item.cited for item in items)


def format_clock(moment: datetime) -> str:
    """A 12-hour clock without a leading zero, such as "9:05 AM". The page script re-formats it in the reader's time zone."""
    return moment.astimezone().strftime("%I:%M %p").lstrip("0")
