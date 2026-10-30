# FR-9: Evaluation set — decisions

Status: 25 questions drafted and checked against the cleaned corpus. **Not yet reviewed by a human; not frozen.** Metrics, the runner and results come later.

## Decisions
1. **Size:** 25 questions (the assignment minimum is 15).
2. **Categories (count):** direct factual (3), procedural (3), list or multi-condition (3), multi-section or multi-source (3), follow-up with history (3), unanswerable (4), similar-but-wrong article (3), table lookup (3). Media is a field (`expected_media`) on two questions, not a category.
3. **Expected evidence:** the article URL (needed for the citation check) plus the section heading and the section's content hash, so a later re-scrape cannot silently change what "correct" means.
4. **How questions were written:** plain, user-style wording drawn from the article text, not creative paraphrases. Each question carries the exact supporting quote.
5. **Reference answers:** a short expected answer plus a checklist of `key_facts` for judging correctness the same way each time.
6. **Unanswerable questions:** 3 plausible but undocumented (TikTok/Snapchat, Salesforce, SSO) and 1 off-topic (Google Ads). Each lists `absence_check` terms that were searched in the whole corpus and found zero times. `related_urls` holds near-miss articles that exist but do not answer.
7. **Follow-ups:** a scripted `history` (user and assistant turns) taken from the articles, so the test stays fixed.
8. **Split:** 8 `dev` questions for tuning chunk size and retrieval, 17 `test` questions for the final report. With so few questions the numbers are rough, and the report should say so.

## File format (`data/evaluation/questions.jsonl`)
One JSON object per line: `id`, `category`, `split`, `question`, `history`, `expected_answer`, `key_facts`, `expected_source_urls`, `evidence` (article_id, url, section_heading, section_content_hash, quote, required), `should_abstain`, `related_urls`, `absence_check`, `expected_media`, `similar_to_urls`, `notes`, `status`.

- `expected_source_urls` lists the sources an answer must be able to cite. An evidence item with `required: false` is an alternative source that also supports the answer.
- A multi-source question has several required evidence items; the answer must draw on all of them.

## Checks
`python -m iqm_rag.evaluation.dataset` checks that each quote is found in its cited section, the section hash still matches the corpus, unanswerable terms are absent, follow-ups have valid history, and there are at least 15 questions. All 25 pass.

## Freeze rule
After review, set `status` to `verified` and do not edit the file to improve scores. Changes after seeing results need a new version. The `test` split is used once, for the final report.

## Known limits
- Drafted from the article text with AI assistance and checked by script; a human review of every question is still pending.
- The Help Center was scraped on 2026-10-29. Articles may change later; the section hashes show when that happens.
- Two table questions (Bid Modifier eligibility and the ad-spec rows) test whether table content survives chunking.
