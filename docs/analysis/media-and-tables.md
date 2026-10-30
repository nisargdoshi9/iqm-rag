# Analysis: images, tables and videos in the IQM Help Center

Source: the first full crawl (2026-10-29), 200 articles, raw HTML in `data/raw/html/` and records in `data/raw/articles.jsonl`.

Purpose: decide how to clean tables, how to associate images and videos with text chunks, and how to show media in answers. Decisions that came out of this are in `docs/decisions/FR-02-cleaning.md`.

Working principle: **text is the evidence; media is display-only.** The bot never describes what an image shows, because the pages give us no description and the spec forbids invented ones.

Method note: all counts below came from ad-hoc scripts over the saved HTML (BeautifulSoup, article body `.article_body`). The scripts are not in the repo yet. Numbers can be reproduced from the definitions in section 8.

---

## 1. Media inventory

| Item | Value |
|---|---|
| Articles with any media | 160 of 200 (80%) |
| Articles with no media | 40 |
| Images | 1,292 across 156 articles |
| Video embeds | 65 across 32 articles |
| Unique videos | 34 (some reused across articles) |
| Articles with 5+ media items | 96 |
| Shortest article text | 1,300 characters (no media-only articles) |
| Median article text | 7,426 characters |

By collection (articles with media / total): Audience targeting 38/43, Reporting and analytics 28/46, Media planning and campaign setup 25/32, Campaign delivery and optimization 17/19, Vera 13/14, Creatives and specifications 12/13, Account setup 10/11, Ad inventory 10/11, Video tutorials 4/4, Conversions and tracking 3/6, Release notes 0/1.

## 2. Images

### Metadata available
- Alt text: none (0 of 1,292).
- Figure captions: none.
- Image file names are hashed CDN paths, so they carry no meaning.
- The only text around an image is the page text near it.

