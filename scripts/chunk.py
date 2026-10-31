"""Split the cleaned articles into chunks (FR-3). Reads data/processed/, writes data/chunks/. Needs no network access.

    python scripts/chunk.py
"""

import json
import logging
import sys

from iqm_rag import config
from iqm_rag.ingestion.chunking import CHUNKS_JSONL, run_chunking


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        report = run_chunking()
    except FileNotFoundError as exc:
        print(f"Chunking stopped: cleaned dataset not found ({exc}). Run scripts/normalize.py first.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    print(f"Chunks: {CHUNKS_JSONL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
