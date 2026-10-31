"""Tests for the incremental update: a fake site, temporary data folders and a topic embedder. No network, no API calls."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (keeps tracing off in tests)
from iqm_rag.ingestion.indexing import open_index
from iqm_rag.scraping.discovery import parse_sitemap
from iqm_rag.scraping.normalization import ProcessedPaths, read_jsonl
from iqm_rag.scraping.scraper import CrawlPaths, PoliteFetcher, _removal_decision
from iqm_rag.update import UpdatePaths, chunk_changes, describe, describe_plan, plan_update, run_update
from test_retrieval import TopicEmbedder
from test_scraping import RerunTests, fixture

CHANGED, REMOVED = "5651450", "5651452"  # in the sitemap but not on the saved collection page, so the sitemap alone controls them
PHRASE = b"Advertisers rely on image creatives"
EXTRA_ARTICLES = 12  # besides the articles the saved collection page lists and the two above; keeps each update fast


def small_sitemap() -> str:
    """The saved sitemap cut to a few dozen articles: those on the saved collection page, the two the tests edit or remove, and a few more."""
    xml, collection = fixture("sitemap.xml").decode(), fixture("collection_video_tutorials.html").decode()
    ids = list(parse_sitemap(xml.encode()))
    keep = {i for i in ids if f"/articles/{i}-" in collection} | {CHANGED, REMOVED} | set(ids[:EXTRA_ARTICLES])
    for article_id in ids:
        if article_id not in keep:
            xml = re.sub(rf"\s*<url>\s*<loc>[^<]*/articles/{article_id}-[^<]*</loc>\s*<lastmod>[^<]*</lastmod>\s*</url>", "", xml)
    return xml


def lastmod_pattern(article_id: str) -> str:
    return rf"(<loc>[^<]*/articles/{article_id}-[^<]*</loc>\s*<lastmod>)[^<]*(</lastmod>)"


class UpdateTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        crawl = CrawlPaths(root / "raw" / "html", root / "raw" / "articles.jsonl", root / "raw" / "crawl_report.json", root)
        processed = ProcessedPaths(crawl.articles_jsonl, root, root / "processed" / "articles.jsonl", root / "processed" / "media.jsonl",
                                   root / "processed" / "audit.jsonl", root / "processed" / "report.json")
        self.paths = UpdatePaths(crawl, processed, root / "chunks" / "chunks.jsonl", root / "chunks" / "report.json", root / "index")
        self.site, self.article, self.embedder = RerunTests(), fixture("article_upload_image_creative.html"), TopicEmbedder()
        self.requested: list[str] = []
        self.base_sitemap = small_sitemap()
        self.total = len(parse_sitemap(self.base_sitemap.encode()))

    def fetcher(self, sitemap: str = None, edited=(), failing=()):
        """A polite fetcher over the fake site, with an optional replacement sitemap, edited article text and articles that fail."""
        session = self.site._routes(self.article)
        inner = session.get.side_effect

        def get(url, **kwargs):
            self.requested.append(url)
            if url.endswith("sitemap.xml"):
                return self.site._resp(url, (sitemap or self.base_sitemap).encode())
            if any(f"/articles/{i}-" in url for i in failing):
                return self.site._resp(url, b"", status=500)
            response = inner(url, **kwargs)
            if any(f"/articles/{i}-" in url for i in edited):
                response._content = response._content.replace(PHRASE, b"Advertisers depend on image creatives")
            return response

        session.get.side_effect = get
        return PoliteFetcher("test-agent", delay_seconds=0.0, session=session, sleep=lambda _: None, clock=lambda: 0.0)

    def update(self, **kwargs) -> dict:
        fetcher = None if kwargs.pop("skip_scrape", False) else self.fetcher(**{k: kwargs.pop(k) for k in ("sitemap", "edited", "failing") if k in kwargs})
        return run_update(fetcher, self.embedder, self.paths, skip_scrape=fetcher is None, **kwargs)

    def sitemap(self, drop=(), new_lastmod=None) -> str:
        xml = self.base_sitemap
        for article_id in drop:
            xml = re.sub(rf"\s*<url>\s*<loc>[^<]*/articles/{article_id}-[^<]*</loc>\s*<lastmod>[^<]*</lastmod>\s*</url>", "", xml)
        for article_id, value in (new_lastmod or {}).items():
            xml = re.sub(lastmod_pattern(article_id), rf"\g<1>{value}\g<2>", xml)
        return xml

    def index_ids(self) -> set:
        return set(open_index(self.paths.index, self.embedder.model).get()["ids"])

    def chunk_ids(self) -> set:
        return {chunk["chunk_id"] for chunk in read_jsonl(self.paths.chunks)}


class FirstAndRepeatUpdateTests(UpdateTestCase):
    def test_the_first_update_builds_the_dataset_the_chunks_and_the_index(self):
        summary = self.update()
        self.assertEqual(summary["status"], "updated")
        self.assertEqual(summary["scrape"]["new"], self.total)
        self.assertEqual(summary["clean"]["articles"], self.total)
        self.assertEqual(summary["index"]["added"], summary["chunks"]["total"])
        self.assertEqual(self.index_ids(), self.chunk_ids())

    def test_an_update_with_nothing_changed_fetches_and_embeds_nothing(self):
        self.update()
        self.embedder.calls.clear()
        self.requested.clear()
        summary = self.update()
        self.assertEqual((summary["scrape"]["new"], summary["scrape"]["changed"], summary["scrape"]["unchanged"], summary["scrape"]["removed"]), (0, 0, self.total, []))
        self.assertEqual(summary["chunks"], {**summary["chunks"], "added": 0, "changed": 0, "removed": 0})
        self.assertEqual({k: summary["index"][k] for k in ("added", "updated", "deleted")}, {"added": 0, "updated": 0, "deleted": 0})
        self.assertEqual(self.embedder.calls, [])
        self.assertFalse([url for url in self.requested if "/articles/" in url])

    def test_skipping_the_scrape_rebuilds_from_the_data_on_disk(self):
        self.update()
        summary = self.update(skip_scrape=True)
        self.assertNotIn("scrape", summary)
        self.assertEqual((summary["status"], summary["index"]["added"], summary["index"]["deleted"]), ("updated", 0, 0))


class ChangedAndRemovedTests(UpdateTestCase):
    def test_a_changed_article_updates_only_its_own_chunks(self):
        self.update()
        self.embedder.calls.clear()
        summary = self.update(sitemap=self.sitemap(new_lastmod={CHANGED: "2027-01-01T00:00:00Z"}), edited=[CHANGED])
        self.assertEqual((summary["scrape"]["changed"], summary["scrape"]["new"], summary["scrape"]["unchanged"]), (1, 0, self.total - 1))
        self.assertGreaterEqual(summary["chunks"]["changed"], 1)
        self.assertEqual((summary["chunks"]["added"], summary["chunks"]["removed"]), (0, 0))
        self.assertEqual(summary["index"]["updated"], summary["chunks"]["changed"])
        self.assertEqual(sum(len(batch) for batch in self.embedder.calls), summary["chunks"]["changed"])

    def test_an_article_removed_from_the_site_leaves_the_data_the_chunks_and_the_index(self):
        self.update()
        raw = next(r for r in read_jsonl(self.paths.crawl.articles_jsonl) if r["article_id"] == REMOVED)
        raw_file = self.paths.crawl.root / raw["raw_html_path"]
        self.assertTrue(raw_file.exists())
        summary = self.update(sitemap=self.sitemap(drop=[REMOVED]))
        self.assertEqual(summary["scrape"]["removed"], [REMOVED])
        self.assertFalse(raw_file.exists())
        for path in (self.paths.crawl.articles_jsonl, self.paths.processed.articles):
            self.assertNotIn(REMOVED, {r["article_id"] for r in read_jsonl(path)})
        self.assertGreater(summary["chunks"]["removed"], 0)
        self.assertEqual(summary["index"]["deleted"], summary["chunks"]["removed"])
        self.assertEqual(self.index_ids(), self.chunk_ids())
        self.assertFalse(any(chunk_id.startswith(f"{REMOVED}:") for chunk_id in self.index_ids()))


class FailureTests(UpdateTestCase):
    def test_a_failed_download_stops_the_update_before_anything_is_removed_and_a_rerun_recovers(self):
        self.update()
        chunks_before, index_before = self.paths.chunks.read_text(), self.index_ids()
        self.embedder.calls.clear()
        stale = self.sitemap(new_lastmod={CHANGED: "2027-01-01T00:00:00Z"})
        summary = self.update(sitemap=stale, failing=[CHANGED])
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(len(summary["scrape"]["failed"]), 1)
        self.assertEqual((self.paths.chunks.read_text(), self.index_ids(), self.embedder.calls), (chunks_before, index_before, []))
        recovered = self.update(sitemap=stale)
        self.assertEqual((recovered["status"], recovered["scrape"]["changed"], recovered["scrape"]["failed"]), ("updated", 1, []))
        self.assertEqual(self.index_ids(), index_before)


class RemovalGuardTests(unittest.TestCase):
    @staticmethod
    def stored(n: int) -> dict:
        return {str(i): {} for i in range(1, n + 1)}

    def decide(self, existing: dict, found: int, collection_errors=(), sitemap_ok=True):
        discovery = mock.Mock(collection_errors=list(collection_errors))
        return _removal_decision(existing, [str(i) for i in range(1, found + 1)], discovery, {"fetched": sitemap_ok})

    def test_a_healthy_crawl_drops_what_is_missing(self):
        self.assertEqual(self.decide(self.stored(100), 98), (["99", "100"], None))
        self.assertEqual(self.decide(self.stored(100), 100), ([], None))

    def test_nothing_is_dropped_when_the_crawl_looks_incomplete(self):
        for kwargs in ({"collection_errors": ["boom"]}, {"sitemap_ok": False}):
            gone, reason = self.decide(self.stored(100), 98, **kwargs)
            self.assertEqual((gone, bool(reason)), ([], True))
        gone, reason = self.decide(self.stored(100), 50)
        self.assertEqual((gone, "50 of 100" in reason), ([], True))


class PlanTests(UpdateTestCase):
    def test_the_plan_lists_new_changed_and_removed_articles_without_fetching_or_writing(self):
        self.update()
        before = self.paths.crawl.articles_jsonl.read_text()
        self.requested.clear()
        sitemap = self.sitemap(drop=[REMOVED], new_lastmod={CHANGED: "2027-01-01T00:00:00Z"})
        plan = plan_update(self.fetcher(sitemap=sitemap), self.paths)
        self.assertEqual((plan["new"], plan["refetch"], plan["removed"], plan["unchanged"]), ([], [CHANGED], [REMOVED], self.total - 2))
        self.assertFalse([url for url in self.requested if "/articles/" in url])
        self.assertEqual(self.paths.crawl.articles_jsonl.read_text(), before)


class SummaryTests(unittest.TestCase):
    def test_chunk_changes_counts_added_changed_and_removed(self):
        self.assertEqual(chunk_changes({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "9", "d": "4"}),
                         {"total": 3, "added": 1, "removed": 1, "changed": 1})

    def test_the_readable_summaries_carry_the_numbers_and_the_stop_reason(self):
        summary = {"status": "stopped", "reason": "1 article(s) failed", "scrape": {"discovered": 200, "new": 1, "changed": 2, "unchanged": 197, "removed": ["9"],
                   "failed": [{}], "removal_skipped_reason": None, "requests": 12}}
        text = describe(summary)
        for part in ("200 articles found", "1 new, 2 changed, 197 unchanged", "1 removed", "stopped (1 article(s) failed)"):
            self.assertIn(part, text)
        plan = {"requests_made": 12, "discovered": 200, "new": ["1"], "refetch": [], "unchanged": 199, "removed": [], "removal_skipped_reason": "errors"}
        self.assertIn("would NOT be applied", describe_plan(plan))


if __name__ == "__main__":
    unittest.main()
