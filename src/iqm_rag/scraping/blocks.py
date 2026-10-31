"""Parse a Help Center article body into structured blocks.

The body is built from Intercom block wrappers (`div.intercom-interblocks-*`), each holding one element.
Blocks nest: list items, table cells and collapsible sections contain further blocks. Nothing is dropped
silently: markup the parser does not recognise becomes an `unknown` block that keeps its HTML.

Block shapes (all are plain dicts so they serialise to JSON as they are):
    heading    {"type", "level", "text"}
    paragraph  {"type", "text"}                       text is inline Markdown
    list       {"type", "ordered", "items": [{"blocks"}]}
    table      {"type", "rows": [{"cells": [{"blocks"}]}], "html"}
    callout    {"type", "blocks"}
    collapsible{"type", "summary", "blocks"}
    code       {"type", "text"}
    image      {"type", "src", "href"}
    video      {"type", "src", "title"}
    unknown    {"type", "kind", "html"}
"""

import re
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from bs4.element import PageElement

Block = dict

BLOCK_PREFIX = "intercom-interblocks-"
ALIGN_PREFIX = BLOCK_PREFIX + "align"
ZERO_WIDTH = re.compile("[​‌‍﻿]")
LINK_MARKDOWN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
INLINE_TAGS = {"a", "b", "strong", "i", "em", "code", "span", "u", "br", "sup", "sub"}
SKIPPED_INLINE_TAGS = {"img", "iframe", "script", "style"}
HEADING_LEVELS = {"heading": 1, "subheading": 2, "subheading3": 3, "subheading4": 4}
DEEPEST_HEADING_LEVEL = 4
TAG_KINDS = {
    "p": "paragraph", "h1": "heading", "h2": "subheading", "h3": "subheading3", "h4": "subheading4",
    "h5": "subheading4", "h6": "subheading4", "ul": "unordered-nested-list", "ol": "ordered-nested-list",
    "table": "table", "img": "image", "iframe": "video", "pre": "code",
}


# --- Inline text -------------------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Remove invisible characters and collapse whitespace."""
    return re.sub(r"\s+", " ", ZERO_WIDTH.sub("", text).replace("\xa0", " "))


def plain(markdown: str) -> str:
    """Strip inline Markdown (links, bold, italic, code) down to the visible text."""
    return re.sub(r"[*`]", "", LINK_MARKDOWN.sub(r"\1", markdown)).strip()


def _wrap(marker: str, inner: str) -> str:
    """Wrap in a marker, moving edge spaces outside so 'Label: ' becomes '**Label:** '."""
    stripped = inner.strip()
    if not stripped:
        return inner
    lead = " " if inner[:1].isspace() else ""
    trail = " " if inner[-1:].isspace() else ""
    return f"{lead}{marker}{stripped}{marker}{trail}"


def _link(node: Tag, base_url: str) -> str:
    text = _inline_children(node, base_url).strip()
    href = (node.get("href") or "").strip()
    if not text or not href or href.startswith("#"):
        return text  # in-page anchors mean nothing outside the page
    return f"[{text}]({urljoin(base_url, href)})"


def _inline_node(node: PageElement, base_url: str) -> str:
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return clean_text(str(node))
    if node.name == "br":
        return " "
    if node.name in SKIPPED_INLINE_TAGS:
        return ""
    if node.name == "a":
        return _link(node, base_url)
    marker = {"b": "**", "strong": "**", "i": "*", "em": "*", "code": "`"}.get(node.name)
    inner = _inline_children(node, base_url)
    return _wrap(marker, inner) if marker else inner


def _inline_children(node: Tag, base_url: str) -> str:
    return "".join(_inline_node(child, base_url) for child in node.children)


def inline_markdown(node: Tag, base_url: str) -> str:
    return re.sub(r" +", " ", _inline_children(node, base_url)).strip()


def plain_text(node: Tag) -> str:
    return clean_text(node.get_text(" ")).strip()


# --- Block parsing -----------------------------------------------------------------------------------


def block_kind(el: Tag) -> Optional[str]:
    for cls in el.get("class", []):
        if cls.startswith(BLOCK_PREFIX) and not cls.startswith(ALIGN_PREFIX):
            return cls[len(BLOCK_PREFIX):]
    return None


def _paragraph(el: Tag, kind: str, base_url: str) -> list[Block]:
    """A paragraph, followed by any images placed inside it (they are media, not text)."""
    node = el.find("p") or el
    text = inline_markdown(node, base_url)
    blocks: list[Block] = [{"type": "paragraph", "text": text}] if text else []
    for img in node.find_all("img"):
        blocks.extend(_image(img, "image", base_url))
    return blocks


def _heading(el: Tag, kind: str, base_url: str) -> list[Block]:
    tag = el if re.fullmatch(r"h[1-6]", el.name) else el.find(re.compile(r"^h[1-6]$"))
    text = plain_text(tag or el)
    level = HEADING_LEVELS.get(kind, DEEPEST_HEADING_LEVEL)
    return [{"type": "heading", "level": level, "text": text}] if text else []


def _list(el: Tag, kind: str, base_url: str) -> list[Block]:
    list_el = el if el.name in ("ul", "ol") else el.find(["ul", "ol"])
    if list_el is None:
        return _unknown(el, kind, base_url)
    items = [{"blocks": parse_blocks(li, base_url)} for li in list_el.find_all("li", recursive=False)]
    items = [item for item in items if item["blocks"]]
    return [{"type": "list", "ordered": kind.startswith("ordered"), "items": items}] if items else []


