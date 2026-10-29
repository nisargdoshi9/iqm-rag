"""Normalise raw articles into structured, Markdown-ready records (FR-2).

Reads the raw dataset only; never changes it. Output goes to data/processed/:
    articles.jsonl      one record per article: structured sections (source of truth) and derived Markdown
    media.jsonl         images and videos with provenance, association and exclusion reason
    table_audit.jsonl   every table classified `unknown`, with its original HTML and structured cells
    cleaning_report.json  counts and anything skipped or failed

IDs are deterministic. Ordinal IDs name a position ("123:s4" is the fourth section); content hashes identify
content. Matching an old and a new version of an article: same ordinal and same hash = unchanged; same hash at
a different ordinal = moved; same ordinal and different hash = edited.
"""

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from iqm_rag import config
from iqm_rag.scraping.blocks import Block, block_plain, nested_block_lists, parse_article_body, plain
from iqm_rag.scraping.markdown import render_blocks, row_markdown
from iqm_rag.scraping.scraper import write_atomic
from iqm_rag.scraping.tables import DATA, MEDIA_LAYOUT, UNKNOWN, annotate_table

logger = logging.getLogger(__name__)

NORMALIZATION_VERSION = 1
TOC_HEADING = "on this page"
TOC_SEARCH_LIMIT = 3
BACK_TO_TOP = "return to the top"  # matched as a prefix: "...of this article" and "...of this page" both occur
COLLECTION_OVERVIEW_MARKER = "collection overview"
APP_LABEL_SECTION = "primary app(s)"
EXCLUSION_APP_LABEL = "app_label"
NEARBY_CHARS = 200
MEDIA_TYPES = ("image", "video")
YOUTUBE_ID = re.compile(r"youtube\.com/embed/([\w-]{11})")

ASSOC_BEFORE_LIST = "before_list"
ASSOC_LIST_ITEM = "list_item"
ASSOC_AFTER_HEADING = "after_heading"
ASSOC_AFTER_HEADING_TEXT = "after_heading_text"
ASSOC_TABLE_ROW = "table_row"
ASSOC_TABLE_LAYOUT = "table_layout"
ASSOC_TABLE_CELL = "table_cell"
ASSOC_OTHER = "other"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Furniture ---------------------------------------------------------------------------------------


def _is_toc_heading(block: Block) -> bool:
    return block["type"] == "heading" and block["text"].strip().rstrip(":").strip().lower() == TOC_HEADING


def _is_back_to_top(block: Block) -> bool:
    return block["type"] == "paragraph" and plain(block["text"]).lower().startswith(BACK_TO_TOP)


def _remove_toc(blocks: list[Block], removed: dict) -> list[Block]:
    """Drop the auto-generated "On this page:" heading and the list of links that follows it."""
    for index, block in enumerate(blocks[:TOC_SEARCH_LIMIT]):
        if _is_toc_heading(block):
            has_list = index + 1 < len(blocks) and blocks[index + 1]["type"] == "list"
            removed["toc"] += 1
            return blocks[:index] + blocks[index + (2 if has_list else 1):]
    return blocks


def remove_furniture(blocks: list[Block]) -> tuple[list[Block], dict]:
    """Remove page furniture by structure (decision D-FR2-1): the table of contents and the back-to-top link."""
    removed = {"toc": 0, "back_to_top": 0}
    blocks = _remove_toc(blocks, removed)
    kept = [block for block in blocks if not _is_back_to_top(block)]
    removed["back_to_top"] = len(blocks) - len(kept)
    return kept, removed


def flatten_collapsibles(blocks: list[Block]) -> list[Block]:
    """Replace top-level collapsible sections by their summary and body, so their headings start sections."""
    flat: list[Block] = []
    for block in blocks:
        if block["type"] == "collapsible":
            flat.extend(flatten_collapsibles(block["summary"]))
            flat.extend(flatten_collapsibles(block["blocks"]))
        else:
            flat.append(block)
    return flat


def annotate_tables(blocks: list[Block]) -> None:
    for block in blocks:
        if block["type"] == "table":
            annotate_table(block)
        for nested in nested_block_lists(block):
            annotate_tables(nested)


# --- Sections, IDs and hashes -----------------------------------------------------------------------


def _new_section(heading: Optional[str], level: Optional[int], path: list[str]) -> dict:
    return {"heading": heading, "level": level, "heading_path": list(path), "blocks": []}


