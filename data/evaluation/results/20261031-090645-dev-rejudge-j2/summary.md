# Evaluation run 20261031-090645-dev-rejudge-j2

- Split: dev · questions: 9 (errors: 0) · dataset 248fcb765871 · statuses {'drafted': 9}
- Models: chat gpt-4.1-mini, rewrite gpt-4.1-mini, embedding text-embedding-3-large, judge gpt-4.1-mini (judge prompt j2) · answer prompt v4 · top_k 8 · index chunks 2310
- Git commit 756ccc4 · tracing on

## Headline

| Measure | Result |
|---|---|
| Right answer or right abstention | 9/9 (100.0%) |
| Answerable questions answered | 8/8 (100.0%) |
| End-to-end correct (answered with every key fact) | 8/8 (100.0%) |

## Retrieval (answerable questions, 9 required evidence items)

| Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR | Right article retrieved |
|---|---|---|---|---|---|
| 5/9 (55.6%) | 7/9 (77.8%) | 8/9 (88.9%) | 9/9 (100.0%) | 0.754 | 8/8 (100.0%) |

## Abstention

| Measure | Result |
|---|---|
| Correct abstentions (should abstain, said not covered) | 1/1 (100.0%) |
| Outcomes | {'answered': 8, 'correct_abstention': 1} |

## Citations

- Mean precision 0.8 · mean recall 1.0 · no wrong citation 6/9 (66.7%)

## Answer quality (LLM judge, answered answerable questions)

- Judged 8 (judge errors 0) · every key fact covered 8/8 (100.0%) · mean fact coverage 1.0 · every claim supported 7/8 (87.5%) · claims 53 (supported 52, quote found in the named document 49)
- The judge is a model of the same family as the answerer; treat it as a guide and use the manual columns in review.csv to check it.

## Operational

- Wall time per question (seconds): {'n': 9, 'median': 2.629, 'p90': 5.89, 'mean': 2.876, 'max': 5.89}
- Tokens 49734 · estimated cost 0.0262 USD (0.00291 per question). This is an estimate from stated prices (2026-10-31; the gpt-4.1-mini figures reproduce LangSmith's own cost estimate for the same calls), not a billed amount.

## Per category

| Category | n | Passed | Recall@8 | End-to-end correct |
|---|---|---|---|---|
| direct_factual | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| follow_up | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| list_multi_condition | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| multi_section | 1 | 1/1 (100.0%) | 2/2 (100.0%) | 1/1 (100.0%) |
| procedural | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| similar_but_wrong | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| table_lookup | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| unanswerable | 1 | 1/1 (100.0%) | 0/0 | 0/0 |

## Failures

- eval-005 [procedural]: wrong citation: https://help.iqm.com/en/articles/15265999-create-or-manage-a-political-planner-plan
- eval-010 [multi_section]: wrong citation: https://help.iqm.com/en/articles/5651486-segmented-audience-overview, https://help.iqm.com/en/articles/11497708-campaign-targeting-guide, https://help.iqm.com/en/articles/15496620-create-or-manage-a-matched-audience-with-vera
- eval-026 [follow_up]: wrong citation: https://help.iqm.com/en/articles/5651452-upload-an-html-creative; unsupported claims
