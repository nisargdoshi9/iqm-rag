# FR-2: Cleaning and normalisation — decisions

Status: implemented on branch `feat/fr-2-cleaning`; awaiting local test. Decisions below are settled unless marked open.

## Context

Requirement (assignment, FR-2): strip navigation, footers and boilerplate, while keeping headings, lists and tables meaningful.

The current extractor (`extract_article` in `src/iqm_rag/scraping/scraper.py`) takes all text inside `.article_body`. That body includes page furniture, which then reaches `raw_text` and would reach chunks if not removed.

## Fixed furniture found (counts across 200 articles)

| Text | Articles | What it is |
|---|---|---|
| "On this page:" followed by a list of headings | 195 | Auto-generated table of contents. It repeats the article's own headings, so it adds noise and duplicates. |
| "Return to the top of this article" | 144 | Back-to-top link at the end of the article. |
| Related-article list just before the back-to-top line (to verify) | unknown | Looks like a "related articles" block. Not yet confirmed as furniture. |
| Zero-width space "​" | 44 | Stray invisible character. Whitespace normalisation should remove it. |

Not furniture (content, keep): "Key terms and concepts" (43 articles) appears to be a real section heading. Confirm it before removing anything similar.

## Decisions to make

### D-FR2-1. How to remove the furniture
- **A. Remove by exact text.** Simple, but brittle: a wording change on the site would break it, and it can't tell content from furniture that happens to match.
- **B. Remove by page structure.** Target the table-of-contents block and the back-to-top element by their HTML structure, not their wording. More robust, but depends on the current page markup.
- **C. Remove by repetition.** Drop lines that appear in many articles. Catches furniture we haven't listed, but can also remove real content that repeats (for example "Click" or "Select" would be caught if the rule were too loose).

Decision: B for the known blocks, plus a report of repeated lines (as above) to catch anything new, so we see furniture before it reaches chunks.

### D-FR2-2. Keep the table of contents or not
- Remove it from the text. Headings are kept in the article body, so section structure isn't lost.
- Alternative: keep it as metadata for chunk section paths. Not needed if headings are kept.

### D-FR2-3. Related-articles block
- Verify its markup on a few articles, then decide whether to remove it. It's cross-links to other articles, not evidence for the answer, so removing it is likely right.

## To verify before implementing
- The related-articles block: confirm its structure and count.
- "Key terms and concepts": confirm it's a real section.
- Whether any furniture sits outside `.article_body`. Only the body is saved today, so it isn't a risk yet.

## Media and table findings (from the first crawl, 200 articles)

Principle: text is the evidence. Media is display-only and never used to answer.

### Evidence
- 1,292 images in 156 articles; 65 YouTube embeds (34 unique videos). No image has alt text or a caption.
- Exclusive association types (priority: table, list item, before list, after heading, heading then text, other): before_list 623, list_item 274, after_heading 175, after_heading_text 72, table multi-row 57, table single-row 82, other 9.
- Verification sample (23 images, one judge, small n, a smoke test, not corpus-wide accuracy): section right 21/23; step right 17 clean, 4 partial, 2 not matched. Partial = the image fits the attached unit but covers only part of it or runs past it.
- 82 single-row table images are 206–1,600 px wide (median 595), none under 150 px, so a size filter does not find decorative images. 36 are app-name labels in "Primary app(s)" sections of collection overview pages; 46 are report/chart images in other articles and are real content.
- 668 tables: 342 single-row callouts, about 326 data tables, plus layout tables that hold only images or app labels.

### Decisions
1. **Section-level association is the guarantee.** Association types are ranking hints, not proof that an image illustrates a specific step.
2. **Exclude the app-label images by template** (52 in practice, see the implementation notes): collection overview article plus the "Primary app(s)" section. The rule is explicit and auditable. Exclude them from generic instructional media, but consider keeping their app name as a structured association (useful for "which app supports X?").
3. **Classify tables before attaching media**: callout, data, media/layout, unknown. Use cell structure, row patterns and surrounding content, not row count alone.
4. **Keep the 46 report/chart images.** Attach them to the containing section and keep their table context.
5. **Record partial matches explicitly.** Evaluation labels: `clean`, `partial`, `wrong`, `uncertain`.
6. **Allow no media.** If a section has no relevant assets, show none; do not force three images.
7. **Media display:** hotlink for the demo; maximum 3 images, thumbnails with click-to-expand; videos get a thumbnail, verified title and click-to-load player.
8. **Defer OCR** until evaluation shows a meaningful gap. Numbered callouts in screenshots are a possible later signal for step matching.
9. **Media is a sidecar.** Chunks stay text-only; media joins by stable section/list/row IDs. Table images never replace the row's textual evidence.
10. **Large tables** split at row boundaries with repeated headers; structured rows are the internal source of truth, and Markdown is derived from them.
11. **Evaluate section accuracy and step accuracy separately.**

