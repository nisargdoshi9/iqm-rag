"""Embed the chunks and build or update the Chroma index (FR-3). Run scripts/chunk.py first.

    python scripts/index.py --dry-run   # show what would be embedded; makes no API calls and writes nothing
    python scripts/index.py             # embed new or changed chunks (calls the OpenAI embeddings API)
    python scripts/index.py --rebuild   # discard the index and embed everything (needed after a model change)
"""

import argparse
import json
import logging
import sys

from iqm_rag import config
from iqm_rag.ingestion.chunking import CHUNKS_JSONL
from iqm_rag.ingestion.embeddings import EmbeddingError, EmbeddingResult, default_embedder
from iqm_rag.ingestion.indexing import IndexMismatchError, run_indexing
from iqm_rag.scraping.normalization import read_jsonl
from iqm_rag.scraping.scraper import write_atomic


class _ModelOnly:
    """Stands in for the embedder in a dry run so no API key is needed and nothing is called."""

    def __init__(self, model: str) -> None:
        self.model = model

    def embed(self, texts: list[str]) -> EmbeddingResult:
        raise RuntimeError("A dry run must not embed anything.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="discard the index and embed everything")
    parser.add_argument("--dry-run", action="store_true", help="plan only: no API calls, nothing written")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        chunks = read_jsonl(CHUNKS_JSONL)
        embedder = _ModelOnly(config.embedding_model()) if args.dry_run else default_embedder()
        report = run_indexing(chunks, embedder, config.CHROMA_DIR, rebuild=args.rebuild, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(f"Indexing stopped: chunks not found ({exc}). Run scripts/chunk.py first.", file=sys.stderr)
        return 2
    except (IndexMismatchError, EmbeddingError, RuntimeError) as exc:
        print(f"Indexing stopped: {exc}\nBatches already stored are kept; fix the problem and re-run to resume.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    if not args.dry_run:
        write_atomic(config.INDEX_REPORT_PATH, json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
