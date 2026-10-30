# FR-3: Chunking decisions

Status: chunking strategy, embedding model and vector store decided (2026-10-30). The chunker is written and run
(see "Implementation"); the embedder and Chroma indexer are written and
run (see "Embedding and indexing"). SPECS.md numbers (500-700 token target, 50-100 overlap) were treated as hypotheses only, not constraints.

## Embedding model and vector store (decided by the project owner)

| Decision | Value |
|---|---|
| Embedding model | OpenAI `text-embedding-3-large`, full 3,072 dimensions. Configurable through `EMBEDDING_MODEL`; the name and dimension are stored with the index so a change is detected |
| Vector store | Chroma (persistent local client), cosine distance set explicitly |
| Answer LLM | OpenAI (exact model chosen later) |
| Chunk cap | Stays at 700 tokens (the model accepts about 8,191), minimum 150 |

Why large and not small (answer if asked): at our size (about 0.55M tokens, roughly $0.07 vs $0.01 by my estimate,
prices from third-party catalogue pages) the price gap is cents, so the more capable model was chosen to rule the
embedding model out as a cause of weak retrieval. OpenAI's launch numbers put English retrieval (MTEB) at 62.3 for small
and 64.6 for large, a modest gap of about 2.3 points, so no big gain is claimed. The corpus has near-identical sibling
sections (Creatives app vs Campaigns app) and product jargon, where a larger vector may separate close cases better,
but that is unmeasured. Not yet tested on our data; the evidence-hit-rate check can compare small vs large cheaply.

Why a hosted model: the owner has OpenAI credits and the answer model is OpenAI too, so one key covers both. The
alternative considered was a local bge-small-en-v1.5 (no key, but a 512-token input limit would force a cap of about
450 tokens: 110 sections split instead of 36). all-MiniLM-L6-v2 (256-token limit) would have split 526 sections and was
ruled out. Chroma was chosen over FAISS (no persistence or metadata filtering, so we would build them) and Qdrant
(server-style, more than about 2,150 vectors need). Chroma upserts and deletes by ID, which fits deterministic chunk IDs
and content-hash skipping. Hosted embeddings mean user questions also go to OpenAI (public Help Center content,
private user questions); mention in the write-up.

Setup (done 2026-10-30): key in the git-ignored `.env`, clean `.venv`, pinned `openai`, `chromadb`, `python-dotenv`.
`scripts/check_openai.py` embedded 3 test strings: 3 vectors of 3,072 dimensions, 22 tokens.

## Decisions (made by the project owner)

| # | Decision | Value |
|---|---|---|
| 1 | Strategy | Section-based chunking with rules ("option C" below) |
| 2 | Size limits | Merge small sections up to a **minimum of about 150 tokens**; **single maximum of about 700 tokens**. Oversized sections are split into k = ceil(size / 700) pieces of similar size, so there are no orphan scraps. No separate soft/hard cap |
| 3 | Overlap | None between whole sections. On split pieces of plain text and lists only, repeat the previous piece's last unit if it is about 50 tokens or less. Not for tables (repeat the header row instead) and not for FAQs (split only between Q/A pairs) |
| 4 | Context header | Embedded text is `Article title > heading path` followed by the content |
| 5 | Comparison of chunking variants | Skipped for now; justified from the data. An "evidence hit rate" check comes later (see Open items) |

All sizes are estimated as characters / 4. A real tokenizer comes with the embedding model choice.

## Data analysis (cleaned corpus, 200 articles)

- About 500k tokens in total. Median article about 2,100 tokens, p90 about 4,300, max about 15,000. Only 6 of 200
  articles fit in 700 tokens, so whole-article chunks are not an option.
- 2,977 sections, of which 2,680 contain text. 256 are bare parent headings (their body lives in child sections)
  and 41 contain only a video.
- Content sections: median about 140 tokens, p90 about 330. 89 are over 500 tokens, 37 over 700, 15 over 1,000.
- The oversized ones are mainly large tables (DoubleVerify segment tables, up to 73 rows and about 7k tokens) and
  FAQ sections of Q/A pairs (one has 65 paragraphs, about 3.6k tokens).
- 40 sections have text but are under 30 tokens (one-sentence sections).
- Evaluation evidence sections (26 across the 25 questions): median about 210 tokens, 3 above 450, max about 850.
- Sibling sections can be near-identical, for example "...from the Creatives app" vs "...from the Campaigns app".
  The heading path is the only difference, which is the main reason for the context header.

Conclusion: the data is already structured and its natural answerable unit (about 140 tokens) is far below the
500-700 token hypothesis in SPECS.md.

## Options considered

