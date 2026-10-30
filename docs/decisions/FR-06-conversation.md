# FR-6: Conversation history and follow-up questions

Status: decided and implemented (2026-10-31). Rewrite quality is not yet measured on the evaluation set. The chat interface (FR-7) and tracing
(FR-8) build on the hooks left here.

## What it does

```
(history, new question) -> rewrite into a standalone query (turn 2 onward) -> retrieve with the query
                        -> answer the user's own message, with the history as labelled context only
```

Requirements: separate histories for separate sessions, relevant previous turns used when answering, follow-ups
resolved before retrieval, the current question's intent preserved, history bounded, an earlier answer never used as
evidence, and every new answer grounded in retrieved Help Center content.

## Decisions

| # | Decision | Options considered | Value |
|---|---|---|---|
| 1 | Where history lives | Stateless chain with the history passed in plus a small `Conversation` helper; a global session store inside the chain; LangChain's built-in message history | Stateless chain and a `Conversation` helper. The evaluation runner passes each question's `history` directly; each UI session owns one `Conversation`, so sessions cannot mix. LangChain's helper does not trim history by itself, and each turn needs more than messages stored (resolved query, citations, warnings) |
| 2 | History window | Last 1, last 3, everything, a token budget, LLM summaries; cutting long answers | Last 3 exchanges, full answers, no cutting. No source gives a number of turns; 3 is judgement, covers short chains and limits topic-switch drift. Answers are capped by the output limit, so history stays bounded. Not tunable with the few follow-up evaluation questions |
| 3 | The rewrite | Every turn from turn 2 or a heuristic; same or smaller model; plain or structured output; fall back or fail | Every turn from turn 2; the model returns the question unchanged when it is already standalone. Same `gpt-4.1-mini` (own setting `REWRITE_MODEL`). Plain text output. On an API failure, empty or over-long output, or a cut-off reply, the raw question is used and the reason recorded |
| 4 | Retrieval query | Rewrite alone; rewrite plus the raw question; two searches merged; whole history | The rewrite alone. The rewrite plus the raw question is the best-reported variant in one shared-task paper and is the first experiment to try; the query is built in one function so this is a small change |
| 5 | What the answer model sees | Original or rewritten question; labelled block, real chat messages or no history | The user's own latest message, plus a labelled history block ("to understand what the user refers to, not evidence"), plus the documents retrieved with the rewritten query. Prompt version v2 |
| 6 | Earlier answers as evidence | The existing citation check plus a prompt rule; remove previous answers from history; a second verification call | The citation check plus a prompt rule. An answer with no valid document citation is shown as an abstention, so a reply cannot rest on the previous answer alone |
| 7 | Small talk ("thanks") | Leave to abstain; a short rule list with a fixed reply; an LLM intent check | Left to abstain in version 1. A rule list and an intent check are future improvements |
| 8 | Tracing hooks | Record on the answer; rely on the tracing service | Each answer records the original question, the resolved query, whether it changed, the fallback reason, the rewrite's tokens and the history used |
| 9 | Evaluation | Existing 3 follow-up questions only; 3 more; 6 more | 3 more drafted for review (a two-step pronoun chain, a topic switch, a question about the previous answer) |

## Answer length cap (amends FR-5)

The answer limit is raised from 700 to 2,000 tokens. At the limit, the API raises `LengthFinishReasonError` (checked
with one live call at a 25-token limit); before this change the chain turned that into "The model request failed", an
error caused by our own cap. Now a cut-off reply is retried once with a limit of 4,000 tokens and a line asking for
a more concise answer. If that is also cut off, the user sees a friendly message asking them to ask about one part at
a time, with a warning recorded. At most one retry, never a loop. A genuine API outage is a different failure and
still shows an error.

## Evidence

- Searching with the whole conversation helps when the topic stays consistent and can hurt on topic switches
  (Alushi et al., EACL 2026), which supports a bounded window and an LLM rewrite that can leave a switched topic alone.
- Sources give no number of turns to keep; general guidance is a sliding window of recent turns. No source was found on
  cutting assistant answers, so none is cut.
- TREC CAsT 2022 systems (Cambridge, Heatwave) searched with concatenated history and used the rewrite for reranking,
  with sparse retrieval; a SemEval-2026 Task 8 system joined the rewrite with the last user turn and found that
  better than either alone. No controlled comparison for dense retrieval on a corpus like ours was found.
- The evaluation set has only 3 follow-up questions (1 dev, 2 test), each with a single prior exchange. They cannot
  separate a good rewrite from a poor one, hence decision 9.

## Open items

- Try the rewrite joined with the raw question as the retrieval query (decision 4), and the rewrite with and without
  the rewrite step, on the follow-up evaluation questions.
- Small talk and greetings (decision 7): a rule list or an LLM intent check.
- The window of 3 exchanges and the cap values are untuned.

## Implementation (2026-10-31)

- `history.py`: `Message`, `trim_history` (last 3 exchanges), `format_history`, `messages_from_dicts` (evaluation
  format). `usage.py`: provider-reported token counts, None when not reported.
- `retrieval/query_rewriting.py`: `QueryRewriter` and `RewriteResult` (original, query, rewritten, fallback reason,
  model, usage, time). The rewrite prompt keeps entity names and the user's intent, never answers, and returns an
  already standalone message unchanged. A cut-off, empty, multi-line or over-500-character reply falls back.
- `generation/chain.py`: steps `rewrite`, `retrieve`, `build_context`, `generate`, `check_output`; `answer(question,
  history)` trims the history; the answer keeps the rewrite, the history used and the number of model attempts.
  `generation/conversation.py`: `Conversation` (per session, failed turns not recorded). Prompt v2 labels the history
  as "not evidence". The answer cap is 2,000 tokens with one retry at 4,000.
- `scripts/chat.py`: terminal chat with `/new` and `/quit`; `scripts/ask.py` prints "Searched for" when the query changed.
- New setting `REWRITE_MODEL` (defaults to `CHAT_MODEL`). Tests: 200 in total, no network.

Live check (one fixed 4-turn conversation, ad hoc questions, a smoke test and not a measurement):

| Turn | Message | Query used | Result |
|---|---|---|---|
| 1 | How do I schedule a report to be emailed every week? | the question (no history) | correct answer, correct source |
| 2 | Can I change those settings later? | "Can I change the scheduled email delivery settings for a report later?" | correct answer from the edit section, two sources |
| 3 | And who is allowed to do that? | "Who is allowed to change the settings of a scheduled report in the IQM platform?" | abstained: the documentation does not say |
| 4 | How do I upload an image creative? (topic switch) | "How do I upload an image creative on the IQM platform?" | correct answer for the new topic |

The pronoun and the chained pronoun were resolved and the topic switch was not polluted by the old topic. One
observation: the rewriter added "on the IQM platform" to two queries. That is harmless here, but it is added wording that
the user did not write; watch for it in the evaluation.
