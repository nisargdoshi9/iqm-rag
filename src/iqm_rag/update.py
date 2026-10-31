"""Incremental update: re-scrape only what changed, then refresh the cleaned data, the chunks and the index.

Each stage is already incremental on its own: the scraper skips articles whose sitemap date is unchanged and drops articles
that left the site, cleaning and chunking are fast local steps that are deterministic, and the index embeds only new or changed
chunks and deletes chunks that no longer exist. This module chains them and reports what changed at each step. If any article
fails to download or clean, the update stops before the later steps, so one failed page never removes an article from the index.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from iqm_rag import config
from iqm_rag.ingestion.chunking import CHUNK_REPORT_PATH, CHUNKS_JSONL, run_chunking
from iqm_rag.ingestion.embeddings import Embedder
from iqm_rag.ingestion.indexing import run_indexing
from iqm_rag.scraping.normalization import ProcessedPaths, read_jsonl, run_normalization
from iqm_rag.scraping.scraper import CrawlPaths, PoliteFetcher, plan_crawl, run_crawl


@dataclass(frozen=True)
class UpdatePaths:
    crawl: CrawlPaths
    processed: ProcessedPaths
    chunks: Path
    chunk_report: Path
    index: Path

    @classmethod
    def default(cls) -> "UpdatePaths":
        return cls(CrawlPaths.default(), ProcessedPaths.default(), CHUNKS_JSONL, CHUNK_REPORT_PATH, config.CHROMA_DIR)


def _chunk_hashes(path: Path) -> dict[str, str]:
    return {chunk["chunk_id"]: chunk["content_hash"] for chunk in read_jsonl(path)} if path.exists() else {}


def chunk_changes(before: dict[str, str], after: dict[str, str]) -> dict:
    """How the chunk set changed: chunks that are new, whose embedded text changed, or that no longer exist."""
    return {"total": len(after), "added": len(set(after) - set(before)), "removed": len(set(before) - set(after)),
            "changed": sum(1 for chunk_id in after if chunk_id in before and before[chunk_id] != after[chunk_id])}


def _scrape_summary(report: dict) -> dict:
    new = report["new_since_last_run"]
    return {"discovered": report["discovered"], "new": len(new), "changed": len([a for a in report["fetched_ok"] if a not in new]),
            "unchanged": report["unchanged_skipped"], "removed": report["removed_dropped"], "failed": report["failed"],
            "removal_skipped_reason": report["removal_skipped_reason"], "requests": report["requests_made"]}


def plan_update(fetcher: PoliteFetcher, paths: UpdatePaths, force: bool = False) -> dict:
    """What an update would fetch and drop. Only the collection pages and the sitemap are requested; nothing is written."""
    return plan_crawl(fetcher, paths.crawl, force=force)


def run_update(fetcher: Optional[PoliteFetcher], embedder: Embedder, paths: UpdatePaths, force: bool = False, skip_scrape: bool = False) -> dict:
    """Scrape (unless skipped), clean, chunk and index; return a summary with a `status` of updated or stopped."""
    summary: dict = {"status": "updated"}
    if not skip_scrape:
        report = run_crawl(fetcher, paths.crawl, force=force)
        summary["scrape"] = _scrape_summary(report)
        if report["failed_count"]:
            return {**summary, "status": "stopped", "reason": f"{report['failed_count']} article(s) failed to download; nothing was cleaned, chunked or indexed. Run the update again to retry them."}
    cleaned = run_normalization(paths.processed)
    summary["clean"] = {"articles": cleaned["articles_processed"], "failed": cleaned["failed"]}
    if cleaned["failed"]:
        return {**summary, "status": "stopped", "reason": f"{len(cleaned['failed'])} article(s) failed to clean; nothing was chunked or indexed."}
    before = _chunk_hashes(paths.chunks)
    run_chunking(None, paths.processed.articles, paths.chunks, paths.chunk_report)
    summary["chunks"] = chunk_changes(before, _chunk_hashes(paths.chunks))
    index = run_indexing(read_jsonl(paths.chunks), embedder, paths.index)
    summary["index"] = {key: index[key] for key in ("added", "updated", "unchanged", "deleted", "embedded_tokens")}
    return summary


def describe(summary: dict) -> str:
    """The summary as a few readable lines."""
    lines = []
    if "scrape" in summary:
        s = summary["scrape"]
        lines.append(f"Scrape: {s['discovered']} articles found; {s['new']} new, {s['changed']} changed, {s['unchanged']} unchanged (skipped), "
                     f"{len(s['removed'])} removed from the site (dropped), {len(s['failed'])} failed; {s['requests']} requests.")
        if s["removal_skipped_reason"]:
            lines.append(f"  Removals NOT applied: {s['removal_skipped_reason']}.")
    if "clean" in summary:
        lines.append(f"Clean: {summary['clean']['articles']} articles.")
    if "chunks" in summary:
        c = summary["chunks"]
        lines.append(f"Chunks: {c['total']} ({c['added']} new, {c['changed']} changed, {c['removed']} removed).")
    if "index" in summary:
        i = summary["index"]
        lines.append(f"Index: {i['added']} added, {i['updated']} updated, {i['deleted']} deleted, {i['unchanged']} unchanged; {i['embedded_tokens']} tokens embedded.")
    lines.append("Status: " + summary["status"] + (f" ({summary['reason']})" if summary.get("reason") else ""))
    return "\n".join(lines)


def describe_plan(plan: dict) -> str:
    lines = [f"Dry run (nothing fetched or written; {plan['requests_made']} discovery requests): {plan['discovered']} articles on the site.",
             f"  New: {len(plan['new'])} {plan['new'][:10]}", f"  To refetch (changed or failed before): {len(plan['refetch'])} {plan['refetch'][:10]}",
             f"  Unchanged: {plan['unchanged']}", f"  Removed from the site: {len(plan['removed'])} {plan['removed'][:10]}"]
    if plan["removal_skipped_reason"]:
        lines.append(f"  Removals would NOT be applied: {plan['removal_skipped_reason']}.")
    return "\n".join(lines)


def to_json(summary: dict) -> str:
    return json.dumps(summary, indent=2, ensure_ascii=False)
