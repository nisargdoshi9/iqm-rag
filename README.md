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
├── generation/      # prompts, RAG chain
├── observability/   # tracing
└── evaluation/      # dataset, metrics, runner
app.py               # chat interface entry point
scripts/             # scrape.py, index.py, evaluate.py
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

To be added as each stage lands (scraping, indexing, chatbot, evaluation).
