# Evaluation report

Baseline system, measured on 2026-10-31. Everything below comes from the saved runs in `data/evaluation/results/`; none of it is
illustrative. **Read the limitations section before quoting any number**: the set is small (28 questions), it was not reviewed
question by question by a person, and the judge is a model of the same family as the answerer.

## Summary

- **Test split (19 questions, run once):** every question got the right kind of response (16 of 16 answerable questions answered, 3 of 3
  unanswerable questions correctly declined). 13 of the 16 answers covered every key fact, by the judge's count; every one of the 108 claims
  the judge checked was supported by the retrieved documents.
- **Retrieval is the weak point.** The right article was retrieved for all 16 answerable questions, but the evidence section was in the
  top 8 for 15 of 19 evidence items (79 percent) and ranked first for only 9 of 19 (47 percent). The misses explain the answer gaps.
- **Citations are over-generous.** For 10 of 19 questions the answer cited an article outside the expected or related list. For
  about half of the extra citations the judge attributed no claim to them.
- **Cost and speed:** median 2.5 s per question (p90 3.7 s), about $0.003 per question (an estimate), 103k tokens for the whole split.
- **Dev split (9 questions):** 9 of 9 right responses, 8 of 8 fully correct answers, Recall@8 9 of 9.

## What was evaluated

| Component | Setting |
|---|---|
| Corpus | 200 Help Center articles scraped 2026-10-29, 2,310 chunks |
| Retrieval | Dense only: `text-embedding-3-large`, Chroma (cosine), top 8, no reranking, no hybrid search |
| Follow-ups | LLM rewrite from the second turn (`gpt-4.1-mini`), last 3 exchanges |
| Answering | `gpt-4.1-mini`, temperature 0, structured output, prompt `v4`, citations mapped from context numbers to stored URLs |
| Judge | `gpt-4.1-mini`, temperature 0, prompt `j2` |
| Questions | 28 questions in 8 categories, 9 dev and 19 test, each with key facts, evidence quotes and expected sources |

## Method

- Every question goes through the same chain as the chat page, once, with its scripted history. Nothing is retried.
- **Retrieval:** a retrieved chunk counts as the evidence if it is from the right article and contains the evidence quote. Recall@k is
  the share of required evidence items found in the top k; MRR uses the first evidence found; "right article" asks whether any retrieved
  chunk comes from an expected article. Unanswerable questions have no evidence and are left out of retrieval figures.
- **Abstention:** a question that should be declined passes if the status is `not_covered`; an answerable one passes if it is `answered`.
- **Citations:** precision is the share of cited URLs that are expected, related or alternative evidence; recall is the share of expected
  URLs cited. A URL outside those lists is counted as "outside the list", which is stricter than "irrelevant".
- **Answer quality:** the judge marks each key fact covered or not and lists the answer's claims, each with the document that supports it. A
  claim is supported only if the judge names a document that was shown to the answerer. Only answered, answerable questions are judged.
- **Procedure:** the dev split was run first to debug the runner and the judge (and the judge prompt was fixed after reading those
  results, see below). The test split was run once, after the judge was fixed and the question set was marked verified. No change was made
  after seeing the test results.

## Results

### Test split (run `20261031-100611-test`)

| Measure | Result |
|---|---|
| Right answer or right abstention | 19/19 |
| Answerable questions answered / correct abstentions | 16/16 and 3/3 |
| Recall@1 / @3 / @5 / @8 (19 evidence items) | 9/19, 15/19, 15/19, 15/19 |
| MRR / right article retrieved | 0.74 / 16/16 |
| Every key fact covered (judge, 16 answers) | 13/16 (mean coverage 0.90) |
| Every claim supported (judge) | 16/16 (108 claims; the named quote was found verbatim for 102) |
| End-to-end correct (answered with every key fact, of 16 answerable) | 13/16 |
| Citation precision / recall (mean) | 0.70 / 1.0 |
| Questions with no citation outside the list | 10/19 |
| Wall time per question | median 2.5 s, p90 3.7 s |
| Tokens / estimated cost | 103,262 / about $0.054 |

