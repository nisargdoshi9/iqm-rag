"""An MCP server that exposes the Help Center search to any MCP client (bonus: MCP server).

Two read-only tools: `search_help_center` returns the best passages for a query (the same pipeline as the chat page: hybrid
search with a rerank by default) and `get_article` returns the cleaned text of one article, paged. The client's own model writes
the answer from the passages and cites their URLs. The index and the articles load on the first call, so the connection starts
quickly and a missing index becomes a clear tool error instead of a crash. Over stdio nothing may be printed to stdout (it
carries the protocol), so all logging goes to stderr.
"""

import re
from pathlib import Path
from typing import Annotated, Callable, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from iqm_rag import config
from iqm_rag.ingestion.embeddings import EmbeddingError
from iqm_rag.ingestion.indexing import IndexMismatchError, IndexNotBuiltError
from iqm_rag.retrieval.pipeline import default_pipeline
from iqm_rag.retrieval.retriever import RetrievalError
from iqm_rag.scraping.normalization import read_jsonl

SERVER_NAME = "iqm-help-center"
DEFAULT_TOP_K = 5
MAX_TOP_K = 10
MAX_PASSAGE_CHARS = 2000  # a longer passage is cut (and flagged); get_article returns the whole text
DEFAULT_ARTICLE_CHARS = 8000
MIN_ARTICLE_CHARS, MAX_ARTICLE_CHARS = 500, 20000
ARTICLE_ID = re.compile(r"/articles/(\d+)")

INSTRUCTIONS = (
    "Answers about the IQM advertising platform come from the IQM Help Center (help.iqm.com). Search it with search_help_center, "
    "answer only from the passages returned, and cite the URL of each passage you use. If the passages do not answer the question, "
    "say that the Help Center does not cover it instead of guessing."
)
SEARCH_DESCRIPTION = (
    "Search the IQM Help Center (help.iqm.com), the official documentation for the IQM advertising platform: campaigns and insertion "
    "orders, audiences, creatives, inventory, delivery and optimization, conversions, reporting, account setup, and the Vera assistant. "
    "Returns the most relevant passages, each with its article title, section and URL. Use it for any question about how IQM works "
    "and answer only from the passages, citing each URL you use. If nothing returned answers the question, say the Help Center does "
    "not cover it. A search takes a few seconds; for more coverage raise top_k (up to 10) instead of repeating the same words. "
    "Use get_article when you need the full text of one article."
)
ARTICLE_DESCRIPTION = (
    "Get the full text of one IQM Help Center article as Markdown, by its URL or numeric ID (as returned by search_help_center). "
    "Long articles are returned in pages: when has_more is true, call again with offset set to next_offset."
)


class HelpCenterError(Exception):
    """A problem the caller can understand and act on."""


class Passage(BaseModel):
    rank: int = Field(description="1 is the most relevant")
    title: str = Field(description="Article title")
    section: str = Field(description="Heading path inside the article")
    url: str = Field(description="Article URL: cite this")
    relevance: float = Field(description="Vector similarity between the query and the passage (0 to 1). Passages are ordered by a reranker, so the scores are not strictly descending.")
    text: str
    truncated: bool = Field(description="True if the passage was cut at the length limit; use get_article for the whole article")


class SearchResponse(BaseModel):
    query: str
    results: list[Passage]


class ArticleResponse(BaseModel):
    title: str
    url: str
    collection: Optional[str]
    last_updated: Optional[str]
    total_chars: int
    offset: int
    has_more: bool
    next_offset: Optional[int] = Field(description="Pass this as offset to continue; null on the last page")
    markdown: str


def _passage(hit) -> Passage:
    chunk = hit.chunk
    text = chunk["text"]
    cut = len(text) > MAX_PASSAGE_CHARS
    return Passage(rank=hit.rank, title=chunk["article_title"], section=" › ".join(chunk["section_path"]), url=chunk["article_url"],
                   relevance=round(hit.similarity, 3), text=text[:MAX_PASSAGE_CHARS].rstrip() + (" …" if cut else ""), truncated=cut)


