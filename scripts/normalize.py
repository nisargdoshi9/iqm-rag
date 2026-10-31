"""Clean the raw Help Center dataset into structured articles and a media sidecar (FR-2).

Reads data/raw/ (never modifies it) and writes data/processed/. Needs no network access.
    python scripts/normalize.py
"""

import json
import logging
import sys

from iqm_rag import config
from iqm_rag.scraping.normalization import ProcessedPaths, run_normalization


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        report = run_normalization(ProcessedPaths.default())
    except FileNotFoundError as exc:
        print(f"Normalisation stopped: raw dataset not found ({exc}). Run scripts/scrape.py first.", file=sys.stderr)
        return 2
    print(json.dumps({k: report[k] for k in ("articles_processed", "tables_by_class", "unknown_tables", "media")}, indent=2))
    print(f"Full report: {config.CLEANING_REPORT_PATH}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
