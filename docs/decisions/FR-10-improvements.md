# Improvements after the first test run: decisions

Status: decided, implemented and measured (2026-10-31). Code: `src/iqm_rag/retrieval/{keyword,fusion,rerank,pipeline}.py`,
`src/iqm_rag/ingestion/chunking.py`, `src/iqm_rag/generation/{prompts,smalltalk,chain}.py`, `scripts/compare_runs.py`.
Results: `docs/evaluation-report.md` (section "Improvements and the held-out ablation").

## Why this work, and how it was kept honest

The first test run (baseline: dense search, prompt v4) showed three weaknesses: link-only chunks crowding out content (eval-021),
multi-section questions retrieving 2 of 5 evidence items, and over-generous citations. The test split had then been seen, so any fix
chosen from its failures could not be validated on it. Before changing anything we wrote **16 new questions** (`data/evaluation/holdout.jsonl`,
split `holdout`, drafted from articles the first 28 questions do not use, checked against the corpus by script and verified by the project
owner). The runner treats the holdout like the test split: verified questions only, and **one run per dataset version and retrieval
configuration**. Fixes were developed against the dev and already-seen test questions; the four configurations compared on the holdout were
fixed in advance, and no setting was changed after seeing holdout results.

## Decisions

| # | Decision | Value and reason |
|---|---|---|
| 1 | Navigation sections | A section made only of one-link list items (the "Locate additional ... resources" lists) is dropped before chunking: 182 sections, 2,310 to 2,131 chunks. A sentence such as "Refer to [X] for steps" is real content and is kept. Dropped at chunk time (not tagged) because the index syncs by chunk ID, so only 3 chunks needed re-embedding |
| 2 | Citations | Prompt `v5`: cite the fewest documents that together support every statement, most important first. On dev, citation precision went 0.80 to 0.94; on the seen test split 0.70 to 0.77 |
| 3 | Small talk | Whole-message rules (greeting, thanks, goodbye, "ok", "what can you do"): no search and no model call, a fixed reply, status `smalltalk`. A message that is more than small talk goes through the normal chain. Rules over an intent model because the failure to avoid is a "not in the Help Center" reply to "hi", and rules cost nothing |
| 4 | Hybrid search | BM25 (`rank_bm25` 0.2.2, own tokenizer: lowercase alphanumerics, stopwords dropped, no stemming) over the same chunks plus dense search, 30 candidates each, merged by reciprocal rank fusion (k = 60). Kept in memory, built from the chunks stored in Chroma. `rank_bm25` is the standard small library; it is unmaintained since 2022 and slower than `bm25s`, which does not matter at 2,131 chunks |
| 5 | Reranker | An LLM reranker (`gpt-4.1-mini`, one listwise call over the 30 fused candidates, returns the best 8) behind a `Reranker` interface, so a cross-encoder or a hosted rerank API can replace it. On any failure the fused order is kept and a warning is recorded. Chosen over a local cross-encoder (torch and a model download) and a hosted API (another key) so a reviewer needs nothing new |
| 6 | Neighbour expansion | Adds the adjacent parts of any split section among the top 8 to the model's context (at most 8 chunks). The ranking, and so Recall, is unchanged; a new metric, "evidence in the model's context", measures it |
| 7 | Switches | `RETRIEVAL_MODE` (dense or hybrid), `RERANK` (off or llm), `NEIGHBOURS`, `RETRIEVAL_CANDIDATES`, `RERANK_MODEL`; the evaluation script takes matching flags and every run records its configuration |
| 8 | Shipped default | **Hybrid search with the LLM rerank, neighbours off**, set from the held-out results below. `RETRIEVAL_MODE=dense RERANK=off` restores the baseline |

## Held-out ablation (16 questions, 19 evidence items, one run per configuration)

| Configuration | Recall@1 | Recall@3 | Recall@8 | MRR | Evidence in context | End-to-end correct | No wrong citation | Median s | Cost per question |
|---|---|---|---|---|---|---|---|---|---|
| dense | 6/19 | 13/19 | 16/19 | 0.63 | 16/19 | 13/14 | 8/16 | 2.2 | $0.0031 |
| hybrid | 7/19 | 12/19 | 16/19 | 0.69 | 16/19 | 12/14 | 8/16 | 2.3 | $0.0031 |
| hybrid + LLM rerank | 11/19 | 17/19 | **19/19** | **0.83** | **19/19** | 13/14 | 8/16 | 3.3 | $0.0059 |
| hybrid + LLM rerank + neighbours | 11/19 | 18/19 | 19/19 | 0.83 | 19/19 | 13/14 | 9/16 | 3.3 | $0.0061 |

(Cost includes the judge call. End-to-end counts the answered answerable questions the judge could assess: 14 of 16.)

What it shows, and what it does not:

- **The reranker is the improvement.** It raised Recall@8 from 16 to 19 of 19 and Recall@1 from 6 to 11 (MRR 0.63 to 0.83), and rescued
  two questions whose evidence dense search had missed (hold-008, hold-012). It nearly doubles the cost per question and adds about one second.
- **Hybrid search alone did not help here.** Recall@8 was unchanged and MRR rose 0.06, but Recall@3 fell by one item and one more answer
  missed its key facts (hold-012). With 16 questions these differences are within noise; it is kept because the reranker needs its extra candidates (keyword hits that vector search ranks low).
- **Neighbour expansion showed no measurable gain** (evidence in context was already 19/19 without it), so it is off by default. The seen test split
  gave the same result.
- **Better retrieval did not change answer quality much:** 13 of 14 answers covered every key fact with or without the reranker, because the dense
  baseline already answered most of these questions. The larger answer-quality effect is for questions like hold-008 and hold-012, and the set
  is too small to prove it.
- **The reranker is not perfectly repeatable.** Two runs that differ only in neighbours (which does not change the ranking) have Recall@3 of 17 and 18:
  one item of 19, at temperature 0.
- A development check of the full configuration on the already-seen test split gave Recall@8 19/19, MRR 0.86 and end-to-end 14/16,
  against 15/19, 0.74 and 13/16 for the baseline. That split was used to build the fixes, so it is not a clean figure.

## Known remaining problems

- **Cross-references inside a procedure (hold-011).** The existing-campaign steps of Campaign Estimations end with "follow steps 7 through 10 of the new
  campaign workflow". Both sections were in the model's context, but the answer repeated "follow the steps from step 7" instead of writing them out, so 2 of 3
  key facts were missing, with every configuration. A prompt rule to expand such references would be the fix; it was **not** applied because the holdout
  results are frozen and a fix tuned on this question could not be measured fairly.
- **Citations are still over-generous:** 8 to 9 of 16 holdout questions cite an article outside the curated list (mostly related articles, such as a
  troubleshooting page). Prompt v5 improved it but did not remove it.
- The reranker is a language model: it adds cost and latency, and its output order can vary slightly between runs.

## Not done

Streaming answers, feedback thumbs, saved chats, media display, a cross-encoder or hosted reranker, and a stronger judge. See `docs/evaluation-report.md`.
