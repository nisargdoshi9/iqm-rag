"""Tests for the MCP server, through an in-memory MCP client. A topic embedder and a throwaway index; no network, no API calls."""

import json
import tempfile
import unittest
from pathlib import Path

import hermetic  # noqa: F401  (keeps tracing off in tests)
from mcp import Client

from iqm_rag.ingestion.embeddings import EmbeddingError
from iqm_rag.ingestion.indexing import IndexNotBuiltError, run_indexing
from iqm_rag.mcp_server import MAX_PASSAGE_CHARS, HelpCenter, HelpCenterError, _page, build_server
from iqm_rag.retrieval.pipeline import RetrievalPipeline, RetrievalSettings
from iqm_rag.retrieval.retriever import Retriever
from test_retrieval import CHUNKS, TopicEmbedder, topic_chunk

LONG_LINES = [f"Line {n} of a long article about scheduling." for n in range(400)]
ARTICLES = [
    {"article_id": "1", "title": "Title", "canonical_url": "https://help.iqm.com/en/articles/1-t", "url": "https://help.iqm.com/en/articles/1-t",
     "collection": "Coll", "last_updated": "2026-01-01T00:00:00Z", "cleaned_markdown": "# Title\n\nShort article."},
    {"article_id": "2", "title": "Long", "canonical_url": "https://help.iqm.com/en/articles/2-long", "url": "https://help.iqm.com/en/articles/2-long",
     "collection": None, "last_updated": None, "cleaned_markdown": "\n".join(LONG_LINES)},
]


class McpTestCase(unittest.IsolatedAsyncioTestCase):
    chunks = CHUNKS

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        embedder = TopicEmbedder()
        index = Path(tmp.name) / "chroma"
        run_indexing(self.chunks, embedder, index)
        articles = Path(tmp.name) / "articles.jsonl"
        articles.write_text("".join(json.dumps(a) + "\n" for a in ARTICLES), encoding="utf-8")
        retriever = Retriever(embedder, index, top_k=5)
        self.center = HelpCenter(lambda: RetrievalPipeline(retriever, RetrievalSettings("dense", "off")), articles)

    def client(self) -> Client:
        return Client(build_server(self.center))


class ToolListTests(McpTestCase):
    async def test_two_read_only_tools_with_usable_descriptions_are_offered(self):
        async with self.client() as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        self.assertEqual(set(tools), {"search_help_center", "get_article"})
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
        self.assertIn("help.iqm.com", tools["search_help_center"].description)
        self.assertIn("citing each URL", tools["search_help_center"].description)
        self.assertEqual(set(tools["search_help_center"].input_schema["required"]), {"query"})
        self.assertEqual(set(tools["get_article"].input_schema["required"]), {"article"})


class SearchTests(McpTestCase):
    async def test_search_returns_passages_with_title_section_url_and_relevance(self):
        async with self.client() as client:
            result = await client.call_tool("search_help_center", {"query": "export", "top_k": 2})
        self.assertFalse(result.is_error)
        data = result.structured_content
        self.assertEqual((data["query"], len(data["results"])), ("export", 2))
        first = data["results"][0]
        self.assertEqual((first["rank"], first["url"], first["title"], first["section"]), (1, CHUNKS[1]["article_url"], "Title", "A › B2"))
        self.assertTrue(0.0 < first["relevance"] <= 1.0)
        self.assertEqual((first["text"], first["truncated"]), (CHUNKS[1]["text"], False))

    async def test_the_default_is_five_passages_and_top_k_is_checked(self):
        async with self.client() as client:
            default = await client.call_tool("search_help_center", {"query": "schedule"})
            too_many = await client.call_tool("search_help_center", {"query": "schedule", "top_k": 11})
            none = await client.call_tool("search_help_center", {"query": "schedule", "top_k": 0})
        self.assertEqual(len(default.structured_content["results"]), 5)
        for bad in (too_many, none):
            self.assertTrue(bad.is_error)
            self.assertIn("top_k must be between 1 and 10", bad.content[0].text)

    async def test_an_empty_query_is_a_tool_error_not_a_crash(self):
        async with self.client() as client:
            result = await client.call_tool("search_help_center", {"query": "   "})
        self.assertTrue(result.is_error)
        self.assertIn("empty", result.content[0].text)