Per category (small counts; the test split has 2 to 4 questions per category):

| Category | n | Passed | Recall@8 | End-to-end correct |
|---|---|---|---|---|
| direct_factual | 2 | 2/2 | 2/2 | 2/2 |
| follow_up | 4 | 4/4 | 4/4 | 4/4 |
| list_multi_condition | 2 | 2/2 | 2/2 | 1/2 |
| multi_section | 2 | 2/2 | 2/5 | 1/2 |
| procedural | 2 | 2/2 | 2/2 | 2/2 |
| similar_but_wrong | 2 | 2/2 | 1/2 | 1/2 |
| table_lookup | 2 | 2/2 | 2/2 | 2/2 |
| unanswerable | 3 | 3/3 | n/a | n/a |

### Dev split (runs `20261031-090645-dev` and `20261031-090645-dev-rejudge-j2`)

| Measure | Result |
|---|---|
| Right answer or right abstention | 9/9 |
| Recall@1 / @3 / @5 / @8 (9 evidence items) | 5/9, 7/9, 8/9, 9/9 |
| MRR / right article retrieved | 0.754 / 8/8 |
| Every key fact covered | 8/8 |
| Every claim supported | 7/8 with judge `j2` (6/8 with the first judge, `j1`, which gave a false positive) |
| Questions with no citation outside the list | 6/9 |
| Wall time per question | median 2.6 s, p90 5.9 s |
| Tokens / estimated cost | 45,248 / about $0.021 |

The dev split is a development set: reading its results led to the judge fix, so it is not an unbiased estimate. It is easier than the
test split (more direct questions; the harder multi-section and similar-but-wrong questions were mostly in test).

### Every test question

| Question | Category | Outcome | Evidence rank | Key facts (judge) | Claims supported | Citation outside list |
|---|---|---|---|---|---|---|
| eval-002 | direct_factual | answered | 1 | 1/1 | 1/1 | no |
| eval-003 | direct_factual | answered | 2 | 2/2 | 9/9 | yes (1) |
| eval-004 | procedural | answered | 1 | 4/4 | 8/8 | no |
| eval-006 | procedural | answered | 1 | 4/4 | 7/7 | no |
| eval-008 | list_multi_condition | answered | 1 | 4/4 | 5/5 | yes (3) |
| eval-009 | list_multi_condition | answered | 1 | 2/3 | 3/3 | yes (1) |
| eval-011 | multi_section | answered | 2, miss, miss | 3/4 | 9/9 | yes (2) |
| eval-012 | multi_section | answered | miss, 2 | 4/4 | 14/14 | yes (1) |
| eval-014 | follow_up | answered | 3 | 3/3 | 9/9 | yes (1) |
| eval-015 | follow_up | answered | 1 | 5/5 | 9/9 | yes (1) |
| eval-017 | unanswerable | correct_abstention | n/a | n/a | n/a | no |
| eval-018 | unanswerable | correct_abstention | n/a | n/a | n/a | no |
| eval-019 | unanswerable | correct_abstention | n/a | n/a | n/a | no |
| eval-021 | similar_but_wrong | answered | miss | 0/3 | 10/10 | no |
| eval-022 | similar_but_wrong | answered | 1 | 3/3 | 3/3 | yes (1) |
| eval-024 | table_lookup | answered | 1 | 1/1 | 1/1 | no |
| eval-025 | table_lookup | answered | 1 | 2/2 | 2/2 | no |
| eval-027 | follow_up | answered | 2 | 3/3 | 8/8 | yes (2) |
| eval-028 | follow_up | answered | 2 | 3/3 | 10/10 | no |

## Failures and what caused them

1. **eval-021, "How do I generate a Nurse Level Data Insights report?" (similar-but-wrong; 0 of 3 key facts).** The right article was
   retrieved and cited, but the section holding the first steps ("Click + Create New ...") was not in the top 8. 3 of the 8 retrieved
   chunks were link-only "Locate additional ... resources" lists. The answer started mid-procedure (delivery frequency, recipients) and
   read as if complete; nothing told the user that steps were missing. This is the most serious failure: a confident, incomplete
   procedure. It also confirms a known weakness, that navigation chunks crowd out content (201 of 2,310 chunks are mostly links).
