"""Fetch Help Center pages politely and save raw extraction results.

Covers robots.txt, delay between requests, bounded retries (D10), article extraction, the crawl report,
and reruns that skip unchanged articles (D9b). Cleaning to Markdown is FR-2, not this module.

The user-agent contact is sent to the site but never written to our outputs.
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

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

HTTP_OK = 200
HTTP_CLIENT_ERROR_MIN = 400
HTTP_SERVER_ERROR_MIN = 500
HTTP_TOO_MANY_REQUESTS = 429
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0
BACKOFF_FACTOR = 2
ERROR_TEXT_LIMIT = 200
JSON_INDENT = 2

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_FAILED = "failed"


class FetchError(Exception):
    def __init__(self, url: str, reason: str, status: Optional[int] = None) -> None:
        super().__init__(f"{reason} ({url})")
        self.url = url
        self.reason = reason
        self.status = status


class TransientFetchError(FetchError):
    """A failure worth retrying: timeout, connection error, 5xx or 429."""


class CrawlAborted(Exception):
    """Raised when the crawl cannot run safely, for example robots.txt or the home page is unreachable."""


class RobotsDisallowed(Exception):
    pass


class ExtractionError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short(text: str) -> str:
    return text[:ERROR_TEXT_LIMIT]


def _is_transient(status: int) -> bool:
    return status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR_MIN


class PoliteFetcher:
    """HTTP GET with a minimum delay between requests and bounded retries on transient failures."""

    def __init__(
        self,
        user_agent: str,
        delay_seconds: float,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_SECONDS,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
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

    def get(self, url: str) -> requests.Response:
        """Return a 200 response. Retries transient failures; raises FetchError once they are exhausted."""
        for attempt in range(self.max_retries + 1):
            try:
                return self._request(url)
            except TransientFetchError as exc:
                if attempt == self.max_retries:
                    raise FetchError(url, exc.reason, exc.status) from exc
                wait = self.backoff_base * BACKOFF_FACTOR**attempt
                logger.warning("Transient failure (%s) on %s; retry %d in %.0fs", exc.reason, url, attempt + 1, wait)
                self.sleep(wait)
        raise AssertionError("unreachable: the loop always returns or raises")

    def _request(self, url: str) -> requests.Response:
        self._wait_turn()
        self._last_request_at = self.clock()
        self.requests_made += 1
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientFetchError(url, _short(f"{type(exc).__name__}: {exc}")) from exc
        except requests.RequestException as exc:
            raise FetchError(url, _short(f"{type(exc).__name__}: {exc}")) from exc
        if response.status_code == HTTP_OK:
            return response
        reason = f"HTTP {response.status_code}"
        if _is_transient(response.status_code):
            raise TransientFetchError(url, reason, response.status_code)
        raise FetchError(url, reason, response.status_code)

    def _wait_turn(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.delay_seconds - (self.clock() - self._last_request_at)
        if remaining > 0:
            self.sleep(remaining)


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
        if exc.status is not None and HTTP_CLIENT_ERROR_MIN <= exc.status < HTTP_SERVER_ERROR_MIN:
            parser.parse([])
            return Robots(parser)
        raise CrawlAborted(f"robots.txt unavailable, not crawling: {exc}") from exc
    parser.parse(response.text.splitlines())
    return Robots(parser)


def _apply_robots_delay(fetcher: PoliteFetcher, robots: Robots) -> None:
    if robots.crawl_delay:
        fetcher.delay_seconds = max(fetcher.delay_seconds, robots.crawl_delay)


def _fetch_allowed(fetcher: PoliteFetcher, robots: Robots, url: str) -> tuple[bytes, str]:
    """Return (body, final canonical URL after redirects) for a URL that robots.txt allows."""
    if not robots.allowed(url):
        raise RobotsDisallowed(f"disallowed by robots.txt ({url})")
    response = fetcher.get(url)
    return response.content, canonicalize(response.url)


# --- Extraction (raw only; cleaning is FR-2) ---------------------------------------------------------


def _media_type(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return "video_embed" if any(video in host for video in VIDEO_HOSTS) else "embed"


def _caption(element: Tag) -> Optional[str]:
    figure = element.find_parent("figure")
    figcaption = figure.find("figcaption") if figure else None
    if figcaption is not None:
        return figcaption.get_text(" ", strip=True) or None
    return element.get("alt") or None


def _video_source(video: Tag) -> Optional[str]:
    if video.get("src"):
        return video["src"]
    source = video.find("source")
    return source.get("src") if source else None


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
        src = _video_source(video)
        if src:
            media.append({"type": "video", "url": urljoin(page_url, src), "caption": _caption(video)})
    return media


def _article_title(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    title = heading.get_text(strip=True) if heading else ""
    if not title:
        raise ExtractionError("no article title (h1) found")
    return title


def _article_body(soup: BeautifulSoup) -> Tag:
    body = soup.select_one(".article_body")
    if body is None:
        raise ExtractionError("no article body (.article_body) found")
    return body


def _last_updated(html: bytes) -> Optional[str]:
    match = LAST_UPDATED.search(html.decode("utf-8", errors="replace"))
    return match.group(1) if match else None


def extract_article(html: bytes, page_url: str) -> dict:
    """Pull title, last-updated date, raw body text and media from an article page. Does not clean."""
    soup = BeautifulSoup(html, "html.parser")
    body = _article_body(soup)
    return {
        "title": _article_title(soup),
        "last_updated": _last_updated(html),
        "raw_text": body.get_text("\n", strip=True),
        "media": extract_media(body, page_url),
    }


# --- Storage -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CrawlPaths:
    html_dir: Path
    articles_jsonl: Path
    report: Path
    root: Path  # raw_html_path values are stored relative to this directory

    @classmethod
    def default(cls) -> "CrawlPaths":
        return cls(config.RAW_HTML_DIR, config.ARTICLES_JSONL, config.CRAWL_REPORT_PATH, config.ROOT_DIR)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: str | bytes) -> None:
    """Write to a temporary file, then rename, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, bytes):
        tmp.write_bytes(data)
    else:
        tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _load_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return {record["article_id"]: record for record in records}


