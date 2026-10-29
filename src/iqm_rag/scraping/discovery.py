"""Discover collections and articles on help.iqm.com.

Two sources are used (decision D1): collection pages give membership, and the sitemap is a cross-check.
Article identity is the numeric ID in the URL (decision D6); the slug may change.
"""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

ARTICLE_PATH = re.compile(r"^/en/articles/(\d+)(?:-[^/]*)?$")
COLLECTION_PATH = re.compile(r"^/en/collections/(\d+)(?:-[^/]*)?$")


@dataclass(frozen=True)
class ArticleRef:
    article_id: str
    url: str  # canonical: https, no query, no fragment, no trailing slash


@dataclass(frozen=True)
class CollectionPage:
    name: str
    articles: list[ArticleRef]
    next_url: Optional[str]


def canonicalize(url: str) -> str:
    """Normalise a Help Center URL: https scheme, no query, fragment or trailing slash."""
    parts = urlsplit(url)
    return f"https://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def article_id_from_url(url: str) -> Optional[str]:
    match = ARTICLE_PATH.match(urlsplit(url).path)
    return match.group(1) if match else None


def article_ref(url: str) -> Optional[ArticleRef]:
    article_id = article_id_from_url(url)
    return ArticleRef(article_id, canonicalize(url)) if article_id else None


def collection_urls_from_home(html: bytes, base_url: str) -> list[str]:
    """Return unique canonical collection URLs linked from the Help Center home page, in page order."""
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, None] = {}
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(base_url, anchor["href"])
        if COLLECTION_PATH.match(urlsplit(absolute).path):
            seen[canonicalize(absolute)] = None
    return list(seen)


def parse_collection_page(html: bytes, page_url: str) -> CollectionPage:
    """Return the collection name, its unique articles, and the next page URL if one is linked."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    name = heading.get_text(strip=True) if heading else ""

    articles: dict[str, ArticleRef] = {}
    for anchor in soup.find_all("a", href=True):
        ref = article_ref(urljoin(page_url, anchor["href"]))
        if ref:
            articles.setdefault(ref.article_id, ref)

    next_link = soup.find("link", rel="next") or soup.find("a", rel="next")
    next_url = canonicalize(urljoin(page_url, next_link["href"])) if next_link and next_link.get("href") else None
    return CollectionPage(name=name, articles=list(articles.values()), next_url=next_url)


def parse_sitemap(xml_bytes: bytes) -> dict[str, tuple[str, Optional[str]]]:
    """Return {article_id: (canonical_url, lastmod)} for article URLs only. Collection pages are ignored."""
    root = ElementTree.fromstring(xml_bytes)
    result: dict[str, tuple[str, Optional[str]]] = {}
    for entry in root.findall("{*}url"):
        loc = entry.findtext("{*}loc")
        lastmod = entry.findtext("{*}lastmod")
        ref = article_ref(loc.strip()) if loc else None
        if ref:
            result[ref.article_id] = (ref.url, lastmod.strip() if lastmod else None)
    return result