### HTML pattern
- 1,289 of 1,292 images sit in `div > a > img`. The link target is the same URL as the `src` (full-size file on IQM's CDN, hosts `downloads.intercomcdn.com` and `iqm-corporation.intercom-attachments-7.com`).
- The other 3 sit inside paragraphs.
- No image sits inside a `<figure>`.

### Position in the text
- 97% have a text block directly before them, and 97% have one directly after.
- Runs of consecutive images are rare: 24 runs; one run is 13 images.
- Median text length: 73 characters before an image, 64 after.
- About 43% of the blocks before an image end with a colon (for example "Click **Save**:").
- 21% of images sit inside list items.

### Association counts (overlapping definitions)
Out of 1,292 images:
- Directly after a heading: 254 (19.7%).
- Heading, then at least one text block, then the image: 679 (52.6%).
- Inside a list item: 274 (21.2%).
- Any of these three: 1,206 (93.3%). The categories overlap.
- Next block is a list item: 897 (69.4%). Of these, 624 (48.3%) are outside a list with the list starting right after the image; the rest are inside a list item with another item following.
- None of the three: 86. Of these, 73 are in table cells and 13 are outside tables.

### Association counts (exclusive, used for the verification sample)
Each image gets one type. Priority: table, list item, before list, after heading, heading then text, other.

| Type | Images |
|---|---|
| before_list | 623 |
| list_item | 274 |
| after_heading | 175 |
| after_heading_text | 72 |
| table, multi-row | 57 |
| table, single-row | 82 |
| other | 9 |
| Total | 1,292 |

### The 13 images outside tables that matched none of the three rules
Files under `data/raw/html/`: `9298440` (1), `5735120` (1), `10034144` (2), `10104871` (2), `5651463` (2), `17605856` (1), `8566348` (1), `10552784` (1), `9827089` (1), `5651517` (1). No clear pattern. These are the cases to check by hand.

### Table-cell images
- 73 of the 86 unmatched images were in table cells, all in cells with no text of their own.
- 48 of those were in multi-row tables where the image is the first cell of a row and the other cells hold the row's spec. The "Creative ad specs and requirements" article (7019246) holds 34 of these (one row per ad format, with a mockup image).
- The rest were in single-row tables; see section 5.

## 3. Spot-checks of image to text

### First check: 10 random images against the text block before them
| Result | Count |
|---|---|
| Strong match | 4 |
| Partial match | 3 |
| Mismatch | 2 |
| Decorative | 1 |

The block immediately before an image was the right anchor about half the time. Images often show the step after the text, or a related screen. The nearest heading explained one image better than the text did. One decorative logo was about 306 px wide and 3 KB.

### Second check: 23 images by association type (verification sample)
Limits: one judge (visual inspection), small n, one image per article, the table-row group has only 3 images, and one judgment (#16) is uncertain. It is a smoke test, not evidence of corpus-wide accuracy.

Two ratings per image:
- **Section:** does the image belong to the topic of the section it was attached to?
- **Step:** does it illustrate the specific unit it was attached to (list item, list, row, or the section's opening)?

Labels: `clean`, `partial` (fits the unit but covers only part of it or runs past it), `wrong`, `uncertain`.

| # | Type | Article | Section | Step | Note |
|---|---|---|---|---|---|
| 1 | list_item | 10552784 | right | partial | Shows the pop-up the step opens, plus later numbered steps |
| 2 | list_item | 17606037 | right | clean | Keyword panel with sub-step callouts |
| 3 | list_item | 17238636 | right | partial | Attached to "Click Create", but shows later steps 12–14 |
| 4 | list_item | 14125174 | right | clean | Create New Report page |
| 5 | list_item | 10104761 | right | clean | Restore Proposal pop-up |
| 6 | before_list | 12081845 | right | clean | Whole bundle-saving flow |
| 7 | before_list | 12003355 | right | clean | Reset-password dialog |
| 8 | before_list | 7033837 | right | partial | Covers only the first three steps |
| 9 | before_list | 9300515 | right | clean | Steps 2–7 of the list |
| 10 | before_list | 14125174 | right | partial | Covers only the first step |
| 11 | after_heading | 10560205 | right | clean | Column selector, Data Cost highlighted |
| 12 | after_heading | 9613510 | right | clean | PMP status column tooltip |
| 13 | after_heading | 5651463 | right | clean | Campaigns column highlighted |
| 14 | after_heading | 5735120 | right | clean | App menu, Conversion highlighted |
| 15 | after_heading | 12238868 | right | clean | Creative type selector |
| 16 | after_heading_text | 8566348 | uncertain | uncertain | Column picker under "Saving Your IO Table" |
| 17 | after_heading_text | 5735120 | right | clean | HTML head with pixel script |
| 18 | after_heading_text | 9298440 | right | clean | Priority phase tables |
| 19 | after_heading_text | 10870472 | right | clean | Bundle settings diagram |
| 20 | after_heading_text | 10034144 | right | clean | Drop-off funnel |
| 21 | table_row | 7019246 | right | clean | Native video mockup in spec table |
| 22 | table_row | 12002711 | wrong | wrong | "Customers" app label in a layout table |
| 23 | table_row | 13336712 | right | clean | Segment groups example |

Summary by type:

| Type | n | Section right | Step clean | Step partial | Wrong / uncertain |
|---|---|---|---|---|---|
| list_item | 5 | 5 | 3 | 2 | 0 |
| before_list | 5 | 5 | 3 | 2 | 0 |
| after_heading | 5 | 5 | 5 | 0 | 0 |
| after_heading_text | 5 | 4 | 4 | 0 | 1 uncertain |
| table_row | 3 | 2 | 2 | 0 | 1 wrong |
| **All** | **23** | **21** | **17** | **4** | **2** |

Observations:
- Structure-based types did much better than the "block before the image" rule used in the first check.
- Screenshots use numbered callouts that match the step numbers in the text (for example 12, 13, 14, or 6a–6d). That could later be a step-matching signal, but it needs OCR, which is deferred.
- Partial matches are mainly two shapes: a `before_list` image that covers only the first steps, and a `list_item` image that shows the step's result plus later steps.
- `table_row` mixes data tables and layout tables (#22), so tables must be classified before the row rule applies.

## 4. Single-row table images (82)
- Widths 206–1,600 px, median 595; heights 76–1,334. None is under 150 px wide, so a size filter does not isolate decoration. Median file size about 32 KB.
- 36 are in collection overview articles, all under the "Primary app(s)" section: app-name labels such as "Campaigns" and "Dashboard" (widths 206–738 px). These 36 are about 2.8% of all images.
- 46 are elsewhere: report and chart images in articles such as "Audience Insights report overview" (18), the SLS Insights report overview (11), the AQ Insights report overview (11), and a few others. These are real content.
- 46 of the 82 tables hold text elsewhere in the table; 36 hold only the image.
- Collection overview articles contain 57 images in total.
- Collection overview pages use tables for icon layout.

## 5. Tables

### Counts
- 668 tables across 154 articles; no nested tables.
- 342 are single-row callout boxes ("Re-Match notice:", "Targeting notice:", "More on …:"). They hold real caveats.
- About 326 have two or more rows (data tables). Row-count histogram (6 means 6 or more): 1 row: 342, 2: 9, 3: 21, 4: 125, 5: 43, 6+: 128. Median 4 to 6 rows for data tables, maximum 73; 12 tables have more than 20 rows.
- Columns: median 2, maximum 6.

### Structure
- No `<th>` cells: the first row is the header in all tables.
- No captions; no merged cells (`colspan` / `rowspan`).
- Cells: 5,783 total; 133 empty; 66 contain lists; 131 contain images; 598 contain links.
- Element right before a table: paragraph 314, `h2` 161, `h1` 106, `h4` 70.

### Current limitation
`raw_text` in the JSONL flattens tables into plain lines, so row and column structure is lost at this stage. Cleaning has to rebuild it from the saved HTML.

### Table types found so far
1. **Callout:** single row, a label cell followed by note text. Keep as a labelled paragraph or caveat.
2. **Data table:** a header row plus rows of text, such as the creative spec tables. Convert to rows (Markdown derived from structured rows).
3. **Media / layout table:** cells holding only images or app labels (collection overview icons, side-by-side screenshots, charts). Not a data table.
4. **Unknown:** anything that fits none of the above. Flag for review.

Classification must use cell structure, row patterns and surrounding content, not row count alone.

## 6. Videos
- 65 embeds in 32 articles, all `youtube.com` iframes; 34 unique YouTube IDs.
- Every iframe has the same title, "Embedded youtube video", so the page gives no usable title. The video ID is the only identifier.
- The Video tutorials collection has only 4 articles (all with media).
- Planned: look up the real title through YouTube's public oEmbed endpoint (34 calls), show a thumbnail and a link, and load the player on click. No transcripts and no downloads. Not yet implemented.

## 7. Page furniture (cross-reference)
Logged in `docs/decisions/FR-02-cleaning.md`: "On this page:" table of contents (195 articles), "Return to the top of this article" (144), a related-articles list before it (unverified), and zero-width spaces (44 articles). "Key terms and concepts" (43 articles) looks like content.

## 8. Definitions used
- **Text block:** a non-empty `<p>` or `<li>` (not nested under another text block). Headings, images and empty blocks do not count.
- **Heading:** `h1` to `h6`.
- **After heading:** the previous token in document order is a heading.
- **Heading, then text, then image:** walking back from the image over one or more text blocks reaches a heading.
- **Inside a list item:** the image has an `<li>` ancestor.
- **Before a list:** the next token is a list item (a `<li>`).
- **Table image:** the image has a `<table>` ancestor.

## 9. Limitations
- Counts are structural. They show where images sit, not whether each one fits its text.
- The verification sample is small (23 images, one judge). Treat percentages as a smoke test.
- The first 10-image check and the 23-image check used different anchors, so they are not directly comparable.
- Earlier I guessed the 25 single-row image-only cells were decorative. The size check showed this was wrong.
- Related-articles markup and the "Key terms" section are still unverified.
- 105 images were downloaded for these checks (8% of the total), to the scratch folder, not the repo.
