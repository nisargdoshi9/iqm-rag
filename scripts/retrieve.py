"""Run one query against the index and print the ranked chunks (FR-4). Calls the OpenAI embeddings API once.

    python scripts/retrieve.py "How do I schedule a report?"
    python scripts/retrieve.py "How do I schedule a report?" --top-k 5
    python scripts/retrieve.py "How do I schedule a report?" --json
"""

import argparse
import json
import sys
from typing import Optional

from iqm_rag import config
from iqm_rag.ingestion.embeddings import EmbeddingError, default_embedder
from iqm_rag.ingestion.indexing import IndexMismatchError, IndexNotBuiltError
from iqm_rag.retrieval.retriever import RetrievalError, RetrievalResult, Retriever

SNIPPET_CHARS = 160


def format_result(result: RetrievalResult) -> str:
    lines = [f"Query: {result.query}",
             f"Model {result.embedding_model}, {result.embedding_tokens} query tokens, "
             f"embed {result.embed_ms:.0f} ms, search {result.search_ms:.0f} ms, top_k {result.top_k}", ""]
    for hit in result.hits:
        chunk = hit.chunk
        part = f" (part {chunk['part']}/{chunk['parts']})" if chunk["parts"] > 1 else ""
        snippet = " ".join(chunk["text"].split())[:SNIPPET_CHARS]
        lines += [f"{hit.rank:>2}  similarity {hit.similarity:.3f}  {chunk['context_header']}{part}",
                  f"    {chunk['article_url']}", f"    {snippet}", ""]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", help="the question to search for")
    parser.add_argument("--top-k", type=int, default=None, help=f"chunks to return (default {config.DEFAULT_TOP_K})")
    parser.add_argument("--json", action="store_true", help="print the full result, including chunk text, as JSON")
    args = parser.parse_args(argv)
    try:
        retriever = Retriever(default_embedder(), config.CHROMA_DIR, args.top_k or config.retrieval_top_k())
        result = retriever.retrieve(args.query)
    except (IndexNotBuiltError, IndexMismatchError, EmbeddingError, RetrievalError, ValueError, RuntimeError) as exc:
        print(f"Retrieval stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) if args.json else format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
