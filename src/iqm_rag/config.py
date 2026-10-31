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
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_JUDGE_MODEL = "gpt-4.1-mini"
DEFAULT_LANGSMITH_PROJECT = "iqm-help-center-rag"
PLACEHOLDER_LANGSMITH_KEYS = ("", "ls-your-key-here")
FALSE_VALUES = ("false", "0", "no", "off")
LLM_MAX_RETRIES = 3  # the OpenAI client retries rate limits, timeouts and 5xx errors with backoff
LLM_TIMEOUT_SECONDS = 60.0
DEFAULT_TOP_K = 8  # chunks retrieved per question; covers the case where a second evidence section ranks around 7th
MAX_TOP_K = 50

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


def retrieval_top_k() -> int:
    """How many chunks to retrieve per question (RETRIEVAL_TOP_K)."""
    raw = os.environ.get("RETRIEVAL_TOP_K", "").strip()
    if not raw:
        return DEFAULT_TOP_K
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"RETRIEVAL_TOP_K must be a whole number, got {raw!r}.") from exc
    if not 1 <= value <= MAX_TOP_K:
        raise RuntimeError(f"RETRIEVAL_TOP_K must be between 1 and {MAX_TOP_K}, got {value}.")
    return value


def chat_model() -> str:
    """Name of the OpenAI chat model that writes the answers (CHAT_MODEL)."""
    return os.environ.get("CHAT_MODEL", "").strip() or DEFAULT_CHAT_MODEL


def rewrite_model() -> str:
    """Name of the model that rewrites follow-up questions (REWRITE_MODEL); defaults to the answer model."""
    return os.environ.get("REWRITE_MODEL", "").strip() or chat_model()


def langsmith_api_key() -> str:
    """The LangSmith key, or an empty string if it is unset or still the placeholder. Never log or print the value."""
    value = os.environ.get("LANGSMITH_API_KEY", "").strip()
    return "" if value in PLACEHOLDER_LANGSMITH_KEYS else value


def tracing_enabled() -> bool:
    """Tracing is on when a LangSmith key is present, unless LANGSMITH_TRACING is explicitly false."""
    switched_off = os.environ.get("LANGSMITH_TRACING", "").strip().lower() in FALSE_VALUES and bool(os.environ.get("LANGSMITH_TRACING", "").strip())
    return bool(langsmith_api_key()) and not switched_off


def langsmith_project() -> str:
    return os.environ.get("LANGSMITH_PROJECT", "").strip() or DEFAULT_LANGSMITH_PROJECT


def judge_model() -> str:
    """Name of the model that judges answers in the evaluation (JUDGE_MODEL)."""
    return os.environ.get("JUDGE_MODEL", "").strip() or DEFAULT_JUDGE_MODEL


# --- retrieval pipeline switches (each can be changed without touching code, so configurations can be compared) ---

RETRIEVAL_MODES = ("dense", "hybrid")  # dense: vector search only; hybrid: vector search and BM25 keyword search fused
RERANKERS = ("off", "llm")  # llm: a language model reorders the candidates
DEFAULT_CANDIDATES = 30  # candidates taken from each search before fusion and reranking
MAX_CANDIDATES = 100


def _choice(name: str, allowed: tuple[str, ...], default: str) -> str:
    value = os.environ.get(name, "").strip().lower() or default
    if value not in allowed:
        raise RuntimeError(f"{name} must be one of {', '.join(allowed)}, got {value!r}.")
    return value


# The shipped defaults follow the held-out ablation (docs/evaluation-report.md): hybrid search with an LLM rerank. Neighbour expansion
# measured no gain, so it stays off. Set RETRIEVAL_MODE=dense and RERANK=off for the plain baseline.
DEFAULT_RETRIEVAL_MODE = "hybrid"
DEFAULT_RERANK = "llm"


def retrieval_mode() -> str:
    """dense or hybrid (RETRIEVAL_MODE)."""
    return _choice("RETRIEVAL_MODE", RETRIEVAL_MODES, DEFAULT_RETRIEVAL_MODE)


def rerank_mode() -> str:
    """off or llm (RERANK)."""
    return _choice("RERANK", RERANKERS, DEFAULT_RERANK)


def neighbour_expansion() -> bool:
    """Add the adjacent parts of split sections to the context (NEIGHBOURS=1)."""
    value = os.environ.get("NEIGHBOURS", "").strip().lower()
    return bool(value) and value not in FALSE_VALUES


def retrieval_candidates() -> int:
    """How many candidates each search contributes before fusion and reranking (RETRIEVAL_CANDIDATES)."""
    raw = os.environ.get("RETRIEVAL_CANDIDATES", "").strip()
    if not raw:
        return DEFAULT_CANDIDATES
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"RETRIEVAL_CANDIDATES must be a whole number, got {raw!r}.") from exc
    if not 1 <= value <= MAX_CANDIDATES:
        raise RuntimeError(f"RETRIEVAL_CANDIDATES must be between 1 and {MAX_CANDIDATES}, got {value}.")
    return value


def rerank_model() -> str:
    """Name of the model that reranks candidates (RERANK_MODEL); defaults to the answer model."""
    return os.environ.get("RERANK_MODEL", "").strip() or chat_model()
