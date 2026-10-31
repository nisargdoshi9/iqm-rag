"""Classify Help Center tables so each is handled by what it actually is.

Many tables are not data: callout boxes ("Note: ...") and image layouts are built from tables too.
Classes (decision D-FR2-3):
    callout       a boxed note: one row holding one text cell, or a bold "Label:" cell plus a text cell
    media_layout  images laid out in cells (one row with an image, or no text cells at all)
    data          a header row plus rows with the same number of columns
    unknown       anything else; kept in full and listed in the audit report
"""

import re

from iqm_rag.scraping.blocks import Block, block_plain, has_media

CALLOUT = "callout"
MEDIA_LAYOUT = "media_layout"
DATA = "data"
UNKNOWN = "unknown"

MAX_LABEL_CHARS = 80
MIN_DATA_ROWS = 2
MIN_HEADER_CELLS = 2
CALLOUT_MAX_CELLS = 2
LABEL_ONLY = re.compile(rf"^\*\*[^*]{{1,{MAX_LABEL_CHARS}}}(?::\*\*|\*\*:)$")


def _cell_markdown_start(cell: dict) -> str:
    first = cell["blocks"][0] if cell["blocks"] else None
    return first["text"] if first and first["type"] == "paragraph" else ""


def _is_callout(rows: list[dict]) -> bool:
    """A boxed note: one row, no media, and either a single text cell or a bold "Label:" cell plus a text cell.

    A single cell needs no label, because notes are also boxed without one ("Organization administrators can...").
    """
    if len(rows) != 1 or not 1 <= len(rows[0]["cells"]) <= CALLOUT_MAX_CELLS:
        return False
    cells = rows[0]["cells"]
    if any(has_media(cell["blocks"]) for cell in cells):
        return False
    if len(cells) == 1:
        return _cell_has_text(cells[0])
    return bool(LABEL_ONLY.match(_cell_markdown_start(cells[0]))) and bool(cells[1]["blocks"])


def _cell_has_text(cell: dict) -> bool:
    return any(block_plain(block) for block in cell["blocks"])


def _is_media_layout(rows: list[dict]) -> bool:
    cells = [cell for row in rows for cell in row["cells"]]
    has_image = any(has_media(cell["blocks"]) for cell in cells)
    has_text = any(_cell_has_text(cell) for cell in cells)
    return has_image and (len(rows) == 1 or not has_text)


def _is_data(rows: list[dict]) -> bool:
    if len(rows) < MIN_DATA_ROWS:
        return False
    header = rows[0]["cells"]
    filled = sum(1 for cell in header if _cell_has_text(cell))
    return filled >= MIN_HEADER_CELLS and all(len(row["cells"]) == len(header) for row in rows)


def classify_table(rows: list[dict]) -> tuple[str, str]:
    """Return (class, reason). The reason is kept so every classification can be audited."""
    cells = [cell for row in rows for cell in row["cells"]]
    if not cells or not any(_cell_has_text(cell) or has_media(cell["blocks"]) for cell in cells):
        return UNKNOWN, "empty table"
    if _is_callout(rows):
        return CALLOUT, "boxed note: one text cell, or a bold label cell plus a text cell"
    if _is_media_layout(rows):
        return MEDIA_LAYOUT, "images in cells (one row, or no text cells)"
    if _is_data(rows):
        return DATA, "header row with 2+ filled cells and rectangular rows"
    return UNKNOWN, _unknown_reason(rows)


def _unknown_reason(rows: list[dict]) -> str:
    widths = {len(row["cells"]) for row in rows}
    if len(rows) < MIN_DATA_ROWS:
        return "single row without a bold label or images"
    if len(widths) > 1:
        return f"rows have different column counts {sorted(widths)}"
    return "header row has fewer than 2 filled cells"


def annotate_table(block: Block) -> None:
    """Add table_class and table_reason to a table block, in place."""
    block["table_class"], block["table_reason"] = classify_table(block["rows"])
