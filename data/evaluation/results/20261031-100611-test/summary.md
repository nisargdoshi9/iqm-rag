# Evaluation run 20261031-100611-test

- Split: test · questions: 19 (errors: 0) · dataset 0544c5efafd2 · statuses {'verified': 19}
- Models: chat gpt-4.1-mini, rewrite gpt-4.1-mini, embedding text-embedding-3-large, judge gpt-4.1-mini (judge prompt j2) · answer prompt v4 · top_k 8 · index chunks 2310
- Git commit c4d0344 · tracing on

## Headline

| Measure | Result |
|---|---|
| Right answer or right abstention | 19/19 (100.0%) |
| Answerable questions answered | 16/16 (100.0%) |
| End-to-end correct (answered with every key fact) | 13/16 (81.2%) |

## Retrieval (answerable questions, 19 required evidence items)

| Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR | Right article retrieved |
|---|---|---|---|---|---|
| 9/19 (47.4%) | 15/19 (78.9%) | 15/19 (78.9%) | 15/19 (78.9%) | 0.74 | 16/16 (100.0%) |

## Abstention

| Measure | Result |
|---|---|
| Correct abstentions (should abstain, said not covered) | 3/3 (100.0%) |
| Outcomes | {'answered': 16, 'correct_abstention': 3} |

## Citations

- Mean precision 0.702 · mean recall 1.0 · no wrong citation 10/19 (52.6%)

## Answer quality (LLM judge, answered answerable questions)

- Judged 16 (judge errors 0) · every key fact covered 13/16 (81.2%) · mean fact coverage 0.901 · every claim supported 16/16 (100.0%) · claims 108 (supported 108, quote found in the named document 102)
- The judge is a model of the same family as the answerer; treat it as a guide and use the manual columns in review.csv to check it.

## Operational

- Wall time per question (seconds): {'n': 19, 'median': 2.548, 'p90': 3.655, 'mean': 2.581, 'max': 3.668}
- Tokens 103262 · estimated cost 0.0542 USD (0.00285 per question). This is an estimate from stated prices (2026-10-31; the gpt-4.1-mini figures reproduce LangSmith's own cost estimate for the same calls), not a billed amount.

## Per category

| Category | n | Passed | Recall@8 | End-to-end correct |
|---|---|---|---|---|
| direct_factual | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| follow_up | 4 | 4/4 (100.0%) | 4/4 (100.0%) | 4/4 (100.0%) |
| list_multi_condition | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 1/2 (50.0%) |
| multi_section | 2 | 2/2 (100.0%) | 2/5 (40.0%) | 1/2 (50.0%) |
| procedural | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| similar_but_wrong | 2 | 2/2 (100.0%) | 1/2 (50.0%) | 1/2 (50.0%) |
| table_lookup | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| unanswerable | 3 | 3/3 (100.0%) | 0/0 | 0/0 |

## Failures

- eval-003 [direct_factual]: wrong citation: https://help.iqm.com/en/articles/8365220-insertion-orders-io-overview
- eval-008 [list_multi_condition]: wrong citation: https://help.iqm.com/en/articles/5651517-manage-a-campaign-s-optimization-delivery-settings, https://help.iqm.com/en/articles/11497708-campaign-targeting-guide, https://help.iqm.com/en/articles/12004298-optimization-overview
- eval-009 [list_multi_condition]: wrong citation: https://help.iqm.com/en/articles/12238826-healthcare-professional-hcp-planner-overview; facts covered 2/3
- eval-011 [multi_section]: evidence not retrieved; wrong citation: https://help.iqm.com/en/articles/8365220-insertion-orders-io-overview, https://help.iqm.com/en/articles/10907105-create-or-manage-an-impression-based-insertion-order-io; facts covered 3/4
- eval-012 [multi_section]: evidence not retrieved; wrong citation: https://help.iqm.com/en/articles/11497708-campaign-targeting-guide
- eval-014 [follow_up]: wrong citation: https://help.iqm.com/en/articles/5735120-create-or-manage-a-conversion
- eval-015 [follow_up]: wrong citation: https://help.iqm.com/en/articles/10873926-bid-model-frequently-asked-questions-faq
- eval-021 [similar_but_wrong]: evidence not retrieved; facts covered 0/3
- eval-022 [similar_but_wrong]: wrong citation: https://help.iqm.com/en/articles/11750312-create-or-manage-a-retargeted-audience
- eval-027 [follow_up]: wrong citation: https://help.iqm.com/en/articles/14126938-generate-or-manage-an-integrated-care-team-ict-insights-report, https://help.iqm.com/en/articles/10774835-generate-or-manage-a-provider-level-data-pld-insights-report
