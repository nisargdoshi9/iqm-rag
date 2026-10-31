# Evaluation run 20261031-111308-test-hybrid-llm-neighbours

- Split: test · questions: 19 (errors: 0) · dataset 0544c5efafd2 · statuses {'verified': 19}
- Models: chat gpt-4.1-mini, rewrite gpt-4.1-mini, embedding text-embedding-3-large, judge gpt-4.1-mini (judge prompt j2) · answer prompt v5 · top_k 8 · index chunks 2131
- Retrieval configuration: hybrid+llm+neighbours {'mode': 'hybrid', 'rerank': 'llm', 'neighbours': True, 'candidates': 30, 'label': 'hybrid+llm+neighbours', 'reranker': 'gpt-4.1-mini'}
- Git commit 7cec6d8 · tracing on

## Headline

| Measure | Result |
|---|---|
| Right answer or right abstention | 19/19 (100.0%) |
| Answerable questions answered | 16/16 (100.0%) |
| End-to-end correct (answered with every key fact) | 14/16 (87.5%) |

## Retrieval (answerable questions, 19 required evidence items)

| Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR | Right article retrieved | Evidence in the model's context |
|---|---|---|---|---|---|---|
| 12/19 (63.2%) | 15/19 (78.9%) | 16/19 (84.2%) | 19/19 (100.0%) | 0.859 | 16/16 (100.0%) | 19/19 (100.0%) |

## Abstention

| Measure | Result |
|---|---|
| Correct abstentions (should abstain, said not covered) | 3/3 (100.0%) |
| Outcomes | {'answered': 16, 'correct_abstention': 3} |

## Citations

- Mean precision 0.792 · mean recall 1.0 · no wrong citation 12/19 (63.2%)

## Answer quality (LLM judge, answered answerable questions)

- Judged 16 (judge errors 0) · every key fact covered 14/16 (87.5%) · mean fact coverage 0.964 · every claim supported 16/16 (100.0%) · claims 108 (supported 108, quote found in the named document 99)
- The judge is a model of the same family as the answerer; treat it as a guide and use the manual columns in review.csv to check it.

## Operational

- Wall time per question (seconds): {'n': 19, 'median': 3.172, 'p90': 4.73, 'mean': 3.501, 'max': 5.341}
- Tokens 246048 · estimated cost 0.1111 USD (0.00585 per question). This is an estimate from stated prices (2026-10-31; the gpt-4.1-mini figures reproduce LangSmith's own cost estimate for the same calls), not a billed amount.

## Per category

| Category | n | Passed | Recall@8 | End-to-end correct |
|---|---|---|---|---|
| direct_factual | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| follow_up | 4 | 4/4 (100.0%) | 4/4 (100.0%) | 4/4 (100.0%) |
| list_multi_condition | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 1/2 (50.0%) |
| multi_section | 2 | 2/2 (100.0%) | 5/5 (100.0%) | 1/2 (50.0%) |
| procedural | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| similar_but_wrong | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| table_lookup | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| unanswerable | 3 | 3/3 (100.0%) | 0/0 | 0/0 |

## Failures

- eval-003 [direct_factual]: wrong citation: https://help.iqm.com/en/articles/8365220-insertion-orders-io-overview
- eval-008 [list_multi_condition]: wrong citation: https://help.iqm.com/en/articles/11497708-campaign-targeting-guide
- eval-009 [list_multi_condition]: wrong citation: https://help.iqm.com/en/articles/12238826-healthcare-professional-hcp-planner-overview; facts covered 2/3
- eval-011 [multi_section]: wrong citation: https://help.iqm.com/en/articles/8365220-insertion-orders-io-overview; facts covered 3/4
- eval-012 [multi_section]: wrong citation: https://help.iqm.com/en/articles/8698628-create-or-manage-a-pre-bid-audience
- eval-014 [follow_up]: wrong citation: https://help.iqm.com/en/articles/5735120-create-or-manage-a-conversion
- eval-022 [similar_but_wrong]: wrong citation: https://help.iqm.com/en/articles/11750312-create-or-manage-a-retargeted-audience
