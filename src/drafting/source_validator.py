"""Validate draft source URLs against the documentation database."""

from __future__ import annotations

from pathlib import Path

from src.database.repository import DocumentationRepository


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def validate_documentation_sources(
    used_source_urls: list[str],
    database_path: Path,
    allowed_sources: list[str] | None = None,
) -> list[str]:
    """Return errors for URLs absent from the corpus or drafting context."""
    errors: list[str] = []
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        conn = repo._get_conn()
        rows = conn.execute(
            "SELECT source_url FROM documentation_pages WHERE status = 'active'"
        ).fetchall()
        corpus = {_normalize_url(str(row["source_url"])) for row in rows}
        context = (
            {_normalize_url(str(url)) for url in allowed_sources if str(url).strip()}
            if allowed_sources is not None
            else None
        )

        for original in used_source_urls:
            normalized = _normalize_url(str(original))
            if normalized not in corpus:
                errors.append(
                    f"Source URL '{original}' is not present in the documentation corpus."
                )
                continue
            if context is not None and normalized not in context:
                errors.append(
                    f"Source URL '{original}' is not allowed for this drafting context."
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
    """Return documentation URLs associated with the supplied context."""
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        conn = repo._get_conn()
        urls: set[str] = set()

        if ticket_id is not None:
            if analysis_id is None:
                rows = conn.execute(
                    "SELECT source_url FROM support_ticket_document_links WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT source_url FROM support_ticket_document_links
                       WHERE ticket_id = ? AND analysis_id = ?""",
                    (ticket_id, analysis_id),
                ).fetchall()
            urls.update(str(row["source_url"]) for row in rows)

        if feedback_id is not None:
            row = conn.execute(
                "SELECT affected_sources_json FROM support_feedback_items WHERE id = ?",
                (feedback_id,),
            ).fetchone()
            if row:
                import json

                affected = json.loads(row["affected_sources_json"])
                urls.update(str(url) for url in affected if isinstance(url, str))

        return sorted(urls)
    finally:
        repo.close()
