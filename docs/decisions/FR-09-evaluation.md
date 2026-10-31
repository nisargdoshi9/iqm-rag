# FR-9: Evaluation set — decisions

Status: 28 questions drafted and checked against the cleaned corpus. **Not yet reviewed by a human; not frozen.** The metrics, judge and runner are built (see "Metrics and runner"); no evaluation has been run yet.

## Decisions
1. **Size:** 28 questions (the assignment minimum is 15). Three follow-up questions were added after the conversation design (below).
2. **Categories (count):** direct factual (3), procedural (3), list or multi-condition (3), multi-section or multi-source (3), follow-up with history (6), unanswerable (4), similar-but-wrong article (3), table lookup (3). Media is a field (`expected_media`) on two questions, not a category.
3. **Expected evidence:** the article URL (needed for the citation check) plus the section heading and the section's content hash, so a later re-scrape cannot silently change what "correct" means.
4. **How questions were written:** plain, user-style wording drawn from the article text, not creative paraphrases. Each question carries the exact supporting quote.
5. **Reference answers:** a short expected answer plus a checklist of `key_facts` for judging correctness the same way each time.
6. **Unanswerable questions:** 3 plausible but undocumented (TikTok/Snapchat, Salesforce, SSO) and 1 off-topic (Google Ads). Each lists `absence_check` terms that were searched in the whole corpus and found zero times. `related_urls` holds near-miss articles that exist but do not answer.
7. **Follow-ups:** a scripted `history` (user and assistant turns) taken from the articles, so the test stays fixed.
8. **Split:** 9 `dev` questions for tuning chunk size and retrieval, 19 `test` questions for the final report. With so few questions the numbers are rough, and the report should say so.

## File format (`data/evaluation/questions.jsonl`)
One JSON object per line: `id`, `category`, `split`, `question`, `history`, `expected_answer`, `key_facts`, `expected_source_urls`, `evidence` (article_id, url, section_heading, section_content_hash, quote, required), `should_abstain`, `related_urls`, `absence_check`, `expected_media`, `similar_to_urls`, `notes`, `status`.

- `expected_source_urls` lists the sources an answer must be able to cite. An evidence item with `required: false` is an alternative source that also supports the answer.
- A multi-source question has several required evidence items; the answer must draw on all of them.

## Checks
`python -m iqm_rag.evaluation.dataset` checks that each quote is found in its cited section, the section hash still matches the corpus, unanswerable terms are absent, follow-ups have valid history, and there are at least 15 questions. All 28 pass.

## Freeze rule
After review, set `status` to `verified` and do not edit the file to improve scores. Changes after seeing results need a new version. The `test` split is used once, for the final report.

## Known limits
- Drafted from the article text with AI assistance and checked by script; a human review of every question is still pending.
- The Help Center was scraped on 2026-10-29. Articles may change later; the section hashes show when that happens.
- Two table questions (Bid Modifier eligibility and the ad-spec rows) test whether table content survives chunking.

## Follow-up questions added with the conversation design

The first three follow-up questions each had one prior exchange and a pronoun, which cannot tell a good query rewrite
from a poor one. Three were added to cover the other cases, all drafted with AI assistance and checked by the validator:

| Id | Split | Case |
|---|---|---|
| eval-026 | dev | Refers to something only the previous answer mentioned ("the 3rd Party ID field you mentioned") |
| eval-027 | test | Two-step chain: the topic is two turns back and the question has only a pronoun ("cancel it for good") |
| eval-028 | test | Topic switch: the history is about report scheduling and the new question is about image creatives |

Even so, six follow-up questions are few; results on them are indicative only.

## Metrics and runner (decided 2026-10-31)

| # | Decision | Value |
|---|---|---|
| 1 | How a question is run | Through the same chain as the chat page, once, with the question's scripted history. Traces are tagged `eval`, the run ID, the question ID, the split and the category |
| 2 | Retrieval metrics | A retrieved chunk counts as the evidence if it is from the right article and contains the evidence quote (markdown marks and whitespace ignored). Reported: Recall@1, @3, @5, @8 (share of required evidence found), MRR (rank of the first evidence found), and whether the right article was retrieved at all. For follow-ups the query actually searched, after the rewrite, is used. Abstention questions have no evidence and are left out of retrieval metrics |
| 3 | Abstention (deterministic) | Should abstain and said `not_covered`: correct. Answerable and said `answered`: passes. Other outcomes are named: `wrongful_abstention`, `invented_answer`, and `clarified_instead` / `over_clarified` (a clarifying question counts as neither a pass nor an invented answer) |
| 4 | Citations (deterministic) | Precision: cited URLs that are expected, related or alternative evidence. Recall: expected URLs cited. Any citation on an abstention is wrong |
| 5 | Answer correctness and faithfulness | An LLM judge (`gpt-4.1-mini`, setting `JUDGE_MODEL`, temperature 0, prompt `j1`) marks each key fact covered or not and lists claims the retrieved documents do not support. Only answered, answerable questions are judged. A judge failure or a wrong number of fact checks is recorded as an error, never as a score |
| 6 | Judge prompt | Written to be strict and unbiased: judge substance only (not length, tone or confidence), do not assume plausibility means correct, partial or hedged statements are not covered, no credit for facts that appear only in the reference answer, and any claim the documents do not support is listed even if true in the real world |
| 7 | Manual review | `review.csv` puts the question, history, expected answer, key facts, the bot's answer, status, cited and expected URLs, evidence rank, top retrieved sections, the judge's per-fact notes, unsupported claims and comment side by side, with empty `manual_verdict` and `manual_notes` columns. It opens in Excel or Sheets |
| 8 | Run procedure | Dev run first (debugging, failures may be inspected); the test run once per dataset version on a verified set. The runner refuses the test split on unverified questions and refuses a second test run for the same dataset hash unless told otherwise (and records that) |
| 9 | Saved per run | `data/evaluation/results/<run-id>/`: `config.json` (models, prompt versions, top-k, index size, dataset hash and statuses, git commit, tracing), `results.jsonl` (one full record per question), `review.csv`, `summary.json`, `summary.md` |
| 10 | Cost | Tokens exactly as reported; cost computed from stated prices (gpt-4.1-mini $0.40 / $1.60 per million input/output tokens, text-embedding-3-large $0.13), which reproduce LangSmith's own estimates for the same calls; labelled an estimate. A model with no listed price gives no cost, never a guess |

### Using it

```
python scripts/evaluate.py --split dev --dry-run     # plan, call counts, rough cost, checks; no API calls
python scripts/evaluate.py --split dev --yes         # the model calls happen only with --yes
python scripts/evaluate.py --rebuild <run-dir>       # rebuild summaries and the CSV from saved results; no API calls
```

The dry run on 2026-10-31: dev is 9 questions (9 answers, 2 rewrites, up to 8 judge calls, about 61k tokens, about $0.03); the
whole set is 28 questions (up to 62 model calls, about 186k tokens, about $0.09). All 28 evidence quotes were found in the
chunks, so recall below 100 percent would be a retrieval miss, not a matching artefact.

### Limits of the method

- The judge is a model of the same family and size as the answerer, so it can share its blind spots; the manual columns in
  `review.csv` exist so that a sample of its verdicts can be checked, and the agreement will be reported.
- With 9 dev and 19 test questions, every figure is a handful of cases. Counts are shown next to percentages, and no figure is
  claimed to be statistically conclusive.
- Recall is measured on the retrieval step as built (top 8, dense only); quote matching means a section split across two
  chunks counts as retrieved only if the chunk holding the quote was retrieved.
