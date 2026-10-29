"""Tests for FR-1 scraping. Uses saved fixtures and mocked HTTP; never calls the live site."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.robotparser import RobotFileParser

import requests

from iqm_rag.scraping.discovery import (
    article_id_from_url,
    canonicalize,
    collection_urls_from_home,
    parse_collection_page,
    parse_sitemap,
)
from iqm_rag.scraping.scraper import (
    CrawlPaths,
    ExtractionError,
    FetchError,
    PoliteFetcher,
    Robots,
    extract_article,
    run_crawl,
)

FIXTURES = Path(__file__).parent / "fixtures"
ARTICLE_URL = "https://help.iqm.com/en/articles/5651450-upload-an-image-creative"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class DiscoveryTests(unittest.TestCase):
    def test_article_id_ignores_slug(self):
        self.assertEqual(article_id_from_url("https://help.iqm.com/en/articles/5651450"), "5651450")
        self.assertEqual(article_id_from_url(ARTICLE_URL), "5651450")

    def test_canonicalize_drops_query_fragment_and_trailing_slash(self):
        self.assertEqual(canonicalize("http://help.iqm.com/en/articles/5651450-x/?a=1#top"),
                         "https://help.iqm.com/en/articles/5651450-x")

    def test_home_page_lists_eleven_unique_collections(self):
        urls = collection_urls_from_home(fixture("home.html"), "https://help.iqm.com/en")
        self.assertEqual(len(urls), 11)
        self.assertEqual(len(set(urls)), 11)
        self.assertTrue(all("/en/collections/" in url for url in urls))

    def test_collection_page_gives_name_and_unique_articles(self):
        page = parse_collection_page(fixture("collection_video_tutorials.html"),
                                     "https://help.iqm.com/en/collections/16890311-video-tutorials")
        self.assertEqual(page.name, "Video tutorials")
        ids = [ref.article_id for ref in page.articles]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(ids), 0)
        self.assertIsNone(page.next_url)  # no rel="next" link on this page

    def test_sitemap_contains_only_articles(self):
        entries = parse_sitemap(fixture("sitemap.xml"))
        self.assertEqual(len(entries), 200)
        self.assertIn("5651450", entries)
        url, lastmod = entries["5651450"]
        self.assertEqual(url, ARTICLE_URL)
        self.assertEqual(lastmod, "2026-03-17T19:25:46Z")


class ExtractionTests(unittest.TestCase):
    def test_extracts_title_date_text_and_media(self):
        fields = extract_article(fixture("article_upload_image_creative.html"), ARTICLE_URL)
        self.assertEqual(fields["title"], "Upload an image creative")
        self.assertEqual(fields["last_updated"], "2026-03-17T19:25:46Z")
        self.assertIn("Image creative overview", fields["raw_text"])
        types = {item["type"] for item in fields["media"]}
        self.assertIn("image", types)
        self.assertTrue(all(item["url"].startswith("http") for item in fields["media"]))

    def test_missing_body_is_an_extraction_error(self):
        with self.assertRaises(ExtractionError):
            extract_article(b"<html><h1>Title</h1><p>no body</p></html>", ARTICLE_URL)


class FetcherTests(unittest.TestCase):
    def _response(self, status: int, body: bytes = b"ok", url: str = ARTICLE_URL):
        response = requests.Response()
        response.status_code = status
        response._content = body
        response.url = url
        return response

    def _fetcher(self, responses):
        session = mock.Mock(spec=requests.Session)
        session.headers = {}
        session.get.side_effect = responses
        sleeps: list[float] = []
        fetcher = PoliteFetcher("test-agent", delay_seconds=2.0, session=session,
                                sleep=sleeps.append, clock=lambda: 1000.0, backoff_base=2.0)
        return fetcher, session, sleeps

    def test_retries_5xx_then_succeeds_with_backoff(self):
        fetcher, session, sleeps = self._fetcher([self._response(503), self._response(200)])
        self.assertEqual(fetcher.get(ARTICLE_URL).status_code, 200)
        self.assertEqual(session.get.call_count, 2)
        self.assertIn(2.0, sleeps)  # backoff before retry 1

    def test_gives_up_after_bounded_retries(self):
        fetcher, session, _ = self._fetcher([self._response(429)] * 4)
        with self.assertRaises(FetchError) as ctx:
            fetcher.get(ARTICLE_URL)
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(session.get.call_count, 4)  # 1 try + 3 retries

    def test_404_is_not_retried(self):
        fetcher, session, _ = self._fetcher([self._response(404)])
        with self.assertRaises(FetchError):
            fetcher.get(ARTICLE_URL)
        self.assertEqual(session.get.call_count, 1)

    def test_enforces_delay_between_requests(self):
        clock_values = iter([1000.0, 1000.5, 1000.5])  # start of request 1; wait check and start of request 2
        session = mock.Mock(spec=requests.Session)
        session.headers = {}
        session.get.side_effect = [self._response(200), self._response(200)]
        sleeps: list[float] = []
        fetcher = PoliteFetcher("test-agent", delay_seconds=2.0, session=session,
                                sleep=sleeps.append, clock=lambda: next(clock_values))
        fetcher.get(ARTICLE_URL)
        fetcher.get(ARTICLE_URL)
        self.assertEqual(sleeps, [1.5])  # 2.0s minimum minus 0.5s already elapsed


class RerunTests(unittest.TestCase):
    """End-to-end run against mocked HTTP and a temporary data directory."""

    def _routes(self, article_html: bytes):
        robots = b"User-agent: *\nDisallow: /not-found\nCrawl-delay: 1\n"
        collection = fixture("collection_video_tutorials.html")
        home = fixture("home.html")
        sitemap = fixture("sitemap.xml")

        lastmods = {aid: lastmod for aid, (_, lastmod) in parse_sitemap(sitemap).items()}

        def get(url, **_):
            if url.endswith("robots.txt"):
                return self._resp(url, robots)
            if url.endswith("sitemap.xml"):
                return self._resp(url, sitemap)
            if url == "https://help.iqm.com/en":
                return self._resp(url, home)
            if "/collections/" in url:
                return self._resp(url, collection)
            if "/articles/" in url:
                # Give each article the date its sitemap entry says, as the live site does.
                article_id = article_id_from_url(url)
                body = article_html.replace(b"2026-03-17T19:25:46Z", lastmods[article_id].encode())
                return self._resp(url, body)
            return self._resp(url, b"", status=404)

        session = mock.Mock(spec=requests.Session)
        session.headers = {}
        session.get.side_effect = get
        return session

    def _resp(self, url, body, status=200):
        response = requests.Response()
        response.status_code = status
        response._content = body
        response.url = url
        return response

    def _paths(self, root: Path) -> CrawlPaths:
        return CrawlPaths(root / "html", root / "articles.jsonl", root / "crawl_report.json", root)

    def test_first_run_then_rerun_skips_unchanged(self):
        article = fixture("article_upload_image_creative.html")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            session = self._routes(article)
            fetcher = PoliteFetcher("test-agent", delay_seconds=0.0, session=session,
                                    sleep=lambda _: None, clock=lambda: 0.0)
            first = run_crawl(fetcher, paths)
            self.assertEqual(first["failed_count"], 0)
            self.assertGreater(first["succeeded_count"], 0)
            self.assertEqual(first["sitemap"]["article_count"], 200)
            self.assertEqual(first["robots_crawl_delay"], 1.0)
            self.assertEqual(fetcher.delay_seconds, 1.0)  # starts at 0.0, raised to robots' Crawl-delay

            records = [json.loads(line) for line in paths.articles_jsonl.read_text().splitlines()]
            self.assertEqual(len(records), first["total_records"])
            sample = next(r for r in records if r["article_id"] == "5651450")
            self.assertTrue((root / sample["raw_html_path"]).exists())
            self.assertEqual(sample["scrape_status"], "success")

            second_session = self._routes(article)
            second_fetcher = PoliteFetcher("test-agent", delay_seconds=0.0, session=second_session,
                                           sleep=lambda _: None, clock=lambda: 0.0)
            second = run_crawl(second_fetcher, paths)
            self.assertEqual(second["unchanged_skipped"], first["succeeded_count"])
            self.assertEqual(second["fetched_articles"], 0)
            self.assertEqual(second["failed_count"], 0)

    def test_failed_article_is_reported_not_dropped(self):
        broken = b"<html><h1>Title</h1><p>no article body here</p></html>"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            session = self._routes(broken)
            fetcher = PoliteFetcher("test-agent", delay_seconds=0.0, session=session,
                                    sleep=lambda _: None, clock=lambda: 0.0)
            report = run_crawl(fetcher, paths)
            self.assertEqual(report["succeeded_count"], 0)
            self.assertGreater(report["failed_count"], 0)
            failure = report["failed"][0]
            self.assertIn("no article body", failure["error"])
            record = next(json.loads(line) for line in paths.articles_jsonl.read_text().splitlines()
                          if json.loads(line)["article_id"] == failure["article_id"])
            self.assertEqual(record["scrape_status"], "failed")
            self.assertTrue((root / record["raw_html_path"]).exists())  # raw copy kept for debugging


class RobotsTests(unittest.TestCase):
    def test_disallowed_path_is_blocked(self):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /not-found"])
        robots = Robots(parser)
        self.assertFalse(robots.allowed("https://help.iqm.com/not-found"))
        self.assertTrue(robots.allowed(ARTICLE_URL))


if __name__ == "__main__":
    unittest.main()
