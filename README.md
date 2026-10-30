# iqm-rag

A chatbot that answers questions about IQM's product using only the articles published on the IQM Help Center (`help.iqm.com`), served through a Retrieval-Augmented Generation (RAG) pipeline.

> **Status:** initial scaffolding. Components, models, and tooling are chosen and documented as they are built.

## Layout

```text
src/iqm_rag/
├── config.py        # data paths and env-based settings
├── scraping/        # discovery, scraper, normalization
├── ingestion/       # chunking, embeddings, indexing
├── retrieval/       # retriever, query rewriting
├── history.py       # chat messages and the history window
├── generation/      # context, prompts, citations, RAG chain
├── ui/              # chat page, display logic, styles
├── observability/   # LangSmith tracing, trace export
└── evaluation/      # dataset, metrics, runner
app.py               # chat interface entry point: streamlit run app.py
scripts/             # scrape.py, index.py, retrieve.py, ask.py, chat.py, export_trace.py, evaluate.py
tests/
data/                # raw/, processed/, chunks/, evaluation/
docs/                # architecture, design decisions, evaluation report, write-up, demo script
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # then fill in values
```

Requires Python 3.10+.

## Architecture

To be written once the pipeline exists (scrape → clean → chunk → embed → retrieve → generate with citations).

## Running

### Scrape the Help Center (FR-1)

Set a contact in the user-agent (required), then run the scraper:

```bash
export SCRAPER_USER_AGENT="IQM-RAG-Assignment-Bot/0.1 (contact: you@example.com)"
python scripts/scrape.py          # rerun skips articles that have not changed
python scripts/scrape.py --force  # refetch everything
```

Outputs, all under `data/raw/`:
- `articles.jsonl`: one record per article, with `scrape_status` and `error`.
- `html/<article_id>.html`: raw HTML for each article.
- `crawl_report.json`: discovered, fetched, skipped, failed, renamed and removed articles, plus pagination and media counts.

The scraper honours `robots.txt`, waits at least `SCRAPER_DELAY_SECONDS` between requests (default 2), and retries timeouts, 5xx and 429 responses up to 3 times.

### Clean the dataset (FR-2)

Needs no network access. Reads `data/raw/` and writes `data/processed/`:

```bash
python scripts/normalize.py
```

Outputs: `articles.jsonl` (structured sections plus derived Markdown), `media.jsonl` (images and videos with their section, association and exclusion reason), `table_audit.jsonl` (tables that could not be classified, with their original HTML), and `cleaning_report.json`.

### Tests

```bash
python -m unittest discover -s tests
```

Tests use saved fixtures and mocked HTTP. They never call the live site.

Other stages (cleaning, indexing, chatbot, evaluation) are added as they land.
