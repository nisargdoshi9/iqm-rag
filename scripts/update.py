"""Update the dataset and the index incrementally (bonus: incremental updates).

Re-scrapes only new or changed articles, drops articles that left the site, then refreshes the cleaned data, the chunks and the
index (only new or changed chunks are embedded). Needs SCRAPER_USER_AGENT and OPENAI_API_KEY.

    python scripts/update.py --dry-run        # discovery only: which articles are new, changed or removed (nothing fetched or written)
    python scripts/update.py                  # update everything that changed
    python scripts/update.py --skip-scrape    # clean, chunk and index from the data already on disk (no network except embeddings)
    python scripts/update.py --force          # refetch every article, then update
    python scripts/update.py --json           # print the summary as JSON

If any article fails to download or clean, the update stops before the later steps and says so; running it again retries only those.
After an update, restart any running MCP server or chat page so it loads the new index.
"""

import argparse
import logging
import sys
from typing import Optional

from iqm_rag import config
from iqm_rag.ingestion.embeddings import EmbeddingError, default_embedder
from iqm_rag.ingestion.indexing import IndexMismatchError
from iqm_rag.scraping.scraper import CrawlAborted, PoliteFetcher
from iqm_rag.update import UpdatePaths, describe, describe_plan, plan_update, run_update, to_json


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="discovery only: report what would change; fetch and write nothing")
    parser.add_argument("--skip-scrape", action="store_true", help="skip the network crawl and rebuild from the data on disk")
    parser.add_argument("--force", action="store_true", help="refetch every article")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    paths = UpdatePaths.default()
    try:
        fetcher = None if args.skip_scrape else PoliteFetcher(user_agent=config.scraper_user_agent(), delay_seconds=config.scraper_delay_seconds())
        if args.dry_run:
            if fetcher is None:
                print("--dry-run needs the crawl; drop --skip-scrape.", file=sys.stderr)
                return 2
            print(describe_plan(plan_update(fetcher, paths, args.force)))
            return 0
        summary = run_update(fetcher, default_embedder(), paths, force=args.force, skip_scrape=args.skip_scrape)
    except (RuntimeError, CrawlAborted, FileNotFoundError) as exc:
        print(f"Update stopped: {exc}", file=sys.stderr)
        return 2
    except (IndexMismatchError, EmbeddingError) as exc:
        print(f"Update stopped while indexing: {exc}\nThe cleaned data and chunks were updated; run scripts/index.py to resume.", file=sys.stderr)
        return 1
    print(to_json(summary) if args.json else describe(summary))
    return 0 if summary["status"] == "updated" else 1


if __name__ == "__main__":
    sys.exit(main())
