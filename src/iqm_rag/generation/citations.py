"""Check the model's draft and turn it into a safe answer with citations built from stored metadata (FR-5).

The model only returns context numbers. A number it was never given is dropped, an answer with no valid source is
shown as an abstention, and an abstention never carries links. A valid number that does not really support the claim
cannot be detected here; the evaluation measures that.
"""

from dataclasses import dataclass

from iqm_rag.generation.context import ContextDoc
from iqm_rag.generation.prompts import AnswerDraft

ABSTENTION_MESSAGE = (
    "I couldn't find this in the IQM Help Center, so I can't answer it reliably. "
    "Try rephrasing the question or contact IQM support."
)


@dataclass(frozen=True)
class Citation:
    url: str
    article_title: str
    sections: tuple[str, ...]  # the sections of this article that were cited, in the order first cited


@dataclass(frozen=True)
class ResolvedAnswer:
    answerable: bool
    text: str
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...]


def _abstain(text: str, warnings: list[str]) -> ResolvedAnswer:
    return ResolvedAnswer(answerable=False, text=text or ABSTENTION_MESSAGE, citations=(), warnings=tuple(warnings))


def _valid_numbers(sources: list[int], docs: list[ContextDoc], warnings: list[str]) -> list[int]:
    supplied = {doc.number for doc in docs}
    valid = list(dict.fromkeys(number for number in sources if number in supplied))
    unknown = sorted({number for number in sources if number not in supplied})
    if unknown:
        warnings.append(f"Dropped source numbers that were not supplied: {unknown}.")
    return valid


def _citations(numbers: list[int], docs: list[ContextDoc]) -> tuple[Citation, ...]:
    by_number = {doc.number: doc for doc in docs}
    grouped: dict[str, tuple[str, list[str]]] = {}
    for number in numbers:
        doc = by_number[number]
        _, sections = grouped.setdefault(doc.article_url, (doc.article_title, []))
        if doc.section not in sections:
            sections.append(doc.section)
    return tuple(Citation(url, title, tuple(sections)) for url, (title, sections) in grouped.items())


def resolve_answer(draft: AnswerDraft, docs: list[ContextDoc]) -> ResolvedAnswer:
    warnings: list[str] = []
    text = draft.answer.strip()
    if not draft.answerable:
        if draft.sources:
            warnings.append("The model listed sources on an abstention; they were ignored.")
        return _abstain(text, warnings)
    numbers = _valid_numbers(draft.sources, docs, warnings)
    if not text or not numbers:
        warnings.append("The model gave an answer without a usable answer text or valid source; shown as an abstention.")
        return _abstain("", warnings)
    return ResolvedAnswer(answerable=True, text=text, citations=_citations(numbers, docs), warnings=tuple(warnings))