2. **eval-011 (budget-based vs impression-based IOs, and how to create one; 3 of 4 facts).** Two of the three required evidence items
   (the "+ Create Insertion Order" step and the note that the budget type cannot be changed) were not retrieved; the answer gave the
   difference well but skipped the explicit first step. A multi-section question needs two articles' worth of evidence in the top 8,
   and only the overview article's chunks were there.
3. **eval-012 (Pre-bid audience; 4 of 4 facts, evidence "miss").** The quote from the target article's definition was not retrieved, but
   the Campaign targeting guide holds the same definition, so the answer was complete. Here the strict quote-based recall understates
   retrieval: the information was available from another article.
4. **eval-009 (HCP Planner creative types; 2 of 3 facts).** The evidence was retrieved first. The answer gave the count and the
   "at least one" rule but not the CTV/OTT detail, which the question did not ask about. The key fact is arguably beyond the question, so
   this is partly a limit of the question set, not only of the bot.
5. **Over-citation (10 of 19 questions).** There were 13 citations outside the expected or related lists. The judge attributed at least one
   claim to 7 of them (plausible supporting sources, such as a related overview) and none to 6 (for example the IO overview cited with
   eval-003 and eval-011). The prompt says to cite only what was used; the model cites more than it needs. This matters because the
   assignment asks that sources be limited to what supports the answer.

What went well: no question produced an error; all three unanswerable questions were declined without a citation; the four follow-ups,
including the two-step pronoun chain (eval-027) and the topic switch (eval-028), were all answered with every key fact; table lookups
worked.

## Limitations

- **Small sample.** 9 dev and 19 test questions; most categories have 2 questions in test. A single question moves a percentage by 5 to
  50 points. Nothing here is statistically conclusive.
- **The questions were not reviewed question by question.** They were drafted with AI assistance, checked by script against the corpus
  (quotes found, section hashes, absence terms) and marked verified on the project owner's instruction. Errors in a reference answer
  or key fact would count against the bot.
- **The judge is the same model family as the answerer** and can share its blind spots. Its first version produced a false positive;
  the second matched a hand check on the 8 dev answers. No hand check of the test verdicts has been done; `review.csv` has empty
  manual columns for that.
- **Quote-based recall is strict in both directions.** It undercounts when the same information sits in a different article (eval-012) and
  needs the exact chunk holding the quote.
- **The citation metric measures agreement with a curated list**, not truth; extra sources can be valid.
- **The test split has now been seen.** Any improvement chosen from these failures cannot be validated on it without bias; a further
  comparison would need new questions.
- Cost figures are estimates from stated prices, not billed amounts. Latency was measured from one machine over the internet.

## What would improve it (not done)

- Filter or down-weight link-only and collection-overview chunks, the likely cause of the worst failure (eval-021).
- Retrieve more candidates and rerank, or add hybrid (keyword plus vector) search, for multi-section questions.
- Tighten citations: cite only the documents behind the answer's claims, which the judge's claim-to-document mapping suggests is feasible.
- Say so when a procedure appears to start mid-way (a completeness check), and a stronger or different-provider judge.
- More questions, reviewed by a person, and a hand check of a sample of the judge's verdicts.

## Reproduce

```
python scripts/evaluate.py --split dev --dry-run          # plan, no API calls
python scripts/evaluate.py --split dev --yes              # dev run (model calls)
python scripts/evaluate.py --rejudge data/evaluation/results/<run> --yes   # judge saved answers again
python scripts/evaluate.py --rebuild data/evaluation/results/<run>         # rebuild summaries and review.csv, no API calls
```

The test split is run once per dataset version (`python scripts/evaluate.py --split test --yes`); the runner refuses a second run.
Each run folder holds `config.json` (models, prompts, top-k, index size, dataset hash, git commit), `results.jsonl`, `review.csv` for
manual review, `summary.json` and `summary.md`. Traces for every question are in LangSmith under the tag `eval`; see `docs/decisions/FR-08-tracing.md`.
