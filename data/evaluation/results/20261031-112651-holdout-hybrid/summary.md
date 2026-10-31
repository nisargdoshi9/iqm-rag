# Evaluation run 20261031-112651-holdout-hybrid

- Split: holdout · questions: 16 (errors: 0) · dataset 5fd7d74123bb · statuses {'verified': 16}
- Models: chat gpt-4.1-mini, rewrite gpt-4.1-mini, embedding text-embedding-3-large, judge gpt-4.1-mini (judge prompt j2) · answer prompt v5 · top_k 8 · index chunks 2131
- Retrieval configuration: hybrid {'mode': 'hybrid', 'rerank': 'off', 'neighbours': False, 'candidates': 30, 'label': 'hybrid', 'reranker': None}
- Git commit 938b3b4 · tracing on

## Headline

| Measure | Result |
|---|---|
| Right answer or right abstention | 16/16 (100.0%) |
| Answerable questions answered | 14/14 (100.0%) |
| End-to-end correct (answered with every key fact) | 12/14 (85.7%) |

## Retrieval (answerable questions, 19 required evidence items)

| Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR | Right article retrieved | Evidence in the model's context |
|---|---|---|---|---|---|---|
| 7/19 (36.8%) | 12/19 (63.2%) | 13/19 (68.4%) | 16/19 (84.2%) | 0.689 | 14/14 (100.0%) | 16/19 (84.2%) |

## Abstention

| Measure | Result |
|---|---|
| Correct abstentions (should abstain, said not covered) | 2/2 (100.0%) |
| Outcomes | {'answered': 14, 'correct_abstention': 2} |

## Citations

- Mean precision 0.714 · mean recall 1.0 · no wrong citation 8/16 (50.0%)

## Answer quality (LLM judge, answered answerable questions)

- Judged 14 (judge errors 0) · every key fact covered 12/14 (85.7%) · mean fact coverage 0.881 · every claim supported 14/14 (100.0%) · claims 83 (supported 83, quote found in the named document 77)
- The judge is a model of the same family as the answerer; treat it as a guide and use the manual columns in review.csv to check it.

## Operational

- Wall time per question (seconds): {'n': 16, 'median': 2.298, 'p90': 2.766, 'mean': 2.229, 'max': 2.981}
- Tokens 98430 · estimated cost 0.05 USD (0.00313 per question). This is an estimate from stated prices (2026-10-31; the gpt-4.1-mini figures reproduce LangSmith's own cost estimate for the same calls), not a billed amount.

## Per category

| Category | n | Passed | Recall@8 | End-to-end correct |
|---|---|---|---|---|
| direct_factual | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| follow_up | 2 | 2/2 (100.0%) | 3/3 (100.0%) | 1/2 (50.0%) |
| list_multi_condition | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| multi_section | 3 | 3/3 (100.0%) | 5/6 (83.3%) | 3/3 (100.0%) |
| procedural | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| similar_but_wrong | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| table_lookup | 1 | 1/1 (100.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| unanswerable | 2 | 2/2 (100.0%) | 0/0 | 0/0 |

## Failures

- hold-001 [direct_factual]: wrong citation: https://help.iqm.com/en/articles/12759402-optimization-delivery-frequently-asked-questions-faq
- hold-002 [direct_factual]: wrong citation: https://help.iqm.com/en/articles/9616211-create-or-manage-an-inventory-group
- hold-005 [list_multi_condition]: wrong citation: https://help.iqm.com/en/articles/11497708-campaign-targeting-guide
- hold-006 [list_multi_condition]: wrong citation: https://help.iqm.com/en/articles/11749823-troubleshoot-a-lookalike-audience
- hold-007 [multi_section]: wrong citation: https://help.iqm.com/en/articles/11997149-campaign-estimations-overview
- hold-008 [multi_section]: evidence not retrieved; wrong citation: https://help.iqm.com/en/articles/12759402-optimization-delivery-frequently-asked-questions-faq
- hold-010 [follow_up]: wrong citation: https://help.iqm.com/en/articles/11749823-troubleshoot-a-lookalike-audience
- hold-011 [follow_up]: facts covered 1/3
- hold-012 [table_lookup]: evidence not retrieved; facts covered 0/2
- hold-013 [similar_but_wrong]: wrong citation: https://help.iqm.com/en/articles/10344323-creative-formats-overview