def _heading_path(stack: list[tuple[int, str]], block: Block) -> list[tuple[int, str]]:
    kept = [entry for entry in stack if entry[0] < block["level"]]
    return kept + [(block["level"], block["text"])]


def build_sections(blocks: list[Block], article_id: str) -> list[dict]:
    """Group blocks into sections that each start at a heading. Blocks before the first heading form one section."""
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    current = _new_section(None, None, [])
    for block in blocks:
        if block["type"] != "heading":
            current["blocks"].append(block)
            continue
        if current["blocks"] or current["heading"] is not None:
            sections.append(current)
        stack = _heading_path(stack, block)
        current = _new_section(block["text"], block["level"], [text for _, text in stack])
    if current["blocks"] or current["heading"] is not None:
        sections.append(current)
    for ordinal, section in enumerate(sections, start=1):
        section["ordinal"] = ordinal
        section["section_id"] = f"{article_id}:s{ordinal}"
    return sections


def _audit_table(block: Block, article_id: str, section_id: str, audit: list[dict]) -> None:
    html = block.pop("html", None)
    if block.get("table_class") == UNKNOWN:
        audit.append(
            {
                "article_id": article_id,
                "section_id": section_id,
                "table_id": block["id"],
                "reason": block["table_reason"],
                "rows": block["rows"],
                "html": html,
            }
        )


def _id_block(block: Block, section_id: str, counters: Counter, article_id: str, audit: list[dict]) -> None:
    kind = block["type"]
    if kind == "list":
        counters["l"] += 1
        block["id"] = f"{section_id}:l{counters['l']}"
        for number, item in enumerate(block["items"], start=1):
            item["id"] = f"{block['id']}:i{number}"
    elif kind == "table":
        counters["t"] += 1
        block["id"] = f"{section_id}:t{counters['t']}"
        for number, row in enumerate(block["rows"], start=1):
            row["id"] = f"{block['id']}:r{number}"
        _audit_table(block, article_id, section_id, audit)


def _assign_ids(blocks: list[Block], section_id: str, counters: Counter, article_id: str, audit: list[dict]) -> None:
    for block in blocks:
        _id_block(block, section_id, counters, article_id, audit)
        for nested in nested_block_lists(block):
            _assign_ids(nested, section_id, counters, article_id, audit)


def _add_hashes(blocks: list[Block]) -> None:
    for block in blocks:
        if block["type"] in ("list", "table"):
            block["content_hash"] = sha256_text(render_blocks([block]))
        if block["type"] == "table":
            for row in block["rows"]:
                row["content_hash"] = sha256_text(row_markdown(row))
        for nested in nested_block_lists(block):
            _add_hashes(nested)


def section_markdown(section: dict) -> str:
    heading = []
    if section["heading"] is not None:
        heading = [{"type": "heading", "level": section["level"], "text": section["heading"]}]
    return render_blocks(heading + section["blocks"])


def assign_structure(sections: list[dict], article_id: str) -> list[dict]:
    """Give lists, items, tables and rows IDs and hashes. Returns audit entries for unknown tables."""
    audit: list[dict] = []
    for section in sections:
        counters: Counter = Counter()
        _assign_ids(section["blocks"], section["section_id"], counters, article_id, audit)
        _add_hashes(section["blocks"])
        section["content_hash"] = sha256_text(section_markdown(section))
    return audit


# --- Media -------------------------------------------------------------------------------------------


def _neighbours(blocks: list[Block], index: int) -> tuple[Optional[Block], Optional[Block]]:
    before = next((b for b in reversed(blocks[:index]) if b["type"] not in MEDIA_TYPES), None)
    after = next((b for b in blocks[index + 1:] if b["type"] not in MEDIA_TYPES), None)
    return before, after


def _top_context(blocks: list[Block], index: int, base: dict) -> dict:
    """Association for an image that sits directly in a section (priority: before a list, then position)."""
    before, after = _neighbours(blocks, index)
    context = {
        "container_id": base["section_id"],
        "nearby_before": block_plain(before)[:NEARBY_CHARS] if before else "",
        "nearby_after": block_plain(after)[:NEARBY_CHARS] if after else "",
    }
    if after is not None and after["type"] == "list":
        return {**context, "association": ASSOC_BEFORE_LIST, "container_id": after["id"]}
    if before is None:
        return {**context, "association": ASSOC_AFTER_HEADING if base["has_heading"] else ASSOC_OTHER}
    return {**context, "association": ASSOC_AFTER_HEADING_TEXT if base["has_heading"] else ASSOC_OTHER}