class LongPassageTests(McpTestCase):
    chunks = CHUNKS + [topic_chunk(6, "schedule " + "word " * 600)]

    async def test_a_long_passage_is_cut_and_flagged(self):
        async with self.client() as client:
            result = await client.call_tool("search_help_center", {"query": "schedule schedule schedule", "top_k": 6})
        cut = [p for p in result.structured_content["results"] if p["truncated"]]
        self.assertEqual(len(cut), 1)
        self.assertLessEqual(len(cut[0]["text"]), MAX_PASSAGE_CHARS + 2)
        self.assertTrue(cut[0]["text"].endswith("…"))


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, error: Exception) -> str:
        class Broken:
            def retrieve(self, query, top_k):
                raise error

        async with Client(build_server(HelpCenter(lambda: Broken()))) as client:
            result = await client.call_tool("search_help_center", {"query": "x"})
        self.assertTrue(result.is_error)
        return result.content[0].text

    async def test_a_missing_index_and_service_failures_become_clear_tool_errors(self):
        self.assertIn("index is not built", await self.call(IndexNotBuiltError("Run scripts/index.py")))
        self.assertIn("Search failed", await self.call(EmbeddingError("simulated outage")))

    async def test_a_pipeline_that_cannot_start_is_reported_not_raised(self):
        def factory():
            raise IndexNotBuiltError("no index here")

        async with Client(build_server(HelpCenter(factory))) as client:
            result = await client.call_tool("search_help_center", {"query": "x"})
        self.assertTrue(result.is_error)
        self.assertIn("no index here", result.content[0].text)


class ArticleTests(McpTestCase):
    async def test_an_article_is_found_by_url_or_id(self):
        async with self.client() as client:
            by_url = await client.call_tool("get_article", {"article": "https://help.iqm.com/en/articles/1-t"})
            by_id = await client.call_tool("get_article", {"article": "1"})
            by_other_url = await client.call_tool("get_article", {"article": "https://help.iqm.com/en/articles/1-renamed"})
        for result in (by_url, by_id, by_other_url):
            data = result.structured_content
            self.assertEqual((data["title"], data["markdown"], data["has_more"], data["next_offset"]), ("Title", "# Title\n\nShort article.", False, None))
        self.assertEqual(by_url.structured_content["collection"], "Coll")

    async def test_a_long_article_is_paged_at_line_breaks_without_losing_text(self):
        pages, offset = [], 0
        async with self.client() as client:
            while True:
                result = await client.call_tool("get_article", {"article": "2", "max_chars": 1000, "offset": offset})
                data = result.structured_content
                pages.append(data["markdown"])
                if not data["has_more"]:
                    break
                self.assertTrue(data["markdown"].endswith("\n"))
                offset = data["next_offset"]
        self.assertGreater(len(pages), 3)
        self.assertEqual("".join(pages), "\n".join(LONG_LINES))

    async def test_bad_references_and_limits_are_tool_errors(self):
        async with self.client() as client:
            unknown = await client.call_tool("get_article", {"article": "999"})
            garbage = await client.call_tool("get_article", {"article": "not an article"})
            small = await client.call_tool("get_article", {"article": "1", "max_chars": 10})
            past_end = await client.call_tool("get_article", {"article": "1", "offset": 10_000})
        for bad in (unknown, garbage, small, past_end):
            self.assertTrue(bad.is_error)
        self.assertIn("search_help_center", unknown.content[0].text)
        self.assertIn("max_chars must be between", small.content[0].text)
        self.assertIn("offset must be between", past_end.content[0].text)

    async def test_missing_articles_file_is_reported(self):
        center = HelpCenter(lambda: None, Path("/nonexistent/articles.jsonl"))
        async with Client(build_server(center)) as client:
            result = await client.call_tool("get_article", {"article": "1"})
        self.assertTrue(result.is_error)
        self.assertIn("scripts/normalize.py", result.content[0].text)


class PageTests(unittest.TestCase):
    def test_pages_end_at_line_breaks_and_the_last_page_has_no_next_offset(self):
        text = "aaaa\nbbbb\ncccc\ndddd"
        self.assertEqual(_page(text, 0, 12), ("aaaa\nbbbb\n", 10))
        self.assertEqual(_page(text, 10, 12), ("cccc\ndddd", None))
        self.assertEqual(_page("abcdefghij", 0, 4), ("abcd", 4))  # no line break to use: cut at the limit


if __name__ == "__main__":
    unittest.main()
