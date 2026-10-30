"""Turn retrieved chunks into the numbered documents shown to the model (FR-5).

The numbers are what the model cites. URLs are deliberately not part of the text the model sees; the application adds
them from stored metadata after the answer, so the model cannot invent or distort one.
"""

from dataclasses import dataclass

from iqm_rag.retrieval.retriever import RetrievedChunk

PART_SEPARATOR = "\n\n"
SECTION_SEPARATOR = " › "


@dataclass(frozen=True)
class ContextDoc:
    number: int  # what the model cites, starting at 1
    article_title: str
    article_url: str
    section: str  # heading path inside the article
    header: str  # "Article title › heading path", as embedded
    text: str
    chunk_ids: tuple[str, ...]
    best_rank: int
    best_similarity: float


def _section_key(chunk: dict) -> str:
    """Chunk ID without the part suffix: parts of one split section share it."""
    return chunk["chunk_id"].rsplit(":p", 1)[0]


def _group_by_section(hits: list[RetrievedChunk]) -> list[list[RetrievedChunk]]:
    """Group hits by section, ordered by the best rank in each group, parts ordered within a group."""
    groups: dict[str, list[RetrievedChunk]] = {}
    for hit in hits:
        groups.setdefault(_section_key(hit.chunk), []).append(hit)
    ordered = sorted(groups.values(), key=lambda group: min(h.rank for h in group))
    return [sorted(group, key=lambda h: h.chunk["part"]) for group in ordered]


def build_context_docs(hits: list[RetrievedChunk]) -> list[ContextDoc]:
    docs = []
    for number, group in enumerate(_group_by_section(hits), start=1):
        first = group[0].chunk
        best = min(group, key=lambda h: h.rank)
        docs.append(ContextDoc(
            number=number, article_title=first["article_title"], article_url=first["article_url"],
            section=SECTION_SEPARATOR.join(first["section_path"]), header=first["context_header"],
            text=PART_SEPARATOR.join(h.chunk["text"] for h in group),
            chunk_ids=tuple(h.chunk["chunk_id"] for h in group), best_rank=best.rank, best_similarity=best.similarity,
        ))
    return docs


def format_context(docs: list[ContextDoc]) -> str:
    """XML-style document blocks, the layout OpenAI's guide reports working well for retrieved documents."""
    return "\n".join(f'<doc id="{doc.number}" title="{doc.header.replace(chr(34), chr(39))}">\n{doc.text}\n</doc>'
                     for doc in docs)