def _page(text: str, offset: int, max_chars: int) -> tuple[str, Optional[int]]:
    """The slice of `text` from `offset`, ended at a line break when one is near the limit; and the offset of the next page, if any."""
    end = offset + max_chars
    if end >= len(text):
        return text[offset:], None
    line_break = text.rfind("\n", offset + max_chars // 2, end)
    end = line_break + 1 if line_break != -1 else end
    return text[offset:end], end


class HelpCenter:
    """The operations behind the tools. Loads the search pipeline and the articles on first use."""

    def __init__(self, pipeline_factory: Callable = default_pipeline, articles_path: Path = config.PROCESSED_ARTICLES_JSONL) -> None:
        self._pipeline_factory, self._articles_path = pipeline_factory, articles_path
        self._pipeline = None
        self._articles: Optional[list[dict]] = None

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> SearchResponse:
        if not query.strip():
            raise HelpCenterError("The query is empty.")
        if not 1 <= top_k <= MAX_TOP_K:
            raise HelpCenterError(f"top_k must be between 1 and {MAX_TOP_K}, got {top_k}.")
        try:
            if self._pipeline is None:
                self._pipeline = self._pipeline_factory()
            result = self._pipeline.retrieve(query, top_k=top_k)
        except IndexNotBuiltError as exc:
            raise HelpCenterError(f"The search index is not built on the server: {exc}") from exc
        except (IndexMismatchError, EmbeddingError, RetrievalError, ValueError, RuntimeError) as exc:
            raise HelpCenterError(f"Search failed: {exc}") from exc
        return SearchResponse(query=result.query, results=[_passage(hit) for hit in result.hits])

    def _find(self, reference: str) -> dict:
        if self._articles is None:
            if not self._articles_path.exists():
                raise HelpCenterError(f"The cleaned articles are not on the server ({self._articles_path}). Run scripts/normalize.py.")
            self._articles = read_jsonl(self._articles_path)
        ref = reference.strip()
        found = ARTICLE_ID.search(ref)
        article_id = ref if ref.isdigit() else (found.group(1) if found else None)
        for article in self._articles:
            if article["article_id"] == article_id or ref in (article.get("canonical_url"), article.get("url")):
                return article
        raise HelpCenterError(f"No article matches {reference!r}. Use search_help_center to find the article URL.")

    def get_article(self, reference: str, max_chars: int = DEFAULT_ARTICLE_CHARS, offset: int = 0) -> ArticleResponse:
        if not MIN_ARTICLE_CHARS <= max_chars <= MAX_ARTICLE_CHARS:
            raise HelpCenterError(f"max_chars must be between {MIN_ARTICLE_CHARS} and {MAX_ARTICLE_CHARS}, got {max_chars}.")
        article = self._find(reference)
        text = article["cleaned_markdown"]
        if not 0 <= offset <= len(text):
            raise HelpCenterError(f"offset must be between 0 and {len(text)} for this article, got {offset}.")
        markdown, next_offset = _page(text, offset, max_chars)
        return ArticleResponse(title=article["title"], url=article["canonical_url"], collection=article.get("collection"),
                               last_updated=article.get("last_updated"), total_chars=len(text), offset=offset,
                               has_more=next_offset is not None, next_offset=next_offset, markdown=markdown)


def build_server(help_center: Optional[HelpCenter] = None) -> MCPServer:
    center = help_center or HelpCenter()
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)
    read_only = dict(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @server.tool(name="search_help_center", description=SEARCH_DESCRIPTION,
                 annotations=ToolAnnotations(title="Search the IQM Help Center", **read_only))
    def search_help_center(
        query: Annotated[str, Field(description="What to look up, in plain words, for example 'how do I schedule a report'")],
        top_k: Annotated[int, Field(description=f"How many passages to return (1 to {MAX_TOP_K})")] = DEFAULT_TOP_K,
    ) -> SearchResponse:
        try:
            return center.search(query, top_k)
        except HelpCenterError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="get_article", description=ARTICLE_DESCRIPTION, annotations=ToolAnnotations(title="Get a Help Center article", **read_only))
    def get_article(
        article: Annotated[str, Field(description="The article URL or numeric ID")],
        max_chars: Annotated[int, Field(description=f"Page size in characters ({MIN_ARTICLE_CHARS} to {MAX_ARTICLE_CHARS})")] = DEFAULT_ARTICLE_CHARS,
        offset: Annotated[int, Field(description="Where to start, in characters; use next_offset from the previous page")] = 0,
    ) -> ArticleResponse:
        try:
            return center.get_article(article, max_chars, offset)
        except HelpCenterError as exc:
            raise ToolError(str(exc)) from exc

    return server
