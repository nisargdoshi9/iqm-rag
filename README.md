# iqm-rag

A chatbot that answers questions about IQM's product using only the articles published on the IQM Help Center (`help.iqm.com`).
It is a Retrieval-Augmented Generation (RAG) pipeline: it scrapes and cleans the articles, indexes them, retrieves the most relevant
sections for a question and has an LLM write an answer that cites the articles it used. When the articles do not cover a question, it
says so instead of guessing.

- **Grounded answers with sources.** Every answer links the Help Center articles it used; links come from stored metadata, never from the model.
- **Says when it cannot answer.** Three outcomes are shown distinctly: answered, not in the Help Center, and a clarifying question for vague questions.
- **Follow-up questions.** Chat history is used to understand follow-ups ("what about those settings?").
- **Tracing and evaluation.** LangSmith tracing (optional) and a 28-question evaluation plus 16 held-out questions, with saved results.

How it works: [docs/architecture.md](docs/architecture.md) · design summary: [docs/writeup.md](docs/writeup.md) · results:
[docs/evaluation-report.md](docs/evaluation-report.md) · decisions: [docs/design-decisions.md](docs/design-decisions.md)

## Architecture in brief

```
Offline   Help Center -> scrape -> clean (sections, tables, media) -> chunk (one per section) -> embed -> Chroma index
Online    question (+ history) -> rewrite follow-ups -> vector + keyword search -> fuse -> LLM rerank -> top 8 chunks
          -> numbered context -> gpt-4.1-mini (status + answer + source numbers) -> checks -> answer with links -> chat page
```

Diagrams and details are in [docs/architecture.md](docs/architecture.md).

## Setup

