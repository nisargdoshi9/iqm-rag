"""Render structured blocks as Markdown.

The structured blocks are the source of truth; Markdown is derived from them. Images and videos are not
rendered: chunks stay text-only and media is joined later through IDs (decision 9).
"""

from iqm_rag.scraping.blocks import Block
from iqm_rag.scraping.tables import CALLOUT, DATA, MEDIA_LAYOUT

CELL_ITEM_SEPARATOR = "; "  # lists inside table cells (decision D-FR2-4)
TITLE_HEADING_OFFSET = 1  # the article title is "#", so a level-1 heading renders as "##"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def cell_markdown(cell: dict) -> str:
    """One table cell as a single line. Lists inside the cell are joined with '; '."""
    parts: list[str] = []
    for block in cell["blocks"]:
        if block["type"] == "list":
            parts.append(CELL_ITEM_SEPARATOR.join(_item_inline(item) for item in block["items"]))
        else:
            parts.extend(render_block(block))
    return _escape_cell(" ".join(part for part in parts if part))


def _item_inline(item: dict) -> str:
    return " ".join(line.strip() for block in item["blocks"] for line in render_block(block) if line.strip())


def row_markdown(row: dict) -> str:
    return "| " + " | ".join(cell_markdown(cell) for cell in row["cells"]) + " |"


def table_header_lines(rows: list[dict]) -> list[str]:
    """The header row and the Markdown separator line of a pipe table."""
    separator = "| " + " | ".join("---" for _ in rows[0]["cells"]) + " |"
    return [row_markdown(rows[0]), separator]


def _pipe_table(rows: list[dict]) -> list[str]:
    return table_header_lines(rows) + [row_markdown(row) for row in rows[1:]]


def _callout_lines(block: Block) -> list[str]:
    """A callout table renders as a blockquote; its bold label stays at the start."""
    cells = block["rows"][0]["cells"]
    text = " ".join(cell_markdown(cell) for cell in cells if cell["blocks"])
    return [f"> {text}"]


def _layout_lines(block: Block) -> list[str]:
    """Text found in image layouts is kept, as ordinary paragraphs, in cell order."""
    lines: list[str] = []
    for row in block["rows"]:
        for cell in row["cells"]:
            for child in cell["blocks"]:
                lines.extend(render_block(child))
    return lines


def _fallback_rows(block: Block) -> list[str]:
    return [f"- {' | '.join(cell_markdown(cell) for cell in row['cells'])}" for row in block["rows"]]


def _table_lines(block: Block) -> list[str]:
    kind = block.get("table_class")
    if kind == DATA:
        return _pipe_table(block["rows"])
    if kind == CALLOUT:
        return _callout_lines(block)
    if kind == MEDIA_LAYOUT:
        return _layout_lines(block)
    return _fallback_rows(block)


def list_item_markdown(item: dict, number: int, ordered: bool) -> str:
    """One list item with its marker (empty string if the item has no text). Nested lists stay inside the item."""
    marker = f"{number}. " if ordered else "- "
    item_lines = [line for child in item["blocks"] for line in render_block(child)]
    if not item_lines:
        return ""
    pad = " " * len(marker)
    return "\n".join([marker + item_lines[0]] + [(pad + line) if line else "" for line in item_lines[1:]])


def _list_lines(block: Block) -> list[str]:
    lines: list[str] = []
    for number, item in enumerate(block["items"], start=1):
        text = list_item_markdown(item, number, block["ordered"])
        if text:
            lines.extend(text.split("\n"))
    return lines


def render_block(block: Block) -> list[str]:
    """Markdown lines for one block. Images and videos render nothing."""
    kind = block["type"]
    if kind == "paragraph":
        return [block["text"]]
    if kind == "heading":
        return ["#" * (block["level"] + TITLE_HEADING_OFFSET) + " " + block["text"]]
    if kind == "list":
        return _list_lines(block)
    if kind == "table":
        return _table_lines(block)
    if kind == "code":
        return ["```", *block["text"].split("\n"), "```"]
    if kind in ("callout", "collapsible"):
        return _container_lines(block)
    return []


def _container_lines(block: Block) -> list[str]:
    children = (block.get("summary") or []) + block["blocks"]
    lines = [line for child in children for line in render_block(child)]
    return [f"> {line}" if block["type"] == "callout" and line else line for line in lines]


def render_blocks(blocks: list[Block]) -> str:
    """Markdown for a sequence of blocks, one blank line between blocks."""
    rendered = ["\n".join(render_block(block)) for block in blocks]
    return "\n\n".join(text for text in rendered if text.strip())