def _table(el: Tag, kind: str, base_url: str) -> list[Block]:
    table = el if el.name == "table" else el.find("table")
    if table is None:
        return _unknown(el, kind, base_url)
    rows = [
        {"cells": [{"blocks": parse_blocks(cell, base_url)} for cell in tr.find_all(["td", "th"], recursive=False)]}
        for tr in table.find_all("tr")
    ]
    return [{"type": "table", "rows": rows, "html": str(table)}]


def _image(el: Tag, kind: str, base_url: str) -> list[Block]:
    img = el if el.name == "img" else el.find("img")
    src = (img.get("src") or "").strip() if img else ""
    if not src:
        return _unknown(el, kind, base_url)
    anchor = img.find_parent("a")
    href = urljoin(base_url, anchor["href"]) if anchor and anchor.get("href") else None
    return [{"type": "image", "src": urljoin(base_url, src), "href": href}]


def _video(el: Tag, kind: str, base_url: str) -> list[Block]:
    frame = el if el.name == "iframe" else el.find("iframe")
    src = (frame.get("src") or "").strip() if frame else ""
    if not src:
        return _unknown(el, kind, base_url)
    return [{"type": "video", "src": urljoin(base_url, src), "title": frame.get("title")}]


def _code(el: Tag, kind: str, base_url: str) -> list[Block]:
    pre = el if el.name == "pre" else el.find("pre")
    if pre is None:
        return _unknown(el, kind, base_url)
    for line_break in pre.find_all("br"):
        line_break.replace_with("\n")
    text = pre.get_text().strip("\n")
    return [{"type": "code", "text": text}] if text.strip() else []


def _callout(el: Tag, kind: str, base_url: str) -> list[Block]:
    blocks = parse_blocks(el, base_url)
    return [{"type": "callout", "blocks": blocks}] if blocks else []


def _collapsible(el: Tag, kind: str, base_url: str) -> list[Block]:
    details = el.find("details")
    if details is None:
        return _unknown(el, kind, base_url)
    summary = details.find("summary")
    body = [child for child in details.children if isinstance(child, Tag) and child.name != "summary"]
    blocks = [block for child in body for block in parse_block(child, base_url)]
    return [{"type": "collapsible", "summary": parse_blocks(summary, base_url) if summary else [], "blocks": blocks}]


def _unknown(el: Tag, kind: Optional[str], base_url: str) -> list[Block]:
    return [{"type": "unknown", "kind": kind or el.name, "html": str(el)}]


_HANDLERS: dict[str, Callable[[Tag, str, str], list[Block]]] = {
    "paragraph": _paragraph,
    "heading": _heading,
    "subheading": _heading,
    "subheading3": _heading,
    "subheading4": _heading,
    "unordered-nested-list": _list,
    "ordered-nested-list": _list,
    "table": _table,
    "image": _image,
    "video": _video,
    "code": _code,
    "callout": _callout,
    "collapsible-section": _collapsible,
}


def parse_block(el: Tag, base_url: str) -> list[Block]:
    kind = block_kind(el) or TAG_KINDS.get(el.name)
    handler = _HANDLERS.get(kind)
    return handler(el, kind, base_url) if handler else _unknown(el, kind, base_url)


def _flush_inline(buffer: list, base_url: str) -> list[Block]:
    text = re.sub(r" +", " ", "".join(_inline_node(node, base_url) for node in buffer)).strip()
    return [{"type": "paragraph", "text": text}] if text else []


def parse_blocks(container: Tag, base_url: str) -> list[Block]:
    """Parse the children of a container. Loose inline content (text, links) becomes one paragraph."""
    blocks: list[Block] = []
    buffer: list = []
    for child in container.children:
        is_inline = isinstance(child, NavigableString) or (child.name in INLINE_TAGS and not block_kind(child))
        if is_inline:
            buffer.append(child)
            continue
        blocks.extend(_flush_inline(buffer, base_url))
        buffer = []
        blocks.extend(parse_block(child, base_url))
    return blocks + _flush_inline(buffer, base_url)


def parse_article_body(html: bytes, base_url: str) -> list[Block]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".article_body > article") or soup.select_one(".article_body")
    if body is None:
        raise ValueError("no .article_body found")
    return parse_blocks(body, base_url)


# --- Helpers over parsed blocks ----------------------------------------------------------------------


def nested_block_lists(block: Block) -> list[list[Block]]:
    """Every list of child blocks inside a block (list items, table cells, callout and collapsible bodies)."""
    kind = block["type"]
    if kind == "list":
        return [item["blocks"] for item in block["items"]]
    if kind == "table":
        return [cell["blocks"] for row in block["rows"] for cell in row["cells"]]
    if kind == "callout":
        return [block["blocks"]]
    if kind == "collapsible":
        return [block["summary"], block["blocks"]]
    return []


def block_plain(block: Block) -> str:
    """Visible text of a block, without Markdown markers. Media contributes nothing."""
    kind = block["type"]
    if kind in ("paragraph", "heading", "code"):
        return plain(block["text"]) if kind == "paragraph" else block["text"]
    parts = [block_plain(child) for children in nested_block_lists(block) for child in children]
    return " ".join(part for part in parts if part)


def has_media(blocks: list[Block]) -> bool:
    for block in blocks:
        if block["type"] in ("image", "video"):
            return True
        if any(has_media(children) for children in nested_block_lists(block)):
            return True
    return False
