"""Central configuration: data paths and settings read from environment variables.

Values come from the process environment. Export them, or load `.env` before running.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

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
INDEX_DIR = DATA_DIR / "index"
CHROMA_DIR = INDEX_DIR / "chroma"
INDEX_REPORT_PATH = INDEX_DIR / "index_report.json"
EVALUATION_DIR = DATA_DIR / "evaluation"

BASE_URL = "https://help.iqm.com/en"
USER_AGENT_PRODUCT = "IQM-RAG-Assignment-Bot"

DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"

load_dotenv(ROOT_DIR / ".env")  # does not override variables already set in the process environment


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


def openai_api_key() -> str:
    """Return the OpenAI key from the environment. Never log or print the value."""
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value or value == "sk-your-key-here":
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return value


def embedding_model() -> str:
    """Name of the embedding model. Stored with the index so a model change is detected."""
    return os.environ.get("EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL
