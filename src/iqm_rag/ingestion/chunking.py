"""Split cleaned articles into chunks (FR-3). Decisions and reasoning: docs/decisions/FR-03-chunking.md.

A chunk is a leaf section. Short sibling sections (same parent) are merged up to a minimum size, and an oversized
section is split at unit boundaries (list item, table row, Q/A pair, paragraph) into even pieces. The context header
"Title > heading path" is stored on the chunk and prepended only when the text is embedded.
"""

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

from iqm_rag import config
from iqm_rag.scraping.blocks import Block
from iqm_rag.scraping.markdown import list_item_markdown, render_block, row_markdown, table_header_lines
from iqm_rag.scraping.normalization import MEDIA_TYPES, read_jsonl, sha256_text
from iqm_rag.scraping.scraper import write_atomic
from iqm_rag.scraping.tables import DATA

CHUNKS_JSONL = config.CHUNKS_DIR / "chunks.jsonl"
CHUNK_REPORT_PATH = config.CHUNKS_DIR / "chunking_report.json"
HEADER_SEPARATOR = " › "
UNIT_SEPARATOR = "\n\n"
GROUP_SEPARATOR = "\n"  # between items of one list, or rows of one table
QUESTION_PREFIX = "**Q"  # FAQ questions are bold paragraphs starting "**Q:"
LEAD_IN_MAX_CHARS = 400  # a paragraph right before a list or table is repeated as its intro when it is this short
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
SMALL_CHUNK_TOKENS = 60  # reporting threshold only

KIND_BLOCK, KIND_ITEM, KIND_ROW, KIND_FAQ = "block", "item", "row", "faq"
OVERLAP_KINDS = (KIND_BLOCK, KIND_ITEM)  # never repeat table rows or FAQ pairs


@dataclass(frozen=True)
class ChunkingConfig:
    """Sizes are estimated tokens (characters / chars_per_token). Starting points, to be tuned by evaluation."""

    merge_min_tokens: int = 150
    max_tokens: int = 700
    overlap_max_tokens: int = 50
    chars_per_token: int = 4


@dataclass
class Unit:
    """The smallest piece a section is split into. Splits happen between units, never inside one."""

    text: str
    kind: str
    group: str = ""  # ID of the list or table the unit belongs to
    group_lead: str = ""  # text put before the unit when a piece starts in the middle of its group
    first_in_group: bool = True


@dataclass
class Draft:
    section_ids: list[str]
    full_path: list[str]
    parent: list[str]
    text: str
    tokens: int
    part: int = 1
    parts: int = 1
    carried: list[str] = field(default_factory=list)  # media-only sections attached to this chunk


def estimate_tokens(text: str, cfg: ChunkingConfig) -> int:
    return math.ceil(len(text) / cfg.chars_per_token) if text else 0


def embedding_text(chunk: dict) -> str:
    """The text that is embedded: the context header followed by the chunk text."""
    return chunk["context_header"] + UNIT_SEPARATOR + chunk["text"]


# --- Units -------------------------------------------------------------------------------------------


def _group_id(block: Block) -> str:
    return str(block.get("id") or id(block))


def _single_unit(block: Block) -> list[Unit]:
    text = "\n".join(render_block(block))
    return [Unit(text, KIND_BLOCK)] if text.strip() else []


def _list_units(block: Block, lead: str) -> list[Unit]:
    group, units = _group_id(block), []
    prefix = lead + UNIT_SEPARATOR if lead else ""
    for number, item in enumerate(block["items"], start=1):
        text = list_item_markdown(item, number, block["ordered"])
        if text:
            units.append(Unit(text, KIND_ITEM, group, prefix, first_in_group=not units))
    return units


def _table_units(block: Block, lead: str) -> list[Unit]:
    rows = block["rows"]
    if block.get("table_class") != DATA or len(rows) < 2:
        return _single_unit(block)
    header = "\n".join(table_header_lines(rows))
    prefix = (lead + UNIT_SEPARATOR if lead else "") + header + GROUP_SEPARATOR
    group = _group_id(block)
    units = [Unit(header + GROUP_SEPARATOR + row_markdown(rows[1]), KIND_ROW, group, prefix)]
    return units + [Unit(row_markdown(row), KIND_ROW, group, prefix, first_in_group=False) for row in rows[2:]]


def _append_block(units: list[Unit], block: Block, lead: str) -> str:
    """Add one block's units and return the intro text for the next block."""
    kind = block["type"]
    if kind in MEDIA_TYPES:
        return lead
    if kind == "paragraph" and block["text"].startswith(QUESTION_PREFIX):
        units.append(Unit(block["text"], KIND_FAQ))
        return ""
    if units and units[-1].kind == KIND_FAQ:  # the answer stays with its question
        text = "\n".join(render_block(block))
        units[-1].text += UNIT_SEPARATOR + text if text.strip() else ""
        return ""
    if kind == "list":
        units.extend(_list_units(block, lead))
    elif kind == "table":
        units.extend(_table_units(block, lead))
    else:
        units.extend(_single_unit(block))
    is_short_paragraph = kind == "paragraph" and len(block["text"]) <= LEAD_IN_MAX_CHARS
    return block["text"] if is_short_paragraph else ""


