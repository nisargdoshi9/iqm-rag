"""Fetch Help Center pages politely and save raw extraction results.

Covers robots.txt, delay between requests, bounded retries (D10), article extraction, the crawl report,
and reruns that skip unchanged articles (D9b). Cleaning to Markdown is FR-2, not this module.
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

from iqm_rag import config
from iqm_rag.scraping.discovery import (
    ArticleRef,
    canonicalize,
    collection_urls_from_home,
    parse_collection_page,
    parse_sitemap,
)

logger = logging.getLogger(__name__)

HOME_URL = config.BASE_URL
ROBOTS_URL = "https://help.iqm.com/robots.txt"
SITEMAP_FALLBACK_URL = "https://help.iqm.com/sitemap.xml"
LAST_UPDATED = re.compile(r'"lastUpdatedDate":"([^"]+)"')
VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")


class FetchError(Exception):
    def __init__(self, url: str, reason: str, status: Optional[int] = None):
        super().__init__(f"{reason} ({url})")
        self.url = url
        self.reason = reason
        self.status = status


class CrawlAborted(Exception):
    """Raised when the crawl cannot run safely, for example robots.txt is unreachable."""


class RobotsDisallowed(Exception):
    pass


class ExtractionError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PoliteFetcher:
    """HTTP GET with a minimum delay between requests and bounded retries on transient failures."""

    def __init__(
        self,
        user_agent: str,
        delay_seconds: float,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sleep = sleep
        self.clock = clock
        self.requests_made = 0
        self._last_request_at: Optional[float] = None

    def _wait_turn(self) -> None:
        if self._last_request_at is not None:
            remaining = self.delay_seconds - (self.clock() - self._last_request_at)
            if remaining > 0:
                self.sleep(remaining)

    def get(self, url: str) -> requests.Response:
        """Return a 200 response. Retries timeouts, connection errors, 5xx and 429; raises FetchError otherwise."""
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            self._last_request_at = self.clock()
            self.requests_made += 1
            status: Optional[int] = None
            try:
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except (requests.Timeout, requests.ConnectionError) as exc:
                reason = f"{type(exc).__name__}: {str(exc)[:200]}"
                retryable = True
            else:
                if response.status_code == 200:
                    return response
                status = response.status_code
                reason = f"HTTP {status}"
                retryable = status >= 500 or status == 429

            if not retryable or attempt == self.max_retries:
                raise FetchError(url, reason, status)
            wait = self.backoff_base * (2**attempt)
            logger.warning("Transient failure (%s) on %s; retry %d in %.0fs", reason, url, attempt + 1, wait)
            self.sleep(wait)
        raise AssertionError("unreachable")


@dataclass
class Robots:
    parser: RobotFileParser

    def allowed(self, url: str) -> bool:
        return self.parser.can_fetch(config.USER_AGENT_PRODUCT, url)

    @property
    def crawl_delay(self) -> Optional[float]:
        value = self.parser.crawl_delay(config.USER_AGENT_PRODUCT)
        return float(value) if value is not None else None

    @property
    def sitemaps(self) -> list[str]:
        return list(self.parser.site_maps() or [])


def load_robots(fetcher: PoliteFetcher) -> Robots:
    """Fetch and parse robots.txt. A 4xx means no restrictions; any other failure aborts the crawl."""
    parser = RobotFileParser()
    try:
        response = fetcher.get(ROBOTS_URL)
    except FetchError as exc:
        if exc.status is not None and 400 <= exc.status < 500:
            parser.parse([])
            return Robots(parser)
        raise CrawlAborted(f"robots.txt unavailable, not crawling: {exc}") from exc
    parser.parse(response.text.splitlines())
    return Robots(parser)


def _fetch_allowed(fetcher: PoliteFetcher, robots: Robots, url: str) -> tuple[bytes, str]:
    """Return (body, final canonical URL after redirects) for a URL that robots.txt allows."""
    if not robots.allowed(url):
        raise RobotsDisallowed(f"disallowed by robots.txt ({url})")
    response = fetcher.get(url)
    return response.content, canonicalize(response.url)


def _media_type(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return "video_embed" if any(video in host for video in VIDEO_HOSTS) else "embed"


def _caption(element: Tag) -> Optional[str]:
    figure = element.find_parent("figure")
    if figure and figure.find("figcaption"):
        return figure.find("figcaption").get_text(" ", strip=True) or None
    return element.get("alt") or None


def extract_media(body: Tag, page_url: str) -> list[dict]:
    media: list[dict] = []
    for img in body.find_all("img"):
        if img.get("src"):
            media.append({"type": "image", "url": urljoin(page_url, img["src"]), "caption": _caption(img)})
    for frame in body.find_all("iframe"):
        if frame.get("src"):
            url = urljoin(page_url, frame["src"])
            media.append({"type": _media_type(url), "url": url, "caption": _caption(frame)})
    for video in body.find_all("video"):
        src = video.get("src") or (video.find("source") or {}).get("src")
        if src:
            media.append({"type": "video", "url": urljoin(page_url, src), "caption": _caption(video)})
    return media


def extract_article(html: bytes, page_url: str) -> dict:
    """Pull title, last-updated date, raw body text and media from an article page. Does not clean."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    title = heading.get_text(strip=True) if heading else ""
    if not title:
        raise ExtractionError("no article title (h1) found")
    body = soup.select_one(".article_body")
    if body is None:
        raise ExtractionError("no article body (.article_body) found")

    match = LAST_UPDATED.search(html.decode("utf-8", errors="replace"))
    return {
        "title": title,
        "last_updated": match.group(1) if match else None,
        "raw_text": body.get_text("\n", strip=True),
        "media": extract_media(body, page_url),
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CrawlPaths:
    html_dir: Path
    articles_jsonl: Path
    report: Path
    root: Path  # raw_html_path values are stored relative to this directory

    @classmethod
    def default(cls) -> "CrawlPaths":
        return cls(config.RAW_HTML_DIR, config.ARTICLES_JSONL, config.CRAWL_REPORT_PATH, config.ROOT_DIR)


def _load_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return {record["article_id"]: record for record in records}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _save_records(path: Path, records: dict[str, dict]) -> None:
    ordered = sorted(records.values(), key=lambda record: int(record["article_id"]))
    _write_atomic(path, "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in ordered))


def _unchanged(prior: Optional[dict], lastmod: Optional[str], root: Path) -> bool:
    """Skip rule (D9b): prior success, sitemap lastmod equals stored last_updated, and raw file present."""
    if not prior or prior.get("scrape_status") != "success" or not lastmod:
        return False
    if prior.get("last_updated") != lastmod:
        return False
    return bool(prior.get("raw_html_path")) and (root / prior["raw_html_path"]).exists()


def run_crawl(fetcher: PoliteFetcher, paths: CrawlPaths, *, force: bool = False) -> dict:
    """Discover, fetch, and save every Help Center article, then write the crawl report."""
    started_at = now_iso()
    robots = load_robots(fetcher)
    if robots.crawl_delay:
        fetcher.delay_seconds = max(fetcher.delay_seconds, robots.crawl_delay)

    # Discovery: collection pages give membership (D1), following "next" links if any.
    try:
        home_html, _ = _fetch_allowed(fetcher, robots, HOME_URL)
    except (FetchError, RobotsDisallowed) as exc:
        raise CrawlAborted(f"Help Center home page unavailable, nothing to discover: {exc}") from exc
    membership: dict[str, ArticleRef] = {}
    sources: dict[str, list[str]] = {}
    collections_report: list[dict] = []
    collection_errors: list[dict] = []
    for collection_url in collection_urls_from_home(home_html, HOME_URL):
        page_url: Optional[str] = collection_url
        visited: set[str] = set()
        name = None
        pages = 0
        while page_url and page_url not in visited:
            visited.add(page_url)
            pages += 1
            try:
                html, final_url = _fetch_allowed(fetcher, robots, page_url)
            except (FetchError, RobotsDisallowed) as exc:
                collection_errors.append({"url": page_url, "error": str(exc)})
                break
            page = parse_collection_page(html, final_url)
            name = name or page.name or collection_url
            for ref in page.articles:
                membership.setdefault(ref.article_id, ref)
                sources.setdefault(ref.article_id, [])
                if name not in sources[ref.article_id]:
                    sources[ref.article_id].append(name)
            page_url = page.next_url
        collections_report.append(
            {
                "name": name,
                "url": collection_url,
                "pages_fetched": pages,
                "next_page_found": pages > 1,
                "article_count": sum(1 for ids in sources.values() if name in ids),
            }
        )

    # Cross-check against the sitemap (D1) and read lastmod for the rerun rule (D9b).
    sitemap_report: dict = {"fetched": False, "article_count": 0, "error": None}
    sitemap: dict[str, tuple[str, Optional[str]]] = {}
    sitemap_url = (robots.sitemaps or [SITEMAP_FALLBACK_URL])[0]
    try:
        sitemap = parse_sitemap(fetcher.get(sitemap_url).content)
        sitemap_report.update(fetched=True, article_count=len(sitemap))
    except (FetchError, ValueError) as exc:
        sitemap_report["error"] = str(exc)

    discovered = sorted(set(membership) | set(sitemap), key=int)
    existing = _load_records(paths.articles_jsonl)
    records = dict(existing)
    report = {
        "started_at": started_at,
        "base_url": config.BASE_URL,
        "user_agent": fetcher.session.headers.get("User-Agent"),
        "delay_seconds": fetcher.delay_seconds,
        "robots_crawl_delay": robots.crawl_delay,
        "force": force,
        "collections": collections_report,
        "collection_errors": collection_errors,
        "sitemap": sitemap_report,
        "discovered": len(discovered),
        "only_in_collections": sorted(set(membership) - set(sitemap), key=int),
        "only_in_sitemap": sorted(set(sitemap) - set(membership), key=int),
        "multi_collection": [
            {"article_id": aid, "collections": sources[aid]} for aid in discovered if len(sources.get(aid, [])) > 1
        ],
        "new_since_last_run": [aid for aid in discovered if aid not in existing],
        "removed_since_last_run": sorted(set(existing) - set(discovered), key=int),
        "renamed": [],
        "unchanged_skipped": 0,
        "fetched_articles": 0,
        "succeeded": [],
        "failed": [],
    }

    for index, article_id in enumerate(discovered, start=1):
        prior = existing.get(article_id)
        sitemap_url_for_article, lastmod = sitemap.get(article_id, (None, None))
        url = sitemap_url_for_article or membership[article_id].url
        collections = sources.get(article_id) or (prior or {}).get("collections", [])

        if not force and _unchanged(prior, lastmod, paths.root):
            if prior["canonical_url"] != url:
                report["renamed"].append({"article_id": article_id, "old": prior["canonical_url"], "new": url})
            records[article_id] = {**prior, "canonical_url": url, "collections": collections,
                                   "collection": collections[0] if collections else None}
            report["unchanged_skipped"] += 1
            logger.info("[%d/%d] %s unchanged, skipped", index, len(discovered), article_id)
            continue

        report["fetched_articles"] += 1
        saved: dict = {}  # raw file details, kept even when extraction fails
        try:
            html, final_url = _fetch_allowed(fetcher, robots, url)
            # Save raw HTML before extraction, so a failed extraction still keeps the raw copy.
            html_path = paths.html_dir / f"{article_id}.html"
            _write_atomic_bytes(html_path, html)
            saved = {
                "raw_html_path": html_path.relative_to(paths.root).as_posix(),
                "raw_html_sha256": _sha256(html),
            }
            fields = extract_article(html, final_url)
            record = {
                "article_id": article_id,
                "title": fields["title"],
                "url": url,
                "canonical_url": final_url,
                "collection": collections[0] if collections else None,
                "collections": collections,
                "last_updated": fields["last_updated"],
                "sitemap_lastmod": lastmod,
                **saved,
                "raw_text": fields["raw_text"],
                "media": fields["media"],
                "scraped_at": now_iso(),
                "scrape_status": "success",
                "error": None,
            }
            report["succeeded"].append(article_id)
            logger.info("[%d/%d] %s ok: %s", index, len(discovered), article_id, fields["title"])
        except (FetchError, RobotsDisallowed, ExtractionError) as exc:
            record = {
                **(prior or {}),
                "article_id": article_id,
                "url": url,
                "canonical_url": url,
                "collection": collections[0] if collections else None,
                "collections": collections,
                "sitemap_lastmod": lastmod,
                **saved,
                "scraped_at": now_iso(),
                "scrape_status": "failed",
                "error": str(exc),
            }
            report["failed"].append({"article_id": article_id, "url": url, "error": str(exc)})
            logger.error("[%d/%d] %s failed: %s", index, len(discovered), article_id, exc)

        if prior and prior.get("canonical_url") and prior["canonical_url"] != record["canonical_url"]:
            report["renamed"].append(
                {"article_id": article_id, "old": prior["canonical_url"], "new": record["canonical_url"]}
            )
        records[article_id] = record
        _save_records(paths.articles_jsonl, records)  # checkpoint after every article

    _save_records(paths.articles_jsonl, records)
    report["finished_at"] = now_iso()
    report["requests_made"] = fetcher.requests_made
    report["articles_with_media"] = sum(1 for aid in discovered if records[aid].get("media"))
    report["articles_with_null_last_updated"] = [
        aid for aid in discovered if records[aid].get("scrape_status") == "success" and not records[aid].get("last_updated")
    ]
    report["total_records"] = len(records)
    report["succeeded_count"] = len(report.pop("succeeded"))
    report["failed_count"] = len(report["failed"])
    _write_atomic(paths.report, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def _write_atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
