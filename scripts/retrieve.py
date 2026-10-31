"""Run one query against the index and print the ranked chunks (FR-4). Calls the OpenAI embeddings API once.

    python scripts/retrieve.py "How do I schedule a report?"
    python scripts/retrieve.py "How do I schedule a report?" --top-k 5
    python scripts/retrieve.py "How do I schedule a report?" --json
    python scripts/retrieve.py "How do I schedule a report?" --retrieval-mode hybrid --rerank llm --neighbours
"""

import argparse
import json
import sys
from typing import Optional

from iqm_rag import config
from iqm_rag.ingestion.embeddings import EmbeddingError, default_embedder
from iqm_rag.ingestion.indexing import IndexMismatchError, IndexNotBuiltError
from iqm_rag.retrieval.pipeline import RetrievalPipeline, RetrievalSettings
from iqm_rag.retrieval.rerank import default_reranker
from iqm_rag.retrieval.retriever import RetrievalError, RetrievalResult, Retriever

SNIPPET_CHARS = 160


def format_result(result: RetrievalResult) -> str:
    lines = [f"Query: {result.query}",
             f"Model {result.embedding_model}, {result.embedding_tokens} query tokens, "
             f"embed {result.embed_ms:.0f} ms, search {result.search_ms:.0f} ms, top_k {result.top_k}", ""]
    for hit in result.hits + result.extra_hits:
        chunk = hit.chunk
        part = f" (part {chunk['part']}/{chunk['parts']})" if chunk["parts"] > 1 else ""
        snippet = " ".join(chunk["text"].split())[:SNIPPET_CHARS]
        rank = f"{hit.rank:>2}" if hit.rank <= result.top_k else " +"  # + marks a neighbouring part added to the context
        stages = " ".join(f"{name}={value}" for name, value in hit.scores.items() if value is not None and name != "neighbour")
        lines += [f"{rank}  similarity {hit.similarity:.3f}  {chunk['context_header']}{part}" + (f"  [{stages}]" if stages else ""),
                  f"    {chunk['article_url']}", f"    {snippet}", ""]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", help="the question to search for")
    parser.add_argument("--top-k", type=int, default=None, help=f"chunks to return (default {config.DEFAULT_TOP_K})")
    parser.add_argument("--retrieval-mode", choices=config.RETRIEVAL_MODES, help="dense or hybrid (default: RETRIEVAL_MODE or dense)")
    parser.add_argument("--rerank", choices=config.RERANKERS, help="llm reorders the candidates (default: RERANK or off)")
    parser.add_argument("--neighbours", action=argparse.BooleanOptionalAction, default=None, help="add adjacent parts of split sections")
    parser.add_argument("--json", action="store_true", help="print the full result, including chunk text, as JSON")
    args = parser.parse_args(argv)
    try:
        env = RetrievalSettings.from_env()
        settings = RetrievalSettings(args.retrieval_mode or env.mode, args.rerank or env.rerank,
                                     env.neighbours if args.neighbours is None else args.neighbours, env.candidates)
        retriever = Retriever(default_embedder(), config.CHROMA_DIR, args.top_k or config.retrieval_top_k())
        pipeline = RetrievalPipeline(retriever, settings, default_reranker() if settings.rerank != "off" else None)
        result = pipeline.retrieve(args.query)
    except (IndexNotBuiltError, IndexMismatchError, EmbeddingError, RetrievalError, ValueError, RuntimeError) as exc:
        print(f"Retrieval stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) if args.json else format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