def section_units(section: dict) -> list[Unit]:
    units: list[Unit] = []
    lead = ""
    for block in section["blocks"]:
        lead = _append_block(units, block, lead)
    return units


def _sentences(text: str, limit_chars: int) -> list[str]:
    pieces: list[str] = []
    for sentence in SENTENCE_BREAK.split(text):
        pieces.extend(sentence[start:start + limit_chars] for start in range(0, len(sentence), limit_chars))
    return [piece for piece in pieces if piece]


def split_oversized(unit: Unit, limit_tokens: int, cfg: ChunkingConfig) -> list[Unit]:
    """Last resort for a single unit larger than the limit: cut at sentence boundaries."""
    limit_chars = limit_tokens * cfg.chars_per_token
    if len(unit.text) <= limit_chars:
        return [unit]
    texts, current = [], ""
    for sentence in _sentences(unit.text, limit_chars):
        if current and len(current) + 1 + len(sentence) > limit_chars:
            texts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    return [Unit(text, KIND_BLOCK) for text in texts + [current]]


# --- Pieces ------------------------------------------------------------------------------------------


def render_units(units: list[Unit]) -> str:
    parts: list[str] = []
    previous_group = ""
    for unit in units:
        text = unit.text
        if unit.group and unit.group != previous_group and not unit.first_in_group:
            text = unit.group_lead + text  # a piece that starts mid-list or mid-table repeats the intro or header
        joiner = "" if not parts else (GROUP_SEPARATOR if unit.group and unit.group == previous_group else UNIT_SEPARATOR)
        parts.append(joiner + text)
        previous_group = unit.group
    return "".join(parts)


def _heading_line(section: dict) -> str:
    if section["heading"] is None:
        return ""
    return render_block({"type": "heading", "level": section["level"], "text": section["heading"]})[0]


def _piece_text(section: dict, units: list[Unit]) -> str:
    heading = _heading_line(section)
    body = render_units(units)
    return heading + UNIT_SEPARATOR + body if heading else body


def _pack(units: list[Unit], pieces_wanted: int, budget: int, cfg: ChunkingConfig) -> list[list[Unit]]:
    """Fill pieces toward an even share of what remains (never above the budget), so no tiny leftover piece appears."""
    remaining = sum(estimate_tokens(unit.text, cfg) for unit in units)
    pieces: list[list[Unit]] = []
    current: list[Unit] = []
    size, left = 0, pieces_wanted
    for unit in units:
        tokens = estimate_tokens(unit.text, cfg)
        limit = min(budget, math.ceil(remaining / left)) if left > 1 else budget
        if current and size + tokens > limit:
            pieces.append(current)
            remaining, current, size = remaining - size, [], 0
            left = max(1, left - 1)
        current.append(unit)
        size += tokens
    return pieces + [current] if current else pieces


def _add_overlap(pieces: list[list[Unit]], cfg: ChunkingConfig) -> list[list[Unit]]:
    result = [pieces[0]]
    for previous, piece in zip(pieces, pieces[1:]):
        last = previous[-1]
        small = estimate_tokens(last.text, cfg) <= cfg.overlap_max_tokens
        result.append(([last] if last.kind in OVERLAP_KINDS and small else []) + piece)
    return result