def _table_association(table_class: str) -> str:
    return {DATA: ASSOC_TABLE_ROW, MEDIA_LAYOUT: ASSOC_TABLE_LAYOUT}.get(table_class, ASSOC_TABLE_CELL)


def _scan_table(block: Block, ctx: dict, found: list) -> None:
    table_class = block["table_class"]
    for row in block["rows"]:
        for cell in row["cells"]:
            cell_ctx = {
                **ctx,
                "association": _table_association(table_class),
                "container_id": row["id"] if table_class == DATA else block["id"],
                "table_id": block["id"],
                "table_class": table_class,
                "nearby_before": plain(row_markdown(row))[:NEARBY_CHARS],
                "nearby_after": "",
            }
            _scan(cell["blocks"], cell_ctx, found)


def _item_text(item: dict) -> str:
    return " ".join(part for part in (block_plain(block) for block in item["blocks"]) if part)[:NEARBY_CHARS]


def _scan(blocks: list[Block], ctx: dict, found: list) -> None:
    for block in blocks:
        kind = block["type"]
        if kind in MEDIA_TYPES:
            found.append((block, ctx))
        elif kind == "list":
            for item in block["items"]:
                item_ctx = {**ctx, "association": ASSOC_LIST_ITEM, "container_id": item["id"],
                            "nearby_before": _item_text(item), "nearby_after": ""}
                _scan(item["blocks"], item_ctx, found)
        elif kind == "table":
            _scan_table(block, ctx, found)
        else:
            for nested in nested_block_lists(block):
                _scan(nested, ctx, found)


def _media_type(block: Block) -> str:
    if block["type"] == "image":
        return "image"
    return "video_embed" if YOUTUBE_ID.search(block["src"]) else "embed"


def _media_record(article_id: str, ordinal: int, block: Block, ctx: dict) -> dict:
    video = YOUTUBE_ID.search(block["src"]) if block["type"] == "video" else None
    return {
        "media_id": f"{article_id}:m{ordinal}",
        "article_id": article_id,
        "ordinal": ordinal,
        "type": _media_type(block),
        "url": block["src"],
        "href": block.get("href"),
        "title": block.get("title"),
        "video_id": video.group(1) if video else None,
        "association": ctx.get("association", ASSOC_OTHER),
        "section_id": ctx["section_id"],
        "section_heading": ctx["section_heading"],
        "container_id": ctx.get("container_id", ctx["section_id"]),
        "table_id": ctx.get("table_id"),
        "table_class": ctx.get("table_class"),
        "nearby_before": ctx.get("nearby_before", ""),
        "nearby_after": ctx.get("nearby_after", ""),
        "excluded": False,
        "exclusion_reason": None,
        "app_name": None,
        "app_name_source": None,
    }


def _apply_exclusion(record: dict, article_title: str) -> None:
    """App-label images: collection overview article, "Primary app(s)" section (decision 2 and 6)."""
    heading = (record["section_heading"] or "").lower()
    if COLLECTION_OVERVIEW_MARKER in article_title.lower() and heading == APP_LABEL_SECTION:
        record.update(excluded=True, exclusion_reason=EXCLUSION_APP_LABEL, app_name_source="image_only")


def extract_media(article_id: str, article_title: str, sections: list[dict]) -> list[dict]:
    found: list[tuple[Block, dict]] = []
    for section in sections:
        base = {"section_id": section["section_id"], "section_heading": section["heading"],
                "has_heading": section["heading"] is not None}
        for index, block in enumerate(section["blocks"]):
            if block["type"] in MEDIA_TYPES:
                found.append((block, {**base, **_top_context(section["blocks"], index, base)}))
            else:
                _scan([block], base, found)
    records = [_media_record(article_id, n, block, ctx) for n, (block, ctx) in enumerate(found, start=1)]
    for record in records:
        _apply_exclusion(record, article_title)
    return records


# --- One article -------------------------------------------------------------------------------------


def render_article(title: str, sections: list[dict]) -> str:
    body = [section_markdown(section) for section in sections]
    return "\n\n".join([f"# {title}"] + [text for text in body if text])


def _count_blocks(blocks: list[Block], counts: Counter) -> None:
    for block in blocks:
        counts[block["type"]] += 1
        if block["type"] == "table":
            counts[f"table:{block['table_class']}"] += 1
        for nested in nested_block_lists(block):
            _count_blocks(nested, counts)


