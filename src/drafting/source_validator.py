"""Validate draft source URLs against the documentation database."""

from __future__ import annotations

from pathlib import Path
from src.database.repository import DocumentationRepository


def validate_documentation_sources(
    used_source_urls: list[str],
    database_path: Path,
    allowed_sources: list[str] | None = None,
) -> list[str]:
    """Return a list of error messages for invalid source URLs.

    Parameters
    ----------
    used_source_urls:
        URLs returned by the provider.
    database_path:
        Path to the documentation SQLite database.
    allowed_sources:
        Optional explicit allowlist. When omitted, any URL present in
        ``documentation_pages`` is accepted.
    """
    errors: list[str] = []
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()

    try:
        if allowed_sources is not None:
            allowed_set = set(allowed_sources)
        else:
            # Build allowlist from all documentation pages
            conn = repo._get_conn()
            rows = conn.execute(
                "SELECT source_url FROM documentation_pages WHERE status = 'active'"
            ).fetchall()
            allowed_set = {row["source_url"] for row in rows}

        for url in used_source_urls:
            normalized = url.strip().rstrip("/")
            found = False
            # Exact match
            if normalized in allowed_set:
                found = True
            # Try with trailing slash variants
            if not found:
                for allowed in allowed_set:
                    if allowed.rstrip("/") == normalized:
                        found = True
                        break
            if not found:
                errors.append(
                    f"Source URL '{url}' is not present in the documentation corpus."
                )

        return errors
    finally:
        repo.close()


def get_allowed_drafting_sources(
    database_path: Path,
    ticket_id: int | None = None,
    analysis_id: int | None = None,
    resolution_id: int | None = None,
    feedback_id: int | None = None,
) -> list[str]:
    """Return the list of documentation URLs legitimately associated
    with the given ticket, analysis, resolution, or feedback item."""
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        conn = repo._get_conn()
        urls: set[str] = set()

        # Ticket + analysis links
        if ticket_id is not None:
            rows = conn.execute(
                "SELECT source_url FROM support_ticket_document_links WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchall()
            urls.update(r["source_url"] for r in rows)

        # Feedback affected sources
        if feedback_id is not None:
            row = conn.execute(
                "SELECT affected_sources_json FROM support_feedback_items WHERE id = ?",
                (feedback_id,),
            ).fetchone()
            if row:
                import json
                affected = json.loads(row["affected_sources_json"])
                urls.update(u for u in affected if isinstance(u, str))

        return sorted(urls)
    finally:
        repo.close()