### Still open for implementation
See the decision list in the chat for ID scheme, conversion method, table-classification rules, list-in-cell format, sidecar schema, and output layout.

## Related
- Media decisions also affect FR-3 (chunk IDs) and FR-7 (display).

## Implementation notes (FR-2)

Code: `src/iqm_rag/scraping/` — `blocks.py` (parse the article body into structured blocks), `tables.py` (table classes), `markdown.py` (render), `normalization.py` (furniture, sections, IDs, hashes, media, run). Entry point: `scripts/normalize.py`. Reads `data/raw/` only; writes `data/processed/`. No network access.

### Settled choices
- **Conversion:** a custom walker over the Intercom block wrappers (`div.intercom-interblocks-*`), no new dependency. Blocks nest (list items, table cells, collapsible sections). Markup it does not recognise becomes an `unknown` block that keeps its HTML. The first run found none.
- **Furniture (D-FR2-1, by structure):** the "On this page:" heading plus its list (matched on the exact heading, 197 articles), and paragraphs starting "Return to the top" (145; both "…of this article" and "…of this page" occur). Empty spacer blocks and zero-width characters are removed when parsing.
- **Related-articles block (D-FR2-3):** it turned out not to be furniture. The "Locate additional … resources" lists are authored headed sections, so they are kept as content.
- **"Key terms and concepts":** real section heading, kept.
- **Table classes:** `callout` (boxed note: one text cell, or a bold "Label:" cell plus a text cell; the label is optional for a single cell), `media_layout` (images in cells; any text next to them is kept), `data` (header row with 2+ filled cells, rectangular rows), `unknown` (kept in full, listed in `table_audit.jsonl` with its HTML and structured cells). Classification uses cell structure, not row count alone.
- **Lists inside table cells:** joined with `; ` in Markdown. The structured rows keep the original list.
- **Output:** structured sections are the source of truth in `articles.jsonl`; `cleaned_markdown` is derived. Images and videos are not rendered into Markdown; they go to `media.jsonl`.
- **Large tables:** the renderer writes each table whole. Splitting at row boundaries with repeated headers is a chunking job (FR-3); the structured rows and row IDs support it.

### IDs and hashes (decision 1)
- Section: `{article_id}:s{n}` (n counts kept sections, starting at 1; a lead-in before the first heading is `s1`). List: `{section}:l{n}`; item: `{list}:i{n}`; table: `{section}:t{n}`; row: `{table}:r{n}`; media: `{article_id}:m{n}`.
- Each section, list, table and row has a SHA-256 `content_hash` of its rendered Markdown; the article has one over `cleaned_markdown`.
- **Matching an old and a new version of an article:** same ordinal and same hash = unchanged; same hash at another ordinal = moved; same ordinal and different hash = edited. Inserting a section shifts later ordinals, so match by hash first.
- Output is deterministic (two runs produce identical files).

### Media
- Associations: `before_list`, `list_item`, `after_heading`, `after_heading_text`, `table_row` (image in a data-table row), `table_layout` (image in a media_layout table), `table_cell`, `other`. A section is the guaranteed unit; the association is a ranking hint.
- Each media record carries section, container (list, list item, row or table) and nearby text. Videos carry the YouTube ID; the title lookup (oEmbed) is not done yet.
- **App labels (decisions 2 and 6):** images in the "Primary app(s)" section of "…collection overview" articles are marked `excluded: true`, reason `app_label`. That is 52 images in 8 articles (more than the 36 first counted, which only included single-row tables). `app_name` is `null` with `app_name_source: "image_only"`, because the name exists only in the image pixels and the page gives no text for it. **Open:** fill it from a reviewed manual mapping, or later with OCR.

### First full run (200 articles, 0 failed)
- 2,977 sections. Blocks: 16,976 paragraphs, 1,976 lists, 668 tables, 63 native callouts, 15 code blocks, 1,292 images, 65 videos.
- Tables: callout 284, data 325, media_layout 58, unknown 1. The unknown table is in article 8615247 (a single row of three bold labels).
- Media: 1,357 records (1,292 images, 65 YouTube embeds). Associations: before_list 625, list_item 274, after_heading 208, after_heading_text 111, table_layout 95, table_row 44. Excluded app labels: 52.
- No leftover "On this page" or zero-width characters in the output.

### Known limits
- Image columns in data tables render as empty columns in Markdown (the header and row text remain). Dropping all-empty columns is an open choice.
- A section holding only a video or image (for example "Video tutorial: …") has a heading and no text. FR-3 should merge such sections into a neighbour.
- Links to the old help-center host (`intercom.help/IQM-Corp/…`) are kept as written.
- Checked by reading sample output and by tests, not against every article.