def _save_records(path: Path, records: dict[str, dict]) -> None:
    ordered = sorted(records.values(), key=lambda record: int(record["article_id"]))
    write_atomic(path, "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in ordered))


def _store_raw(paths: CrawlPaths, article_id: str, html: bytes) -> dict:
    """Save the raw HTML file and return the fields that point to it."""
    html_path = paths.html_dir / f"{article_id}.html"
    write_atomic(html_path, html)
    return {
        "raw_html_path": html_path.relative_to(paths.root).as_posix(),
        "raw_html_sha256": _sha256(html),
    }


def _unchanged(prior: Optional[dict], lastmod: Optional[str], root: Path) -> bool:
    """Skip rule (D9b): prior success, sitemap lastmod equals stored last_updated, and raw file present."""
    if not prior or prior.get("scrape_status") != STATUS_SUCCESS or not lastmod:
        return False
    if prior.get("last_updated") != lastmod:
        return False
    return bool(prior.get("raw_html_path")) and (root / prior["raw_html_path"]).exists()


# --- Discovery ---------------------------------------------------------------------------------------


@dataclass
class Discovery:
    membership: dict[str, ArticleRef] = field(default_factory=dict)
    sources: dict[str, list[str]] = field(default_factory=dict)  # article_id -> collection names
    collections: list[dict] = field(default_factory=list)
    collection_errors: list[dict] = field(default_factory=list)


def _add_memberships(discovery: Discovery, refs: list[ArticleRef], name: str) -> None:
    for ref in refs:
        discovery.membership.setdefault(ref.article_id, ref)
        names = discovery.sources.setdefault(ref.article_id, [])
        if name not in names:
            names.append(name)


def _crawl_collection(
    fetcher: PoliteFetcher, robots: Robots, collection_url: str, discovery: Discovery
) -> dict:
    """Walk one collection's pages (following "next" links) and record its articles."""
    name: Optional[str] = None
    page_url: Optional[str] = collection_url
    visited: set[str] = set()
    article_ids: set[str] = set()
    while page_url and page_url not in visited:
        visited.add(page_url)
        try:
            html, final_url = _fetch_allowed(fetcher, robots, page_url)
        except (FetchError, RobotsDisallowed) as exc:
            discovery.collection_errors.append({"url": page_url, "error": str(exc)})
            break
        page = parse_collection_page(html, final_url)
        name = name or page.name or collection_url
        _add_memberships(discovery, page.articles, name)
        article_ids.update(ref.article_id for ref in page.articles)
        page_url = page.next_url
    return {
        "name": name,
        "url": collection_url,
        "pages_fetched": len(visited),
        "next_page_found": len(visited) > 1,
        "article_count": len(article_ids),
    }


def _fetch_home(fetcher: PoliteFetcher, robots: Robots) -> bytes:
    try:
        html, _ = _fetch_allowed(fetcher, robots, HOME_URL)
    except (FetchError, RobotsDisallowed) as exc:
        raise CrawlAborted(f"Help Center home page unavailable, nothing to discover: {exc}") from exc
    return html


def discover(fetcher: PoliteFetcher, robots: Robots) -> Discovery:
    discovery = Discovery()
    for collection_url in collection_urls_from_home(_fetch_home(fetcher, robots), HOME_URL):
        discovery.collections.append(_crawl_collection(fetcher, robots, collection_url, discovery))
    return discovery


def fetch_sitemap(fetcher: PoliteFetcher, robots: Robots) -> tuple[dict, dict]:
    """Return (article entries keyed by ID, report section). A failure is recorded, not raised."""
    url = (robots.sitemaps or [SITEMAP_FALLBACK_URL])[0]
    try:
        entries = parse_sitemap(fetcher.get(url).content)
    except (FetchError, ElementTree.ParseError) as exc:
        return {}, {"fetched": False, "article_count": 0, "error": str(exc)}
    return entries, {"fetched": True, "article_count": len(entries), "error": None}


# --- Per-article processing --------------------------------------------------------------------------


@dataclass(frozen=True)
class CrawlContext:
    fetcher: PoliteFetcher
    robots: Robots
    paths: CrawlPaths
    discovery: Discovery
    sitemap: dict
    existing: dict
    force: bool


def _first(names: list[str]) -> Optional[str]:
    return names[0] if names else None


def _success_record(
    article_id: str,
    url: str,
    final_url: str,
    lastmod: Optional[str],
    collections: list[str],
    saved: dict,
    fields: dict,
) -> dict:
    return {
        "article_id": article_id,
        "title": fields["title"],
        "url": url,
        "canonical_url": final_url,
        "collection": _first(collections),
        "collections": collections,
        "last_updated": fields["last_updated"],
        "sitemap_lastmod": lastmod,
        **saved,
        "raw_text": fields["raw_text"],
        "media": fields["media"],
        "scraped_at": now_iso(),
        "scrape_status": STATUS_SUCCESS,
        "error": None,
    }


def _failed_record(
    prior: Optional[dict],
    article_id: str,
    url: str,
    lastmod: Optional[str],
    collections: list[str],
    error: str,
    saved: dict,
) -> dict:
    """A failed record keeps the last good fields (if any) so no earlier data is lost."""
    return {
        **(prior or {}),
        **saved,
        "article_id": article_id,
        "url": url,
        "canonical_url": url,
        "collection": _first(collections),
        "collections": collections,
        "sitemap_lastmod": lastmod,
        "scraped_at": now_iso(),
        "scrape_status": STATUS_FAILED,
        "error": error,
    }


def _process_article(ctx: CrawlContext, article_id: str) -> tuple[dict, str]:
    """Fetch (or skip) one article and return its record and outcome."""
    prior = ctx.existing.get(article_id)
    sitemap_url, lastmod = ctx.sitemap.get(article_id, (None, None))
    url = sitemap_url or ctx.discovery.membership[article_id].url
    collections = ctx.discovery.sources.get(article_id) or (prior or {}).get("collections", [])

    if not ctx.force and _unchanged(prior, lastmod, ctx.paths.root):
        skipped = {**prior, "canonical_url": url, "collections": collections, "collection": _first(collections)}
        return skipped, OUTCOME_SKIPPED

    try:
        html, final_url = _fetch_allowed(ctx.fetcher, ctx.robots, url)
    except (FetchError, RobotsDisallowed) as exc:
        return _failed_record(prior, article_id, url, lastmod, collections, str(exc), {}), OUTCOME_FAILED

    saved = _store_raw(ctx.paths, article_id, html)  # kept even if extraction fails below
    try:
        fields = extract_article(html, final_url)
    except ExtractionError as exc:
        return _failed_record(prior, article_id, url, lastmod, collections, str(exc), saved), OUTCOME_FAILED
    return _success_record(article_id, url, final_url, lastmod, collections, saved, fields), OUTCOME_SUCCEEDED


# --- Report ------------------------------------------------------------------------------------------


def _cross_check(discovery: Discovery, sitemap: dict, discovered: list[str]) -> dict:
    """Compare collection membership with the sitemap (D1) and list articles that appear in several collections."""
    membership_ids = set(discovery.membership)
    sitemap_ids = set(sitemap)
    return {
        "only_in_collections": sorted(membership_ids - sitemap_ids, key=int),
        "only_in_sitemap": sorted(sitemap_ids - membership_ids, key=int),
        "multi_collection": [
            {"article_id": aid, "collections": discovery.sources[aid]}
            for aid in discovered
            if len(discovery.sources.get(aid, [])) > 1
        ],
    }


def _run_settings(started_at: str, fetcher: PoliteFetcher, robots: Robots, force: bool) -> dict:
    return {
        "started_at": started_at,
        "base_url": config.BASE_URL,
        "user_agent_product": config.USER_AGENT_PRODUCT,
        "delay_seconds": fetcher.delay_seconds,
        "robots_crawl_delay": robots.crawl_delay,
        "force": force,
    }


def _start_report(
    settings: dict,
    discovery: Discovery,
    sitemap: dict,
    sitemap_report: dict,
    discovered: list[str],
    existing: dict,
) -> dict:
    return {
        **settings,
        "collections": discovery.collections,
        "collection_errors": discovery.collection_errors,
        "sitemap": sitemap_report,
        "discovered": len(discovered),
        **_cross_check(discovery, sitemap, discovered),
        "new_since_last_run": [aid for aid in discovered if aid not in existing],
        "removed_since_last_run": sorted(set(existing) - set(discovered), key=int),
        "renamed": [],
        "unchanged_skipped": 0,
        "fetched_articles": 0,
        "succeeded": [],
        "failed": [],
    }


def _record_outcome(report: dict, outcome: str, article_id: str, prior: Optional[dict], record: dict) -> None:
    if outcome == OUTCOME_SKIPPED:
        report["unchanged_skipped"] += 1
    else:
        report["fetched_articles"] += 1
    if outcome == OUTCOME_SUCCEEDED:
        report["succeeded"].append(article_id)
    if outcome == OUTCOME_FAILED:
        report["failed"].append({"article_id": article_id, "url": record["url"], "error": record["error"]})
    if prior and prior.get("canonical_url") and prior["canonical_url"] != record["canonical_url"]:
        report["renamed"].append(
            {"article_id": article_id, "old": prior["canonical_url"], "new": record["canonical_url"]}
        )


def _finish_report(report: dict, fetcher: PoliteFetcher, records: dict, discovered: list[str], paths: CrawlPaths) -> dict:
    report["finished_at"] = now_iso()
    report["requests_made"] = fetcher.requests_made
    report["articles_with_media"] = sum(1 for aid in discovered if records[aid].get("media"))
    report["articles_with_null_last_updated"] = [
        aid
        for aid in discovered
        if records[aid].get("scrape_status") == STATUS_SUCCESS and not records[aid].get("last_updated")
    ]
    report["total_records"] = len(records)
    report["succeeded_count"] = len(report.pop("succeeded"))
    report["failed_count"] = len(report["failed"])
    write_atomic(paths.report, json.dumps(report, indent=JSON_INDENT, ensure_ascii=False) + "\n")
    return report


# --- Entry point -------------------------------------------------------------------------------------


def run_crawl(fetcher: PoliteFetcher, paths: CrawlPaths, *, force: bool = False) -> dict:
    """Discover, fetch, and save every Help Center article, then write the crawl report."""
    started_at = now_iso()
    robots = load_robots(fetcher)
    _apply_robots_delay(fetcher, robots)
    discovery = discover(fetcher, robots)
    sitemap, sitemap_report = fetch_sitemap(fetcher, robots)

    discovered = sorted(set(discovery.membership) | set(sitemap), key=int)
    existing = _load_records(paths.articles_jsonl)
    ctx = CrawlContext(fetcher, robots, paths, discovery, sitemap, existing, force)
    settings = _run_settings(started_at, fetcher, robots, force)
    report = _start_report(settings, discovery, sitemap, sitemap_report, discovered, existing)

    records = dict(existing)
    for index, article_id in enumerate(discovered, start=1):
        prior = existing.get(article_id)
        record, outcome = _process_article(ctx, article_id)
        _record_outcome(report, outcome, article_id, prior, record)
        records[article_id] = record
        logger.info("[%d/%d] %s %s", index, len(discovered), article_id, outcome)
        _save_records(paths.articles_jsonl, records)  # checkpoint after every article
    _save_records(paths.articles_jsonl, records)
    return _finish_report(report, fetcher, records, discovered, paths)
