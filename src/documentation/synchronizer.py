"""Orchestrates the documentation sync pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .downloader import USER_AGENT, download_article
from .hashing import calculate_content_hash
from .index_loader import IndexLoadError, load_documentation_index
from .models import DocumentationEntry, DownloadResult, SyncSummary
from src.database.repository import DocumentationRepository


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _download_all(
    entries: list[DocumentationEntry],
    concurrency: int,
) -> list[DownloadResult]:
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency + 2)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        tasks = [download_article(client, e, semaphore) for e in entries]
        return await asyncio.gather(*tasks)


def _build_error_dict(result: DownloadResult, title: str) -> dict:
    return {
        "url": result.url,
        "title": title,
        "error_type": result.error_type or "unknown",
        "http_status": result.http_status,
        "message": result.error_message or "",
    }


async def synchronize_documentation(
    index_path: Path,
    database_path: Path,
    concurrency: int = 5,
) -> SyncSummary:
    """Run a full documentation sync.

    1. Load and validate the index JSON.
    2. Initialise the database schema.
    3. Start a sync-run record.
    4. Download every article concurrently.
    5. Upsert pages and versions atomically.
    6. Mark pages missing from the current index.
    7. Complete the sync-run record.
    8. Return a :class:`SyncSummary`.
    """
    # 1. Load index
    print("Loading documentation index …")
    doc_index = load_documentation_index(index_path)
    discovered = len(doc_index.entries)
    if discovered == 0:
        print("No valid entries found in the index. Nothing to sync.")
        return SyncSummary()

    # Hash of the raw index file for reproducibility
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()

    # 2. Schema
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()

    # 3. Start sync run
    run_id = repo.start_sync_run(
        source_index_path=str(index_path),
        source_index_hash=index_hash,
        discovered_count=discovered,
    )
    print(f"Discovered articles: {discovered}")

    # 4. Download
    print("Downloading articles …")
    results = await _download_all(doc_index.entries, concurrency)

    # Build lookup entry by url
    entry_by_url: dict[str, DocumentationEntry] = {e.url: e for e in doc_index.entries}

    # 5. Process results
    summary = SyncSummary(discovered_count=discovered)
    errors: list[dict] = []
    timestamp = _utc_now()

    for result in results:
        entry = entry_by_url.get(result.url)
        if entry is None:
            continue  # shouldn't happen

        if not result.success:
            # Fetch failure
            summary.failed_count += 1
            try:
                repo.record_fetch_failure(entry, timestamp)
            except Exception:
                pass
            errors.append(_build_error_dict(result, entry.title))
            continue

        summary.fetched_count += 1

        content_hash = calculate_content_hash(result.raw_markdown or "")
        page_row = repo.get_page_by_url(entry.url)

        if page_row is None:
            # New article
            repo.create_page_with_version(entry, result, content_hash, timestamp)
            summary.new_count += 1
        else:
            page_id = page_row["id"]
            existing_hash = page_row["current_content_hash"] or ""
            if existing_hash == content_hash:
                # Unchanged
                repo.mark_page_unchanged(page_id, entry, timestamp)
                summary.unchanged_count += 1
            else:
                # Changed
                repo.create_new_version(page_id, entry, result, content_hash, timestamp)
                summary.changed_count += 1

    # 6. Mark missing pages
    active_urls = {e.url for e in doc_index.entries}
    summary.missing_count = repo.mark_missing_pages(active_urls, timestamp)

    # 7. Finalise sync run
    run_status = "completed" if summary.failed_count == 0 else "completed_with_errors"
    repo.complete_sync_run(run_id, summary, errors, run_status)

    repo.close()
    return summary