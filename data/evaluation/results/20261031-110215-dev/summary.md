# Evaluation run 20261031-110215-dev

- Split: dev · questions: 9 (errors: 0) · dataset 0544c5efafd2 · statuses {'verified': 9}
- Models: chat gpt-4.1-mini, rewrite gpt-4.1-mini, embedding text-embedding-3-large, judge None (judge prompt None) · answer prompt v5 · top_k 8 · index chunks 2131
- Git commit 1f623c9 · tracing on

## Headline

| Measure | Result |
|---|---|
| Right answer or right abstention | 9/9 (100.0%) |
| Answerable questions answered | 8/8 (100.0%) |
| End-to-end correct (answered with every key fact) | 0/8 (0.0%) |

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

- Mean precision 0.938 · mean recall 0.938 · no wrong citation 8/9 (88.9%)

## Answer quality (LLM judge, answered answerable questions)

- Judged 0 (judge errors 0) · every key fact covered 0/0 · mean fact coverage None · every claim supported 0/0 · claims 0 (supported 0, quote found in the named document 0)
- The judge is a model of the same family as the answerer; treat it as a guide and use the manual columns in review.csv to check it.

## Operational

- Wall time per question (seconds): {'n': 9, 'median': 2.553, 'p90': 3.644, 'mean': 2.745, 'max': 3.644}
- Tokens 24534 · estimated cost 0.0112 USD (0.00125 per question). This is an estimate from stated prices (2026-10-31; the gpt-4.1-mini figures reproduce LangSmith's own cost estimate for the same calls), not a billed amount.

## Per category

| Category | n | Passed | Recall@8 | End-to-end correct |
|---|---|---|---|---|
| direct_factual | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0/1 (0.0%) |
| follow_up | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 0/2 (0.0%) |
| list_multi_condition | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0/1 (0.0%) |
| multi_section | 1 | 1/1 (100.0%) | 2/2 (100.0%) | 0/1 (0.0%) |
| procedural | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0/1 (0.0%) |
| similar_but_wrong | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0/1 (0.0%) |
| table_lookup | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0/1 (0.0%) |
| unanswerable | 1 | 1/1 (100.0%) | 0/0 | 0/0 |

## Failures

- eval-010 [multi_section]: wrong citation: https://help.iqm.com/en/articles/5651486-segmented-audience-overview
