# FR-8: Observability and tracing

Status: decided and implemented (2026-10-31). Verified against the real LangSmith service with two multi-turn conversations
and one question through the chat page.

## Decisions

| # | Decision | Options considered | Value |
|---|---|---|---|
| 1 | Tool | LangSmith, Langfuse, Phoenix (local), a plain local log | LangSmith: native to LangChain, so the chain's named steps trace with no extra code, and the assignment lists it first |
| 2 | What a trace carries | Defaults only; defaults plus our own metadata | Defaults plus our metadata: run name, tags (`rag`, prompt version, model), session ID, setup metadata, the outcome, the query embedding as its own step, and the retrieved chunks with scores |
| 3 | Trace ID | LangSmith generates it; we generate it | We generate one per request, use it as the LangSmith run ID, return it on every answer and show it in Developer mode. It is also a request ID when tracing is off |
| 4 | When it runs | Always; only with a key | Only when `LANGSMITH_API_KEY` is set (and `LANGSMITH_TRACING` is not false). Without a key nothing is sent, and tests never reach the network |
| 5 | Privacy | Send everything; hide inputs and outputs | On only when a key is set; `LANGSMITH_HIDE_INPUTS` and `LANGSMITH_HIDE_OUTPUTS` are documented in `.env.example` for anyone who does not want questions and answers stored. Questions go to a third-party service, which the write-up should mention |
| 6 | Cost | Compute our own; use LangSmith's | Tokens are recorded exactly as the provider reports them. Cost is LangSmith's estimate from published model prices (labelled an estimate); the evaluation report will state its own price assumptions |
| 7 | Evaluation link | None; tags on traces | `answer(..., tags=..., metadata=...)` lets the evaluation runner tag traces with the question ID |

## What one request records

A request is one run, `rag_answer`, with one child step per stage:

```
rag_answer                        3.46 s   3,599 tokens   about $0.0016 (LangSmith estimate)
  rewrite                         0.70 s     509 tokens      prompt + gpt-4.1-mini call
  retrieve                        0.36 s
    vector_search  (retriever)    0.36 s                    the 8 retrieved chunks, with rank, similarity, chunk ID, source URL
      embed_query  (embedding)    0.34 s      14 tokens     3,072 dimensions
  build_context                   0.00 s
  generate                        2.39 s   3,090 tokens     the full prompt and the structured response
  check_output                    0.00 s
```

(From `docs/traces/example-trace.json`: the second turn of a conversation, so it includes the follow-up rewrite.)

- **Root run input:** the question and the history shown to the model. **Output:** a compact summary (status, answer text,
  cited URLs, search query, whether it was rewritten, retrieved chunk IDs, token usage, model time, attempts, warnings, trace ID).
- **Tags:** `rag`, `prompt:v4`, `model:gpt-4.1-mini`. **Metadata:** session ID (LangSmith groups runs with one into a thread),
  chat, rewrite and embedding models, top-k, history length, question length, and after the run the status, whether it
  abstained, whether it was rewritten, the number of citations, attempts and warnings. No secrets and no question text.
- **Errors** are recorded on the failing step by LangChain. The OpenAI client's own retries happen inside a call and are not
  separately visible; our own retry after a cut-off reply shows as a second `generate` attempt (`llm_attempts`).

## Using it

- Set `LANGSMITH_API_KEY` in `.env` (see `.env.example`); optionally `LANGSMITH_PROJECT` (default `iqm-help-center-rag`).
- Developer mode in the chat page shows "Tracing on, project ..." in the sidebar and the trace ID under each answer.
  `scripts/ask.py` prints the trace ID too.
- `python scripts/export_trace.py <trace-id> --out docs/traces/example-trace.json` writes the whole trace as nested JSON, with
  LangChain's own wrapper runs left out. The committed example lets a reviewer see a trace without access to our project.

## How it was checked

- Unit tests (hermetic, 20 new): configuration rules (no key, placeholder key, key, explicit off), tags and metadata (no
  secrets), the document format for retrieved chunks, a unique valid trace ID on every answer, the run starting with our ID,
  tags and metadata, tracing enabled only when asked, compact logging, one named step per stage, and the exporter.
- Live: two conversations and one chat-page question traced to LangSmith; the root run ID matched our ID, the tags, the
  metadata, the retrieved documents, the embedding step, both model calls with token counts and an estimated cost, and the
  trace ID shown in the interface was found in LangSmith.

## Problems found on the way

- LangChain writes a step's whole output into the trace. Our dataclasses carry every chunk's text, so the same chunks were
  copied into three steps (about 14 KB, 12 KB and 30 KB). Heavy objects now travel between steps wrapped in a small holder that
  logs a one-line label; the `vector_search` step holds the chunks and the prompt holds the text.
- `RunnablePassthrough.assign` added unnamed wrapper runs for every step. The chain now has one named step per stage.
- A field that LangSmith's input processor expected (`self`) is not passed to it; the embedding model is recorded as run
  metadata instead.
- Embedding token counts are not shown in LangSmith's token columns (they are in the step's output); the root summary and the
  interface show the query embedding tokens separately.

## Limits and later

- Traces hold the question and the answer. Anyone who must not store them should set the HIDE flags.
- Cost is an estimate by LangSmith; no billed figures.
- No feedback scores or datasets in LangSmith yet (the interface has no feedback buttons).