def normalize_article(raw: dict, html: bytes) -> tuple[dict, list[dict], list[dict]]:
    """Return (article record, media records, table audit entries) for one raw article."""
    article_id = raw["article_id"]
    blocks, removed = remove_furniture(parse_article_body(html, raw["canonical_url"]))
    blocks = flatten_collapsibles(blocks)
    annotate_tables(blocks)
    sections = build_sections(blocks, article_id)
    audit = assign_structure(sections, article_id)
    media = extract_media(article_id, raw["title"], sections)
    markdown = render_article(raw["title"], sections)
    counts: Counter = Counter()
    for section in sections:
        _count_blocks(section["blocks"], counts)
    record = {
        **{key: raw.get(key) for key in (
            "article_id", "title", "url", "canonical_url", "collection", "collections", "last_updated",
            "raw_html_path", "raw_html_sha256", "scraped_at", "scrape_status")},
        "sections": sections,
        "cleaned_markdown": markdown,
        "content_hash": sha256_text(markdown),
        "cleaning": {"version": NORMALIZATION_VERSION, "removed": removed, "block_counts": dict(counts)},
    }
    return record, media, audit


# --- Whole dataset -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessedPaths:
    raw_jsonl: Path
    raw_root: Path  # raw_html_path values are relative to this directory
    articles: Path
    media: Path
    audit: Path
    report: Path

    @classmethod
    def default(cls) -> "ProcessedPaths":
        return cls(config.ARTICLES_JSONL, config.ROOT_DIR, config.PROCESSED_ARTICLES_JSONL,
                   config.MEDIA_JSONL, config.TABLE_AUDIT_JSONL, config.CLEANING_REPORT_PATH)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    write_atomic(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _normalize_one(raw: dict, root: Path) -> tuple[dict, list[dict], list[dict]]:
    html = (root / raw["raw_html_path"]).read_bytes()
    return normalize_article(raw, html)


def _build_report(articles: list[dict], media: list[dict], audit: list[dict], skipped: list, failed: list) -> dict:
    blocks: Counter = Counter()
    removed: Counter = Counter()
    for article in articles:
        blocks.update(article["cleaning"]["block_counts"])
        removed.update(article["cleaning"]["removed"])
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "articles_processed": len(articles),
        "skipped": skipped,
        "failed": failed,
        "sections": sum(len(article["sections"]) for article in articles),
        "block_counts": {k: v for k, v in sorted(blocks.items()) if not k.startswith("table:")},
        "tables_by_class": {k[len("table:"):]: v for k, v in sorted(blocks.items()) if k.startswith("table:")},
        "unknown_tables": {"count": len(audit), "reasons": dict(Counter(entry["reason"] for entry in audit))},
        "furniture_removed": dict(removed),
        "media": {
            "total": len(media),
            "by_type": dict(Counter(item["type"] for item in media)),
            "by_association": dict(Counter(item["association"] for item in media)),
            "excluded_by_reason": dict(Counter(item["exclusion_reason"] for item in media if item["excluded"])),
        },
        "unknown_blocks": blocks.get("unknown", 0),
        "empty_markdown_articles": [a["article_id"] for a in articles if a["cleaned_markdown"].count("\n") < 2],
    }


def run_normalization(paths: ProcessedPaths) -> dict:
    """Normalise every successfully scraped article. Failures are reported, never silently dropped."""
    raw_records = sorted(read_jsonl(paths.raw_jsonl), key=lambda record: int(record["article_id"]))
    articles, media, audit, skipped, failed = [], [], [], [], []
    for raw in raw_records:
        if raw.get("scrape_status") != "success":
            skipped.append({"article_id": raw["article_id"], "reason": f"raw scrape_status={raw.get('scrape_status')}"})
            continue
        try:
            record, article_media, article_audit = _normalize_one(raw, paths.raw_root)
        except (OSError, ValueError, KeyError) as exc:
            failed.append({"article_id": raw["article_id"], "error": f"{type(exc).__name__}: {exc}"})
            continue
        articles.append(record)
        media.extend(article_media)
        audit.extend(article_audit)
    _write_jsonl(paths.articles, articles)
    _write_jsonl(paths.media, media)
    _write_jsonl(paths.audit, audit)
    report = _build_report(articles, media, audit, skipped, failed)
    write_atomic(paths.report, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report
