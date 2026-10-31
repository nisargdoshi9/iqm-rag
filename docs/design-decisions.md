# Design decisions

One record per part of the system, each with the options considered, the choice, the evidence behind it and its limits.

| Record | Topic | The choice in one line |
|---|---|---|
| [FR-01](decisions/FR-01-discovery-and-scraping.md) | Discovery and scraping | Sitemap and collection discovery, polite fetching (robots.txt, 2 s delay), content hashes so reruns skip unchanged articles |
| [FR-02](decisions/FR-02-cleaning.md) | Cleaning | Parse articles into a section tree with lists, tables, FAQ pairs and media, instead of flattening to text |
| [FR-03](decisions/FR-03-chunking.md) | Chunking, embeddings, index | Section-based chunks (150 to 700 tokens, heading path in the embedded text), `text-embedding-3-large`, Chroma with cosine distance |
| [FR-04](decisions/FR-04-retrieval.md) | Retrieval | Dense search, top 8, scores exposed but not used to decide whether to answer (the baseline; upgraded in the improvements record below) |
| [FR-05](decisions/FR-05-generation.md) | Answers, citations, abstention | `gpt-4.1-mini` with structured output; the model cites context numbers and the application maps them to stored URLs |
| [FR-06](decisions/FR-06-conversation.md) | Chat history | Stateless chain, last 3 exchanges, LLM rewrite of follow-ups with fallback |
| [FR-07](decisions/FR-07-chat-interface.md) | Chat interface | Streamlit; three outcome states; evidence and diagnostics only in Developer mode |
| [FR-08](decisions/FR-08-tracing.md) | Tracing | LangSmith, on only when a key is set; we generate the trace ID |
| [FR-09](decisions/FR-09-evaluation.md) | Evaluation | Evidence-quote retrieval metrics, deterministic abstention and citation checks, a strict LLM judge; test split run once |
| [Improvements](decisions/FR-10-improvements.md) | After the first test run | 16 held-out questions; link-only chunks dropped; tighter citations; small talk; hybrid search, LLM reranker and neighbour parts as switches, compared once each; shipped default hybrid + rerank |
| [Updates and MCP](decisions/FR-11-update-and-mcp.md) | Bonus tasks | One `update.py` command (changed articles only, removed articles dropped, failures stop it before it removes anything); MCP server with a search tool and a get-article tool |

Supporting analysis: [media and tables](analysis/media-and-tables.md). Results: [evaluation report](evaluation-report.md). Design
summary for a reader: [write-up](writeup.md). Structure: [architecture](architecture.md).