def section_pieces(section: dict, units: list[Unit], cfg: ChunkingConfig) -> list[str]:
    """The section's text, whole if it fits the maximum, otherwise split into even pieces.

    The maximum limits the final chunk text, so the budget for the units of one piece leaves room for what every piece
    repeats: the heading, the list intro or table header, and one overlap unit.
    """
    heading = _heading_line(section)
    total = sum(estimate_tokens(unit.text, cfg) for unit in units) + estimate_tokens(heading, cfg)
    if total <= cfg.max_tokens:
        return [_piece_text(section, units)]
    leads = max((estimate_tokens(unit.group_lead, cfg) for unit in units), default=0)
    overhead = estimate_tokens(heading, cfg) + leads + cfg.overlap_max_tokens
    budget = max(cfg.max_tokens // 2, cfg.max_tokens - overhead)
    units = [part for unit in units for part in split_oversized(unit, budget, cfg)]
    wanted = math.ceil(sum(estimate_tokens(unit.text, cfg) for unit in units) / budget)
    pieces = _add_overlap(_pack(units, wanted, budget, cfg), cfg)
    return [_piece_text(section, piece) for piece in pieces]


# --- Drafts: merging and carrying media-only sections --------------------------------------------------


def _has_media(section: dict) -> bool:
    return any(block["type"] in MEDIA_TYPES for block in section["blocks"])


class _Drafter:
    def __init__(self, cfg: ChunkingConfig) -> None:
        self.cfg = cfg
        self.drafts: list[Draft] = []
        self.pending: Optional[Draft] = None
        self.carry: list[str] = []

    def add_section(self, section: dict) -> None:
        units = section_units(section)
        if not units:
            if _has_media(section):
                self.carry.append(section["section_id"])
            return
        pieces = section_pieces(section, units, self.cfg)
        if len(pieces) == 1:
            self._add_whole(section, pieces[0])
        else:
            self._flush()
            self._add_split(section, pieces)

    def _add_whole(self, section: dict, text: str) -> None:
        tokens = estimate_tokens(text, self.cfg)
        parent = section["heading_path"][:-1]
        pending = self.pending
        if pending and not (pending.parent == parent and pending.tokens + tokens <= self.cfg.max_tokens):
            self._flush()
            pending = None
        if pending:
            pending.section_ids.append(section["section_id"])
            pending.text += UNIT_SEPARATOR + text
            pending.tokens = estimate_tokens(pending.text, self.cfg)
        else:
            pending = self.pending = Draft([section["section_id"]], section["heading_path"], parent, text, tokens)
        pending.carried, self.carry = pending.carried + self.carry, []
        if pending.tokens >= self.cfg.merge_min_tokens:
            self._flush()

    def _add_split(self, section: dict, pieces: list[str]) -> None:
        for number, text in enumerate(pieces, start=1):
            draft = Draft([section["section_id"]], section["heading_path"], section["heading_path"][:-1], text,
                          estimate_tokens(text, self.cfg), number, len(pieces))
            if number == 1:
                draft.carried, self.carry = self.carry, []
            self.drafts.append(draft)

    def _flush(self) -> None:
        if self.pending:
            self.drafts.append(self.pending)
            self.pending = None

    def finish(self) -> list[Draft]:
        self._flush()
        if self.carry and self.drafts:
            self.drafts[-1].carried += self.carry
        return self.drafts


# --- Chunks ------------------------------------------------------------------------------------------


def _ordinal(section_id: str) -> int:
    return int(section_id.rsplit(":s", 1)[1])


def _finalize(article: dict, draft: Draft, index: int) -> dict:
    path = draft.full_path if len(draft.section_ids) == 1 else draft.parent
    chunk = {
        "chunk_id": f"{draft.section_ids[0]}:p{draft.part}",
        "article_id": article["article_id"],
        "article_title": article["title"],
        "article_url": article["canonical_url"],
        "collection": article.get("collection"),
        "section_path": path,
        "section_ids": draft.section_ids,
        "media_section_ids": sorted(draft.carried + draft.section_ids, key=_ordinal),
        "chunk_index": index,
        "part": draft.part,
        "parts": draft.parts,
        "context_header": HEADER_SEPARATOR.join([article["title"]] + path),
        "text": draft.text,
        "token_estimate": draft.tokens,
        "last_updated": article.get("last_updated"),
    }
    chunk["content_hash"] = sha256_text(embedding_text(chunk))
    return chunk


def chunk_article(article: dict, cfg: Optional[ChunkingConfig] = None) -> list[dict]:
    drafter = _Drafter(cfg or ChunkingConfig())
    for section in article["sections"]:
        drafter.add_section(section)
    return [_finalize(article, draft, index) for index, draft in enumerate(drafter.finish())]


def chunk_corpus(articles: list[dict], cfg: Optional[ChunkingConfig] = None) -> list[dict]:
    return [chunk for article in articles for chunk in chunk_article(article, cfg)]


# --- Running over the corpus -------------------------------------------------------------------------


def chunk_report(chunks: list[dict], articles: int, cfg: ChunkingConfig) -> dict:
    sizes = sorted(chunk["token_estimate"] for chunk in chunks)
    split_sections = {chunk["section_ids"][0] for chunk in chunks if chunk["parts"] > 1}
    return {
        "articles": articles,
        "chunks": len(chunks),
        "tokens": {"min": sizes[0], "median": statistics.median(sizes), "p90": sizes[int(len(sizes) * 0.9)], "max": sizes[-1]},
        "merged_chunks": sum(1 for chunk in chunks if len(chunk["section_ids"]) > 1),
        "split_sections": len(split_sections),
        f"under_{SMALL_CHUNK_TOKENS}_tokens": sum(1 for size in sizes if size < SMALL_CHUNK_TOKENS),
        "config": cfg.__dict__,
        "token_estimate": f"characters / {cfg.chars_per_token}",
    }


def run_chunking(cfg: Optional[ChunkingConfig] = None) -> dict:
    """Chunk the cleaned articles and write data/chunks/chunks.jsonl plus a report. Needs no network access."""
    cfg = cfg or ChunkingConfig()
    articles = read_jsonl(config.PROCESSED_ARTICLES_JSONL)
    chunks = chunk_corpus(articles, cfg)
    write_atomic(CHUNKS_JSONL, "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks))
    report = chunk_report(chunks, len(articles), cfg)
    write_atomic(CHUNK_REPORT_PATH, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report
