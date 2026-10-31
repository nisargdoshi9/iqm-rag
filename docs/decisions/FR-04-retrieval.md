# FR-4: Retrieval decisions

Status: decided and implemented (2026-10-30). `src/iqm_rag/retrieval/retriever.py`, `scripts/retrieve.py`,
`tests/test_retrieval.py`. Retrieval quality was measured with the evaluation set; see `docs/evaluation-report.md` (test split: Recall@8 15 of 19 evidence items, Recall@1 9 of 19).

## What retrieval does

`Retriever.retrieve(query, top_k=None)` embeds a query string with the same model that built the index, finds the
`top_k` closest chunks in Chroma and returns them with scores and diagnostics. It does not call an LLM, does not look
at chat history and does not decide whether a question can be answered. Answer generation, follow-up handling and
citations sit on either side of it and only use its output.

## Decisions

| # | Decision | Value |
|---|---|---|
| 1 | Method | Dense vector search only. Hybrid (BM25 plus dense) and a reranker are not in the baseline; both are logged as later experiments |
| 2 | Number of chunks | `top_k = 8` by default; set with `RETRIEVAL_TOP_K` (1 to 50) or per call. Re-evaluate once the full evaluation set is run |
| 3 | Scores | Each hit carries Chroma's cosine distance and `similarity = 1 - distance`. Retrieval does not abstain: the answer step decides from the evidence, with at most a loose similarity floor |
| 4 | Duplicates | No per-article cap. Citations are de-duplicated by URL when the answer is built, and split parts of one section can be stitched together in order when the context is built (both belong to the generation and citation tickets) |
| 5 | Follow-up questions | Resolved before retrieval by an LLM rewrite into a standalone question (generation ticket): skipped on the first turn, falls back to the raw question if the call fails, and both queries are traced. The retriever stays history-agnostic |
| 6 | Collection overview pages | Kept in the index for now (94 of 2,310 chunks, 9 articles, mostly "All articles" listings). Revisit after the evidence-hit-rate check; a metadata filter or index-time exclusion is easy to add |
| 7 | Shape | A typed `Retriever` class over Chroma. The query is embedded as plain text (the context header is only added to chunks). Startup refuses a missing or empty index, another embedding model, and a query vector of the wrong dimension |

## Results returned

`RetrievalResult`: the query used, `top_k`, embedding model, query tokens, embed and search time in milliseconds, and
`hits`. Each `RetrievedChunk` has `rank` (1 is closest), `distance`, `similarity` and the stored chunk: text, article
ID, title and URL, section path, section IDs, `media_section_ids`, part and parts, last-updated date. `to_dict()` gives a
JSON-ready form for tracing. Limits: the query is trimmed; an empty query or one over 2,000 characters is rejected
(never truncated silently); `top_k` outside 1 to 50 is rejected. Asking for more than the index holds returns all of it.

## Evidence behind the choices (exploratory)

Run on the 8 dev-split questions only; the 17 test questions were not touched. A small sample: it informs the
defaults and proves nothing.

- Answerable questions: the evidence section was in the top 3 for all 7. Single-evidence questions ranked it 1st, except
  the win-rate question at 3rd.
- Multi-section question (matched vs segmented audiences): its two evidence sections ranked 2nd and 7th, which a top-5
  would have cut in half. This is the reason for 8.
- Abstention: the unanswerable TikTok question's best match had distance 0.496; the answerable win-rate question's best
  match had 0.518. A distance cut-off cannot separate them, so scores are signals, not the abstention rule.
- Collection overview pages took 2 of the top 5 on one question.
- One follow-up question ("those scheduling settings") already found its section at rank 1 raw. Prepending the previous
  question improved the distance from 0.298 to 0.246, an easy case that does not settle the choice of method.
- One live query on the full index (a weekly emailed report question): the correct section ranked first at
  similarity 0.608, followed by sibling sections and the scheduling sections of the PLD, ICT and NLD report articles,
  which are near-copies of each other.

## Follow-up handling: options considered

| Option | Retrieval query | Outcome |
|---|---|---|
| Raw question | the follow-up alone | Fails on pronouns ("those settings") |
| Concatenate previous user questions | previous question(s) plus current | Free and simple; a topic switch pulls in stale context, and a chain of pronoun questions loses the root topic if only one is kept |
| Add the previous answer or cited titles | previous question, answer or titles, plus current | No source found supporting it; long answers dilute the query. Not used |
| LLM rewrite (chosen) | one standalone question | The usual approach in the sources read (NVIDIA RAG Blueprint docs, practitioner guides). Handles pronouns, chains, topic switches and references to the previous answer. Costs one small call per follow-up turn |

Sources: NVIDIA RAG Blueprint multi-turn docs (simple mode concatenates previous user queries only; rewriting is
recommended when accuracy matters); a SemEval-2026 Task 8 system paper (last turn joined with an LLM rewrite beat
either alone, one paper); a question-rewriting paper for conversational QA (automatic rewrites still lag human ones);
practitioner posts on topic dilution. History kept for the rewrite and for generation is a few recent exchanges
(a named constant in the generation ticket), not summarised memory.

## Open items

- Link-list chunks: 201 of 2,310 chunks (8.7%, 185 articles) are more than 60% link text, mostly "Locate additional ...
  resources" sections with no answerable content. In one live query ("how to manage creatives overview") two of the
  top 8 were such chunks and a third was a collection summary. None of the 26 evaluation evidence sections is a
  link-list chunk. Options: leave, drop at index time, or tag in metadata and filter at query time (preferred, since it
  can be compared). Deferred; decide together with the collection-overview pages (decision 6) using the hit-rate check.

- Evidence-hit-rate check on the full evaluation set (no LLM calls): confirms or changes `top_k`, compares small vs
  large embeddings, and shows whether overview pages or tiny intro chunks crowd out evidence.
- Hybrid search and a reranker: only if the hit-rate check shows relevant chunks retrieved but ranked too low.
- Compare follow-up retrieval with and without the rewrite on the evaluation set's follow-up questions.
