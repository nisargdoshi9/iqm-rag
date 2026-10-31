# Incremental updates and the MCP server: decisions

Status: decided and implemented (2026-10-31). Code: `src/iqm_rag/update.py`, `scripts/update.py`, `src/iqm_rag/scraping/scraper.py` (removals, crawl
plan), `src/iqm_rag/mcp_server.py`, `scripts/mcp_server.py`. Tests: `tests/test_update.py`, `tests/test_mcp_server.py`.

## Incremental updates

What already existed: the scraper skipped articles whose stored date equals the sitemap date, and the index embedded only new or changed chunks
and deleted stale ones. What was missing: articles removed from the site were reported but never dropped (so a deleted article would stay in the
data, the chunks and the index and keep being cited), and there was no single command or summary.

| # | Decision | Reason |
|---|---|---|
| 1 | One command, `scripts/update.py`, runs scrape, clean, chunk and index and prints what changed at each step | The steps were already incremental; the gap was chaining them and reporting |
| 2 | Removed articles are dropped from `articles.jsonl` and their local raw HTML is deleted, so they leave the processed data, the chunks and (through the index's stale-chunk deletion) the index | A bot must not cite a page that no longer exists. Both files are regenerable |
| 3 | Removal needs a healthy crawl: no collection or sitemap errors and at least 80% of the stored articles found again; otherwise nothing is dropped and the reason is reported | A page that failed to load must never delete an article |
| 4 | Any failed download or failed cleaning stops the update before cleaning, chunking and indexing; a rerun retries only the failures | A failed record is skipped by the cleaner, so continuing would silently remove that article from the index |
| 5 | `--dry-run` is discovery only (collection pages and the sitemap, about 14 requests): lists new, changed and removed articles and writes nothing | Previewing without downloading or changing anything |
| 6 | Chunking and cleaning are re-run in full | They are local, deterministic and take seconds; the index sync by content hash is what keeps embedding incremental |

Limits: change detection relies on the sitemap date, so an edit without a new date is only found with `--force`. A real run against a copy of
the data (live site, two days after the first scrape) found 1 new and 11 changed articles, made 26 requests and re-embedded 12 new, 17 changed
and 1 removed chunk (about 5,600 tokens). The committed dataset was left at the 2026-10-29 snapshot, because the evaluation questions, hashes and
results were measured on it; updating it would need the question set re-validated.

## MCP server

| # | Decision | Reason |
|---|---|---|
| 1 | Tools: `search_help_center(query, top_k)` and `get_article(article, max_chars, offset)`; no `ask` tool | The brief asks to expose the search. A search tool lets the client's model search again and cite the URLs; an `ask` tool would double the model calls and hide the evidence. Search then fetch is the usual retrieval-server pattern |
| 2 | Search runs the shipped pipeline (hybrid and LLM rerank) | Same quality as the chat page, about a second and a fraction of a cent per search |
| 3 | Passages carry title, section, URL, relevance and text, capped at 2,000 characters with a `truncated` flag; `top_k` 1 to 10, default 5 | Small enough for a client's context, with the URL to cite |
| 4 | Both tools are marked read-only; errors (empty query, bad `top_k`, missing index, unknown article, failed search) are tool errors with a clear message, not crashes | The client model can read the message and recover |
| 5 | stdio transport, official `mcp` SDK, settings from `.env`, index and articles loaded on the first call, all logging to stderr | Claude Desktop and Claude Code run stdio servers; stdout carries the protocol |
| 6 | Local only, not hosted: a client needs the repository, the virtualenv, the built index and the keys | A shared HTTP server would need authentication and cost control; out of scope |

Limits: the server loads the index at start-up, so restart the client after an update. Each search sends the query to OpenAI (embedding and
rerank). The MCP SDK is v2 (`MCPServer`); version 1 used `FastMCP`.