- **A. Fixed windows (for example 500 tokens, 80 overlap).** Simple, about 1,000 chunks, but cuts through procedures
  and Q/A pairs and ignores the structure built in FR-2. Remains a useful baseline.
- **B. One chunk per section, unchanged (about 2,680 chunks).** Aligns with citations and media IDs, but tiny and
  giant chunks hurt retrieval.
- **C. Section-based with rules (chosen).** See the algorithm below.
- **D. Parent-child ("small to big").** Deferred, see below.
- **E. Semantic or LLM-assisted chunking.** Not chosen: costs tokens, non-deterministic, little to gain on pages that
  are already structured.
- **Recursive text splitter (for example LangChain's).** Not used as the main strategy. It re-guesses structure from
  blank lines, which we already have exactly. Our approach is the same idea (split by progressively smaller
  boundaries) applied to the real tree: section, block, then list item / table row / Q-A pair, and sentence
  splitting only as a last resort for a single enormous paragraph (expected to be rare).

## Algorithm (option C)

1. The base unit is the leaf section from FR-2's structured output, not the derived Markdown. Parent headings with no
   body are never chunks; they only appear in the heading path.
2. Break each section into atomic units, which are never cut through: a paragraph or callout, one list item, one
   table row, or one FAQ question together with its answer.
3. Merge small neighbours: a section under the minimum is joined with the next sibling (same parent, directly
   after it) until the chunk reaches the minimum or the siblings run out. Never merge across different parents.
   Each merged part keeps its own heading line in the text, and the chunk metadata lists all its section IDs.
4. Split only sections over the maximum, at unit boundaries, into evenly sized pieces. A table piece repeats the
   header row and lead-in sentence. A list piece repeats the intro sentence. An FAQ splits only between Q/A pairs.
5. Prepend the context header (decision 4).
6. Metadata: the SPECS schema fields plus section ID(s), part number, `content_hash`, `last_updated` and the media
   IDs from FR-2 for the display plan. Chunk IDs are deterministic (`{article}:{section}:{part}`) so unchanged
   content can skip re-embedding.
7. Video-only sections are not indexed; the video attaches to the neighbouring chunk.

### Worked example: article 10344341 (Import IQM campaign data into Google Looker Studio)

Under the parent "Manage a report": "Review a report" (about 43 tokens) and "Edit a date range" (about 86) merge into
one chunk of about 117. "Choose a preset theme" and "Customize a preset theme" merge into about 123. Larger sections
such as "Edit a chart's properties" (about 231) stay alone. Heading-only sections ("Edit a data visualization...") are
not chunks. This article produced 14 chunks, mean about 149 tokens, median about 127, range 53-326 (at a minimum of
120).

Known weakness of the mechanical merge rule: "Delete a data visualization (chart)" and "Style the report" share a
parent but are different topics, so they merged into a 53-token chunk. It is harmless (each keeps its own heading
line) but loose. A stricter rule is possible but there is no evidence yet that it would help.

Split example: "Bid Modifier FAQ" (article 10873926), 19 Q/A pairs, about 1,640 tokens, becomes 4 pieces of about
440, 510, 550 and 150 tokens, each cut falling between two Q/A pairs.

### Prototype results (whole corpus, rough simulation, throwaway script, not in the repo)

| Minimum | Chunks | Median | p90 | Max | Under 60 tokens | Sections split |
|---|---|---|---|---|---|---|
| 120 | 2,275 | 181 | 382 | 696 | 174 | 36 |
| **150 (chosen)** | **2,150** | **196** | **398** | **696** | **168** | **36** |

Raising the minimum from 120 to 150 changed little. About 168 chunks stay under 60 tokens at either setting because
they are lone short sections with no same-parent neighbour to merge with, so the minimum alone does not remove the
tiny tail. See open items.

## Online research (searched 2026-10-30; mostly vendor blogs, no controlled study of our situation)

- No authoritative benchmark settles the best chunk size; it depends on the task. The peer-reviewed CRUD-RAG
  benchmark (64/128/256/512 tokens) concluded that different tasks have different best sizes, with 256 best for its
  two-document QA setting. NVIDIA's study (128 to 2,048 tokens) found page-level chunking best on its data.
- Practitioner guidance: 128-256 tokens suit fact-based lookups where precise matching matters; 256-512 suit tasks
  needing broader context. Microsoft Azure's starting point is 512 with 25% overlap. A February 2026 FloTorch
  benchmark (as summarised by PremAI) gives 256-512 with 10-25% overlap as the practical starting range.
- Very small fragments hurt: in that benchmark, semantic chunking produced fragments averaging 43 tokens and
  they scored only 54% end-to-end accuracy (different method from ours, but a warning about tiny chunks).
- Prepending the heading path or document title to each chunk is widely recommended, especially for the "right
  article, wrong section" case. This is practitioner reasoning, not a controlled test. One source states it found
  no published benchmark isolating heading-based chunking.
- Late chunking (Jina) shows that chunks embedded in isolation can lose neighbouring context, and that long passages
  compressed into one vector can dilute meaning. Our mitigations are the context header and top-k retrieval.
- Overall: heading-aware splitting plus a title/heading prefix is a sensible default; the sources agree the setting
  must be measured on one's own corpus.

Reading for us: a typical chunk of about 150-200 tokens sits at the low end of the fact-lookup range and is
plausible for short, self-contained how-to sections. Going to 256+ just to match generic advice would mean merging
unrelated how-to sections. The minimum of 150 sits at the bottom of the commonly cited band.

Sources:
- CRUD-RAG benchmark: https://arxiv.org/pdf/2401.17043
- NVIDIA, finding the best chunking strategy: https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/
- PremAI, RAG chunking strategies 2026 benchmark guide: https://blog.premai.io/rag-chunking-strategies-the-2026-benchmark-guide
- DEV, chunking strategies that survive production: https://dev.to/numb_code_07/rag-chunking-strategies-that-survive-production-beyond-the-512-token-default-1hkk
- Late chunking paper: https://arxiv.org/pdf/2409.04701v2
- Jina, late chunking: https://jina.ai/news/late-chunking-in-long-context-embedding-models/

## Implementation (chunker, 2026-10-30)

Code: `src/iqm_rag/ingestion/chunking.py`, run with `python scripts/chunk.py` (reads `data/processed/`, writes
`data/chunks/chunks.jsonl` and `chunking_report.json`, no network). Tests: `tests/test_chunking.py` (84 tests in the
suite pass).

Result on the real corpus (200 articles, sizes estimated as characters / 4):

| Chunks | Median | p90 | Max | Merged chunks | Sections split | Chunks under 60 tokens |
|---|---|---|---|---|---|---|
| 2,310 | 194 | 406 | 691 | 376 | 37 | 142 |

Chunk fields: the SPECS schema (`chunk_id`, `article_id`, `article_title`, `article_url`, `collection`,
`section_path`, `chunk_index`, `text`, `content_hash`) plus `section_ids`, `media_section_ids`, `part`/`parts`,
`context_header`, `token_estimate`, `last_updated`. The embedded string is `context_header + "\n\n" + text`
(`embedding_text()`), and `content_hash` is the hash of that string. Chunk ID format `{first_section_id}:p{part}`.
36 chunks carry the ID of a neighbouring media-only section in `media_section_ids` so its video can be shown.

Behaviour worth knowing:
- **The maximum is a hard limit on the final chunk text.** My first version let pieces overshoot (up to 905 tokens)
  because the repeated heading, list intro or table header, and the overlap unit were not counted. The packing budget
  now subtracts them, and the real corpus tops out at exactly 700. Found by inspecting the largest chunks, not by a
  test, so a regression test now covers it.
- **Content check:** all 11,353 units (paragraphs, list items, table rows, Q/A pairs) in the corpus appear in some
  chunk (compared on the first 80 characters). No unit exceeds 400 tokens, so the last-resort sentence cutting never
  fires on this corpus.
- Splits repeat the section heading; a list piece that starts mid-list repeats the intro sentence and keeps the
  original item numbers; table pieces repeat the header row; FAQ pairs are never separated.

Decisions on the findings (owner, 2026-10-30):
1. **Top-level merging: stopped (applied).** 138 of 514 merged chunks had joined top-level sections, which only share
   the article as their "parent" (for example "Assign a Contextual audience to a campaign" with "Locate additional
   Contextual audience resources": a how-to blended with a link list, labelled with the title only). Top-level
   sections now never merge; only sections under a real shared heading do. Measured effect: chunks 2,168 to 2,310
   (+142), chunks under 60 tokens 111 to 142 (+31), merged chunks 514 to 376. Chosen because a blended vector is the
   precision problem chunking is meant to avoid, and the cost is a few cents of embedding.
2. **Tiny parent intros: left as is, to be revisited.** 142 chunks are under 60 tokens, mostly one-sentence intros to
   a subsection whose children have a different parent (example: "Expand the drop-down arrow next to a question to
   reveal the answer." as a 19-token chunk). Merging an intro into its first child was rejected for now because the
   intro describes all children, not only the first. Revisit with the evidence-hit-rate check (open items): if these
   intros crowd out real answers in the top-k, add the merge then.
3. **Mechanical merges** such as "Delete a chart" + "Style the report" (described above) remain; harmless because each
   part keeps its heading line.

## Embedding and indexing (2026-10-30)

Code: `src/iqm_rag/ingestion/embeddings.py` (OpenAI embedder), `src/iqm_rag/ingestion/indexing.py` (Chroma), run with
`python scripts/chunk.py` then `python scripts/index.py` (`--dry-run` plans without API calls or writes, `--rebuild`
re-embeds everything). Tests: `tests/test_indexing.py` (14 tests, fake embedder and a throwaway Chroma folder, no
network). Index location `data/index/chroma` (untracked, regenerable), run report `data/index/index_report.json`.

First real run: 2,310 chunks, 24 batches of up to 100, model `text-embedding-3-large`, dimension 3,072, 480,738 tokens
billed (about $0.06 at the third-party-reported price of $0.13 per 1M tokens; the dry-run estimate of 553k tokens was
about 15% high), about one minute. A re-run embeds nothing (2,310 unchanged).

Behaviour:
- **Cosine distance** is set explicitly on the collection. Chroma's collection stores the embedding model name.
- **Incremental:** each record stores the content hash of the embedded text (header + text). A run embeds only new or
  changed chunks, upserts them by chunk ID (no duplicates), and deletes stored chunks that no longer exist.
- **Resumable:** each batch is stored as soon as it is embedded. A failure keeps earlier batches and a re-run
  continues (tested: failing the third of three batches leaves 200 of 250 stored, the re-run embeds the remaining 50).
- **Model and dimension changes are refused** with a message pointing at `--rebuild`, instead of mixing vectors from
  different models. Chroma also rejects a wrong dimension on its own.
- **Metadata** is scalar-only: list fields are stored as JSON strings and decoded by `record_to_chunk()`, which
  rebuilds the full chunk for retrieval. The collection is created without a Chroma embedding function, so Chroma never
  downloads or runs a model of its own; we always pass our vectors.
- The OpenAI client retries rate limits, timeouts and 5xx errors (3 retries, 60 s timeout). Provider errors are
  wrapped in `EmbeddingError` with the batch size and model.

Smoke check (not an evaluation): three evaluation questions (VCR calculation, Daily Pacing update frequency, impression-
vs budget-based IO) embedded and queried against the index. The expected article appeared in the top 3 results for all
three (top distances 0.22, 0.40, 0.30). Three questions, retrieval only, one run: it shows the index works, it does not
measure quality. The evidence-hit-rate check on the full set is still to do (open items).

## Why these values are a starting point, not a proven optimum

The values come from our data distribution plus general guidance. Nothing has been measured on retrieval yet. The
minimum (150), maximum (700) and overlap (50) are all named config constants so they can be tuned once the
evaluation runs. If the dev questions show misses caused by chunks that are too small or too large, change the knob
and report it in the write-up. Do not describe these values as optimised.

## Parent-child ("small to big"): deferred

Not guaranteed to help. The leaf section is already the answerable unit (median about 140 tokens) and the next level
up, the article, is far too large. The only realistic gain is for the about 36 split sections. It also risks pulling
in a near-identical sibling (Creatives vs Campaigns app), which hurts similar-but-wrong questions, and adds context
tokens and vaguer citations. SPECS.md has no guidance on it (its bonus lists only hybrid search, re-ranking and
query rewriting). Hook kept: every chunk stores `section_id` and `part`, so "expand to the whole section" is a
retrieval-time lookup that needs no re-index. Build it only if evaluation failures show answers cut at split
boundaries.

## Likely evaluator questions

- Why this chunk size? Median section about 140 tokens, only 3% over 500, evidence sections cluster at 100-300.
- Why no overlap between sections? Cuts are only at semantic boundaries, and the context header carries the heading.
- Why not a recursive splitter? We hold the structure, so we do not have to guess it.
- What if the answer spans two chunks? Top-k retrieval; the multi-source evaluation questions exercise this.
- How were tables and lists handled? Header-row repeat, intro-sentence repeat, and splits only between rows, items
  and Q/A pairs.
- Was it tested? Not yet beyond data analysis; see open items.
- What happens when a page changes? Content hashes and deterministic IDs let us re-embed only changed chunks.

## Open items

- **Come back to: evidence hit rate.** Once the index exists, measure for each evaluation question whether its
  evidence section appears in the top-k results. It needs no LLM calls. If the 120 and 150 variants differ, use it in
  the write-up. Owner asked to revisit this later.
- Tiny intro chunks (142 under 60 tokens): see decision 2 above. Revisit after the evidence hit rate.
