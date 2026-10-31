# FR-9: Evaluation set — decisions

Status: 28 questions, checked against the cleaned corpus by script and marked `verified` on 2026-10-31 on the project owner's instruction, **without a question-by-question human review** (drafted with AI assistance; a 11-question spot-check sheet was prepared and skipped by choice). The report must say so. The metrics, judge and runner are built (see "Metrics and runner"); the dev split and the test split have each been run (the test split once).

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
After review, set `status` to `verified` and do not edit the file to improve scores. (Done on 2026-10-31 without an individual review, as noted at the top.) Changes after seeing results need a new version. The `test` split is used once, for the final report.

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

## Dev run 1 (2026-10-31, run `20261031-090645-dev`)

The 9 dev questions, run once on the baseline (answer prompt v4, judge prompt j1, top-k 8, dense retrieval only). Results are in
`data/evaluation/results/20261031-090645-dev/` (`review.csv` for manual checking). The question set was still "drafted".

| Measure | Result |
|---|---|
| Right answer or right abstention | 9/9 |
| Answerable questions answered / correct abstentions | 8/8 and 1/1 |
| Recall@1 / @3 / @5 / @8 (9 evidence items) | 5/9, 7/9, 8/9, 9/9 |
| MRR / right article retrieved | 0.754 / 8/8 |
| Every key fact covered (judge) | 8/8 |
| Every claim supported (judge) | 6/8 (see the finding below) |
| Citations outside the expected or related list | 3 of 9 questions |
| Wall time per question | median 2.6 s, p90 5.9 s |
| Tokens / estimated cost | 45,248 / about $0.021 (planned $0.029) |
| Errors | 0 |

With 9 questions, mostly direct ones, this is a smoke test of the pipeline and the runner and says little about quality in
general. Retrieval is where the weakness shows: the right section is first for 5 of 9 and within the top 8 for all 9.

### Findings from reading the results

- **The judge's faithfulness check gave a false positive (eval-020).** It listed 9 "unsupported claims", but 8 of them are in the
  retrieved context (checked by searching the retrieved text for the Primary Matching Criteria menu, System Fields, Generate
  Audience, the file upload options and so on). Its comment shows it compared the answer with the key facts instead of with the
  documents, which the prompt had told it not to do. So "6/8 faithful" understates the answer; by hand, 7/8 is closer, because the
  other flag (eval-026: the answer adds that the field helps "link and verify data between IQM and other systems") is a fair catch
  of an embellishment. The judge prompt needs a grounded form of the check before the final run.
- **The citation metric is strict, not wrong-or-right.** "Wrong" means a cited URL is not in the question's expected or related
  list. Three answers cited extra articles. For eval-010 (Matched vs Segmented audiences) the extras are the audience overviews and
  the Vera article, which plausibly support a comparison; for eval-005 the extra is a Political Planner article whose text also
  covers restoring proposals. These need a manual look; the question file is not edited after seeing results, so the score stays as
  measured and the interpretation goes in the report.
- **Recall@1 misses:** eval-007 (rank 3), eval-010 (ranks 2 and 7 for its two required sections) and eval-026 (rank 5, a follow-up
  rewritten to ask about the field in the Creatives app, where the custom-tracking sections rank above the overview). All are within
  the top 8, so the answers were still correct.

### Judge fix and re-judge (2026-10-31, run `20261031-090645-dev-rejudge-j2`)

The false positive above was fixed in judge prompt `j2`: the judge now lists every factual claim in the answer, names the document
that supports each one and quotes it; a claim is unsupported only if no shown document is named. The prompt also says the key
facts are not the list of allowed claims. The 8 saved dev answers were judged again (8 judge calls, no new answers), into a new
run directory so the original stays as it was.

| | j1 (original) | j2 (re-judged) |
|---|---|---|
| Every key fact covered | 8/8 | 8/8 |
| Every claim supported | 6/8 | 7/8 |
| eval-020 | 9 "unsupported claims" (false positive) | 13 claims, all supported, quotes found |
| eval-026 | 1 unsupported claim | the same claim, correctly flagged |
| Claims judged / supported / quote found verbatim | n/a | 53 / 52 / 49 |

This matches the hand check (7/8). Three supported claims had a quote that was not verbatim in the named document (a loose quote,
not a missing claim); the verdict does not depend on the quote, and the count is reported. The judge is still the same model
family as the answerer; the manual columns in `review.csv` remain the check.

The question file's content hash now ignores the `status` field, so verifying the set does not change its identity; the first dev
run recorded a hash of the file bytes (`248fcb...`) from before this change.

## Test run (2026-10-31, run `20261031-100611-test`)

Run once on the verified set, after the judge fix, with no change afterwards. Results and analysis are in `docs/evaluation-report.md`;
the saved run is `data/evaluation/results/20261031-100611-test/` (`review.csv` for manual checking).

Headline: 19/19 right responses; 13/16 answers with every key fact; Recall@8 15/19 (Recall@1 9/19, MRR 0.74); every judged claim
supported (108/108); 10/19 questions cite only listed sources; median 2.5 s per question; about $0.054 estimated.

Main findings: retrieval ranking and navigation chunks (eval-021 failed because three of the top eight chunks were link lists and the
steps section was not retrieved), multi-section questions (2 of 5 evidence items), and over-citation (13 citations outside the
expected or related lists, 6 of which no judged claim relied on). The test split has now been seen, so a further retrieval
improvement would need new questions to be evaluated without bias.