Requires Python 3.10 or newer (developed on 3.12) and an OpenAI API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt     # pinned versions
pip install -e .
cp .env.example .env                # then set OPENAI_API_KEY (and optionally the other values)
```

### Configuration (`.env`)

| Variable | Needed for | Default |
|---|---|---|
| `OPENAI_API_KEY` | indexing, answering, evaluation | none (required) |
| `EMBEDDING_MODEL` | indexing and querying; changing it needs `scripts/index.py --rebuild` | `text-embedding-3-large` |
| `CHAT_MODEL`, `REWRITE_MODEL`, `JUDGE_MODEL` | answering, follow-up rewrite, evaluation judge | `gpt-4.1-mini` (rewrite defaults to the chat model) |
| `RETRIEVAL_TOP_K` | chunks retrieved per question (1 to 50) | `8` |
| `RETRIEVAL_MODE`, `RERANK`, `NEIGHBOURS`, `RETRIEVAL_CANDIDATES`, `RERANK_MODEL` | retrieval switches: `dense` or `hybrid`, rerank `off` or `llm`, neighbour parts, candidates per search, reranker model | `hybrid`, `llm`, `0`, `30`, the chat model |
| `LANGSMITH_API_KEY` | tracing; tracing is on only when this is set | unset (tracing off) |
| `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`, `LANGSMITH_HIDE_INPUTS`, `LANGSMITH_HIDE_OUTPUTS`, `LANGSMITH_ENDPOINT` | tracing options | see `.env.example` |
| `SCRAPER_USER_AGENT`, `SCRAPER_DELAY_SECONDS` | scraping only | none (required to scrape) / `2.0` |

Never commit `.env`; it is git-ignored.

## Quick start: run the chatbot

The cleaned dataset and the chunks are in the repository, so you only need to build the index (this is the one step that calls the embeddings API):

```bash
python scripts/index.py        # embeds the 2,131 chunks: about a minute and roughly $0.06
streamlit run app.py           # opens the chat page
```

Try the example questions on the start screen. Turn on **Developer mode** in the sidebar to see the search query, the retrieved
passages with scores, token counts, timings and the trace ID under each answer.

Other ways to try it:

```bash
python scripts/chat.py --evidence                 # chat in the terminal (/new, /quit)
python scripts/ask.py "How do I schedule a report?" --evidence   # one question
python scripts/retrieve.py "How do I schedule a report?"         # retrieval only (embeds the query, no answer)
```

## Rebuild the data from scratch

Only needed to refresh the dataset. Scraping takes about 7 minutes (2 seconds between requests).

```bash
export SCRAPER_USER_AGENT="IQM-RAG-Assignment-Bot/0.1 (contact: you@example.com)"   # use your own contact
python scripts/scrape.py       # data/raw/: raw HTML and article records (reruns skip unchanged articles; --force refetches)
python scripts/normalize.py    # data/processed/: structured articles, media, table audit (no network)
python scripts/chunk.py        # data/chunks/chunks.jsonl (no network)
python scripts/index.py        # data/index/: the Chroma index; --dry-run shows the cost first, --rebuild after a model change
```

The scraper honours `robots.txt`, identifies itself with the contact you set, waits at least `SCRAPER_DELAY_SECONDS` between requests and
retries timeouts, 5xx and 429 responses up to 3 times. Raw HTML (`data/raw/html/`) and the vector index (`data/index/`) are not committed.

## Data in the repository

| Path | What |
|---|---|
| `data/processed/articles.jsonl`, `media.jsonl` | The cleaned dataset: 200 articles as sections, plus their images and videos (scraped 2026-10-29) |
| `data/chunks/chunks.jsonl` | The 2,131 chunks that are embedded (link-only navigation sections are dropped) |
| `data/evaluation/questions.jsonl` | The evaluation set (28 questions with key facts, evidence quotes and expected sources) |
| `data/evaluation/holdout.jsonl` | 16 further questions written before the improvements, used to compare retrieval configurations on unseen questions |
| `data/evaluation/results/` | Saved evaluation runs, each with `review.csv` for side-by-side manual review |
| `docs/traces/example-trace.json` | One exported LangSmith trace |

The articles are the property of IQM and are used here only to build the assistant for this assignment.

## Evaluation

```bash
python scripts/evaluate.py --split dev --dry-run     # plan only: call counts, rough cost, checks; no API calls
python scripts/evaluate.py --split dev --yes         # run (model calls); nothing is called without --yes
python scripts/evaluate.py --split holdout --yes --retrieval-mode hybrid --rerank llm   # one retrieval configuration on the held-out questions
python scripts/compare_runs.py --split holdout       # table comparing the saved runs of a split; no API calls
python scripts/evaluate.py --rebuild data/evaluation/results/<run>   # rebuild summaries from saved results, no API calls
```

Results and their limits are in [docs/evaluation-report.md](docs/evaluation-report.md). The test and holdout splits are run once per dataset
version and retrieval configuration; the runner refuses a repeat. The shipped default (hybrid search with an LLM rerank) was chosen from the
holdout comparison.

## Tracing

Set `LANGSMITH_API_KEY` in `.env` and every request is traced (one run, one step per stage, with the retrieved chunks, prompts,
responses, latency and token usage). `python scripts/export_trace.py <trace-id>` exports a trace as JSON. Without a key nothing is sent.
Questions and answers are stored in LangSmith when tracing is on; set `LANGSMITH_HIDE_INPUTS` and `LANGSMITH_HIDE_OUTPUTS` to keep them out.

## Tests

```bash
python -m unittest discover -s tests
```

432 tests with saved fixtures, fake models and a throwaway index; they never call the live site or any API.

## Layout

```text
src/iqm_rag/
├── config.py        # data paths and env-based settings
├── scraping/        # discovery, scraper, cleaning
├── ingestion/       # chunking, embeddings, indexing
├── retrieval/       # vector search, BM25, fusion, reranker, pipeline, follow-up rewriting
├── history.py       # chat messages and the history window
├── generation/      # context, prompts, citations, the answer chain, conversations
├── ui/              # chat page, display logic, styles, scripts
├── observability/   # LangSmith tracing, trace export
└── evaluation/      # dataset checks, metrics, judge, runner
app.py               # chat page: streamlit run app.py
scripts/             # scrape, normalize, chunk, index, retrieve, ask, chat, evaluate, compare_runs, export_trace
tests/
data/                # raw/ (not committed), processed/, chunks/, index/ (not committed), evaluation/
docs/                # architecture, decisions, evaluation report, write-up
```

## Known limits

- The LLM rerank improves retrieval (see the held-out comparison) but adds about a second and doubles the cost per question; it is a language
  model, so its ordering can vary slightly between runs. `RERANK=off` and `RETRIEVAL_MODE=dense` give the faster baseline.
- Answers still cite an article outside the curated list for about half of the questions (mostly related articles), and a step that says
  "follow steps 7 to 10 of another workflow" is sometimes repeated instead of written out (hold-011 in the report).
- The evaluation sets are small (28 and 16 questions), were not reviewed question by question for the first set, and the judge is the same model family as the answerer.
- Answers are not streamed, and images and videos are not shown; chat history is kept only for the open browser session.
