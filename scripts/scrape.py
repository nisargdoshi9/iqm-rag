"""Scrape and save the IQM Help Center articles (FR-1).

Requires SCRAPER_USER_AGENT in the environment, for example:
    export SCRAPER_USER_AGENT="IQM-RAG-Assignment-Bot/0.1 (contact: you@example.com)"
    python scripts/scrape.py            # rerun skips unchanged articles
    python scripts/scrape.py --force    # refetch everything
"""

import argparse
import logging
import sys

from iqm_rag import config
from iqm_rag.scraping.scraper import CrawlAborted, CrawlPaths, PoliteFetcher, run_crawl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape the IQM Help Center.")
    parser.add_argument("--force", action="store_true", help="refetch every article, ignoring the rerun rule")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        fetcher = PoliteFetcher(
            user_agent=config.scraper_user_agent(),
            delay_seconds=config.scraper_delay_seconds(),
        )
        report = run_crawl(fetcher, CrawlPaths.default(), force=args.force)
    except (RuntimeError, CrawlAborted) as exc:
        print(f"Crawl stopped: {exc}", file=sys.stderr)
        return 2

    print(
        f"Discovered {report['discovered']}: succeeded {report['succeeded_count']}, "
        f"failed {report['failed_count']}, unchanged skipped {report['unchanged_skipped']}, "
        f"requests {report['requests_made']}. Report: {config.CRAWL_REPORT_PATH}"
    )
    return 1 if report["failed_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
