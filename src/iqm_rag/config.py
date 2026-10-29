"""Central configuration: data paths and settings read from environment variables.

Values come from the process environment. Export them, or load `.env` before running.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_HTML_DIR = RAW_DIR / "html"
ARTICLES_JSONL = RAW_DIR / "articles.jsonl"
CRAWL_REPORT_PATH = RAW_DIR / "crawl_report.json"
PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_ARTICLES_JSONL = PROCESSED_DIR / "articles.jsonl"
MEDIA_JSONL = PROCESSED_DIR / "media.jsonl"
TABLE_AUDIT_JSONL = PROCESSED_DIR / "table_audit.jsonl"
CLEANING_REPORT_PATH = PROCESSED_DIR / "cleaning_report.json"
CHUNKS_DIR = DATA_DIR / "chunks"
EVALUATION_DIR = DATA_DIR / "evaluation"

BASE_URL = "https://help.iqm.com/en"
USER_AGENT_PRODUCT = "IQM-RAG-Assignment-Bot"

DEFAULT_DELAY_SECONDS = 2.0


def scraper_user_agent() -> str:
    """Return the identifiable user-agent. Required; the crawl refuses to run without a contact."""
    value = os.environ.get("SCRAPER_USER_AGENT", "").strip()
    if not value:
        raise RuntimeError(
            "SCRAPER_USER_AGENT is not set. Use a value like "
            "'IQM-RAG-Assignment-Bot/0.1 (contact: you@example.com)'."
        )
    return value


def scraper_delay_seconds() -> float:
    """Minimum delay between requests. The crawl uses the larger of this and robots.txt Crawl-delay."""
    raw = os.environ.get("SCRAPER_DELAY_SECONDS", str(DEFAULT_DELAY_SECONDS))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"SCRAPER_DELAY_SECONDS must be a number, got {raw!r}.") from exc
    if value < 0:
        raise RuntimeError(f"SCRAPER_DELAY_SECONDS must be 0 or more, got {value}.")
    return value
