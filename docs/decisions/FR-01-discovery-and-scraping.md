# FR-1: Help Center discovery and scraping — decisions

Status: implemented and run on 2026-10-29. 200 of 200 articles fetched in 214 requests with no failures; collection pages and the sitemap agreed exactly (no article found by only one); all 200 records have a last-updated date.

## Context (observed on help.iqm.com, 2026-10-29)

- `robots.txt`: `User-agent: *`, disallows only `/not-authorized`, `/not-found` and a literal template path. Sets `Crawl-delay: 1`. Lists `http://help.iqm.com/sitemap.xml`.
- Home page links 11 collections.
- Each collection page lists its articles. The union over all 11 collections is 200 unique article URLs.
- `sitemap.xml` has 211 `<url>` entries: 200 articles and 11 collection pages. It matches the collection pages exactly. Every entry has a `<lastmod>`.
- Article pages are server-rendered (title, body and the article element are in the HTML). The last-updated date is in an embedded JSON field, `lastUpdatedDate` (ISO 8601 UTC). The visible text is relative ("Updated over 7 months ago"), so it is not used.
- For two articles checked, sitemap `<lastmod>` equals `lastUpdatedDate` exactly.
- A bare article URL (ID without slug) returns 302 to the slug URL.
- Collection pages show a "Next" control. The scraper follows pagination if it is present; the crawl found 200 articles in total, matching the sitemap.
- `lastUpdatedDate` was checked on four articles before the crawl; the crawl then found it on all 200.

## Decisions

### D1. Discovery source — both
Use collection pages for membership and the sitemap as a cross-check. Discovery records any article found by one method but not the other, and the crawl report lists those differences. Rationale: the PDF says to start from collection pages; the sitemap catches anything a collection page misses.

### D2. Fetching method — `requests` + `BeautifulSoup`
Plain HTTP first. Playwright only if an article's body cannot be extracted this way. Rationale: article pages are server-rendered.

### D3. Delay between requests — 2 seconds
Stricter than `Crawl-delay: 1`, which gives a buffer. The crawl of about 211 pages takes roughly 7 minutes at this delay. Default lives in `.env.example` / `config.py`.

### D4. User-agent — honest bot name with a contact from config
Format: `IQM-RAG-Assignment-Bot/0.1 (contact: <email>)`. The contact value comes from `SCRAPER_USER_AGENT` in `.env`, so no personal details are committed. Rationale: the assignment asks for a clear user-agent; disguising the scraper as a browser would hide who is crawling.

### D5. Last-updated date — `lastUpdatedDate` from the embedded JSON
Confirmed: this is the article's last-edited date on the Help Center, not the crawl time. The crawl time is stored separately as `scraped_at`. Stored as an ISO 8601 string; `null` if the field is missing.

### D6. Article identity and renaming — numeric ID plus current slug URL
- `article_id` = the numeric ID in the URL (e.g. `5651450`).
- `canonical_url` = the current slug URL (from the sitemap or the post-redirect URL).
- Reruns match articles by `article_id`, not URL. If the slug changed, `canonical_url` is updated and the change is recorded in the crawl report.
- Chunks take their citation URL from `canonical_url` at index time, so re-indexing picks up a rename.
- If an ID disappears from the sitemap, or a new ID appears, the crawl report lists it as removed or new.

### D7. Body format — Markdown with structure
Output Markdown that keeps section headings (hierarchy), lists, tables, links and media information.

### D8. Media-heavy articles — text, captions and media URLs now
Keep text and captions, and record media URLs and their type. Do not transcribe video or describe images. Measure how many of the 200 articles are media-heavy during the first crawl and report it in the crawl report. If the count is small, this approach stays; if large, transcription is revisited later.

### D9a. Raw storage — separate files with a JSONL index
- Each article's raw HTML is saved as its own file, under `data/raw/`.
- A JSONL index (`data/raw/articles.jsonl`) holds one record per article and points to its HTML file via `raw_html_path`.
- Rationale: the raw files stay untouched (raw content is immutable); the JSONL stays small and easy to inspect. About 200 files at roughly 100 KB each is about 20 MB.

### D9b. Rerun rule — skip unchanged articles
On a rerun, skip any article whose stored `last_updated` equals its sitemap `<lastmod>`, and refetch only the rest. An unchanged article costs no requests. Rationale: the two sources matched exactly in the sample checked.

### D9c. Content hash — stored per article
- FR-1 stores `raw_html_sha256` (SHA-256 of the downloaded HTML) on every fetched article.
- FR-2 adds `content_hash` (SHA-256 of the cleaned Markdown), which is the hash the spec's change detection (Bonus D) is meant to use.

### D10. Retry policy — 3 retries, exponential backoff
- Retry only on timeouts, HTTP 5xx and HTTP 429.
- Other 4xx responses are not retried; they are recorded as failed.
- After the final retry, the article is recorded as failed in the crawl report with the reason.

## Implementation notes
- Code: `src/iqm_rag/scraping/discovery.py` (URLs, collections, sitemap) and `scraper.py` (fetching, extraction, rerun, report). Entry point: `scripts/scrape.py`.
- Extraction is raw only (title, date, body text, media). Markdown cleaning is FR-2.
- Raw HTML is saved before extraction, so a page that fails extraction keeps its raw copy and is reported as failed.
- Renames show up as `canonical_url` changes after redirects, and are listed in the crawl report.
- The rerun rule skips an article only if its last success, sitemap `lastmod` and stored `last_updated` all agree, and its raw file is present.
- Pagination is detected from a `rel="next"` link. The collection pages checked so far have none, so this is recorded as "not found", not as "does not paginate".
- Tests: `tests/test_scraping.py`, using saved fixtures in `tests/fixtures/`. The test runner is `unittest`, so no new dependency was added. pytest is still an open decision.

## To verify during the first full crawl
- **Pagination:** check whether any collection page has a "Next" page beyond the first. Record the result.
- **Dates:** check `lastUpdatedDate` for all 200 articles. Record any missing values.
- **Media:** count media-heavy articles (D8) and record the distribution in the crawl report.
