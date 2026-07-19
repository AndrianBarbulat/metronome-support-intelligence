"""Repository layer for documentation-persistence operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.documentation.models import DocumentationEntry, DownloadResult, SyncSummary
from src.documentation.hashing import calculate_content_hash
from src.database.connection import get_connection
from src.database.schema import SCHEMA_SQL


class DocumentationRepository:
    """Thin repository wrapping SQLite operations for the documentation DB."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_connection(self._db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def initialize_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        self._ensure_phase44_columns(conn)
        conn.commit()

    # ------------------------------------------------------------------
    # Sync runs
    # ------------------------------------------------------------------
    def start_sync_run(
        self,
        source_index_path: str,
        source_index_hash: str,
        discovered_count: int,
    ) -> int:
        conn = self._get_conn()
        now = self._utc_now()
        cur = conn.execute(
            """INSERT INTO documentation_sync_runs
               (started_at, source_index_path, source_index_hash,
                discovered_count, status)
               VALUES (?, ?, ?, ?, 'running')""",
            (now, source_index_path, source_index_hash, discovered_count),
        )
        conn.commit()
        return cur.lastrowid

    def complete_sync_run(
        self,
        run_id: int,
        summary: SyncSummary,
        errors: list[dict],
        status: str,
    ) -> None:
        conn = self._get_conn()
        import json

        now = self._utc_now()
        conn.execute(
            """UPDATE documentation_sync_runs
               SET completed_at = ?,
                   fetched_count = ?,
                   new_count = ?,
                   changed_count = ?,
                   unchanged_count = ?,
                   failed_count = ?,
                   missing_count = ?,
                   status = ?,
                   errors_json = ?
               WHERE id = ?""",
            (
                now,
                summary.fetched_count,
                summary.new_count,
                summary.changed_count,
                summary.unchanged_count,
                summary.failed_count,
                summary.missing_count,
                status,
                json.dumps(errors, ensure_ascii=False),
                run_id,
            ),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def get_page_by_url(self, source_url: str) -> sqlite3.Row | None:
        conn = self._get_conn()
        return conn.execute(
            "SELECT * FROM documentation_pages WHERE source_url = ?",
            (source_url,),
        ).fetchone()

    def _upsert_page_base(
        self, entry: DocumentationEntry, timestamp: str, conn: sqlite3.Connection
    ) -> int:
        """Insert-or-replace just the index-metadata columns and return the page id."""
        cur = conn.execute(
            """INSERT INTO documentation_pages
               (source_url, title, index_description, document_type,
                category, subcategory, slug, file_name, status,
                first_seen_at, last_seen_at, last_checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
               ON CONFLICT(source_url) DO UPDATE SET
                   title = excluded.title,
                   index_description = excluded.index_description,
                   document_type = excluded.document_type,
                   category = excluded.category,
                   subcategory = excluded.subcategory,
                   slug = excluded.slug,
                   file_name = excluded.file_name,
                   status = 'active',
                   last_seen_at = excluded.last_seen_at,
                   last_checked_at = excluded.last_checked_at""",
            (
                entry.url,
                entry.title,
                entry.description,
                entry.document_type,
                entry.category,
                entry.subcategory,
                entry.slug,
                entry.file_name,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        return cur.lastrowid

    # ------------------------------------------------------------------
    # New page + version 1  (atomic)
    # ------------------------------------------------------------------
    def create_page_with_version(
        self,
        entry: DocumentationEntry,
        result: DownloadResult,
        content_hash: str,
        timestamp: str,
    ) -> int:
        conn = self._get_conn()
        try:
            page_id = self._upsert_page_base(entry, timestamp, conn)
            conn.execute(
                """UPDATE documentation_pages
                   SET current_content_hash = ?,
                       current_version = 1,
                       last_changed_at = ?
                   WHERE id = ?""",
                (content_hash, timestamp, page_id),
            )
            conn.execute(
                """INSERT INTO documentation_versions
                   (page_id, version_number, content_hash, raw_markdown,
                    http_status, final_url, fetched_at)
                   VALUES (?, 1, ?, ?, ?, ?, ?)""",
                (
                    page_id,
                    content_hash,
                    result.raw_markdown or "",
                    result.http_status,
                    result.final_url,
                    timestamp,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return page_id

    # ------------------------------------------------------------------
    # Unchanged page
    # ------------------------------------------------------------------
    def mark_page_unchanged(
        self,
        page_id: int,
        entry: DocumentationEntry,
        timestamp: str,
    ) -> None:
        conn = self._get_conn()
        self._upsert_page_base(entry, timestamp, conn)
        conn.commit()

    # ------------------------------------------------------------------
    # Changed page — new version  (atomic)
    # ------------------------------------------------------------------
    def create_new_version(
        self,
        page_id: int,
        entry: DocumentationEntry,
        result: DownloadResult,
        content_hash: str,
        timestamp: str,
    ) -> int:
        conn = self._get_conn()
        try:
            self._upsert_page_base(entry, timestamp, conn)

            # Determine next version number
            row = conn.execute(
                "SELECT MAX(version_number) FROM documentation_versions WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            next_ver = (row[0] or 0) + 1

            conn.execute(
                """UPDATE documentation_pages
                   SET current_content_hash = ?,
                       current_version = ?,
                       last_changed_at = ?
                   WHERE id = ?""",
                (content_hash, next_ver, timestamp, page_id),
            )
            conn.execute(
                """INSERT INTO documentation_versions
                   (page_id, version_number, content_hash, raw_markdown,
                    http_status, final_url, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    page_id,
                    next_ver,
                    content_hash,
                    result.raw_markdown or "",
                    result.http_status,
                    result.final_url,
                    timestamp,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return next_ver

    # ------------------------------------------------------------------
    # Fetch failure
    # ------------------------------------------------------------------
    def record_fetch_failure(
        self,
        entry: DocumentationEntry,
        timestamp: str,
    ) -> None:
        conn = self._get_conn()
        existing = self.get_page_by_url(entry.url)
        if existing:
            conn.execute(
                """UPDATE documentation_pages
                   SET last_checked_at = ?,
                       status = CASE
                           WHEN status = 'missing_from_index' THEN 'missing_from_index'
                           ELSE 'fetch_failed'
                       END
                   WHERE source_url = ?""",
                (timestamp, entry.url),
            )
        else:
            conn.execute(
                """INSERT INTO documentation_pages
                   (source_url, title, index_description, document_type,
                    category, subcategory, slug, file_name, status,
                    first_seen_at, last_checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'fetch_failed', ?, ?)""",
                (
                    entry.url,
                    entry.title,
                    entry.description,
                    entry.document_type,
                    entry.category,
                    entry.subcategory,
                    entry.slug,
                    entry.file_name,
                    timestamp,
                    timestamp,
                ),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Missing from index
    # ------------------------------------------------------------------
    def mark_missing_pages(
        self,
        active_urls: set[str],
        timestamp: str,
    ) -> int:
        conn = self._get_conn()
        all_rows = conn.execute("SELECT id, source_url FROM documentation_pages").fetchall()
        missing_count = 0
        for row in all_rows:
            if row["source_url"] not in active_urls:
                conn.execute(
                    "UPDATE documentation_pages SET status = 'missing_from_index' WHERE id = ?",
                    (row["id"],),
                )
                missing_count += 1
        conn.commit()
        return missing_count

    # ------------------------------------------------------------------
    # Phase 3 — Parsed versions & chunks
    # ------------------------------------------------------------------
    def get_active_pages_with_current_version(self) -> list[sqlite3.Row]:
        conn = self._get_conn()
        return conn.execute(
            """SELECT p.*, v.id as version_id, v.raw_markdown, v.content_hash as version_hash
               FROM documentation_pages p
               JOIN documentation_versions v ON v.page_id = p.id
                   AND v.version_number = p.current_version
               WHERE p.status = 'active'
               ORDER BY p.id"""
        ).fetchall()

    def get_parsed_version(
        self, version_id: int, parser_version: str
    ) -> sqlite3.Row | None:
        conn = self._get_conn()
        return conn.execute(
            """SELECT * FROM documentation_parsed_versions
               WHERE version_id = ? AND parser_version = ?""",
            (version_id, parser_version),
        ).fetchone()

    def upsert_parsed_version(
        self,
        page_id: int,
        version_id: int,
        parser_version: str,
        parsed_json: str,
        section_count: int,
        code_block_count: int,
        table_count: int,
        openapi_block_count: int,
        timestamp: str,
    ) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            """INSERT INTO documentation_parsed_versions
               (page_id, version_id, parser_version, parsed_json,
                section_count, code_block_count, table_count,
                openapi_block_count, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(version_id, parser_version) DO UPDATE SET
                   parsed_json = excluded.parsed_json,
                   section_count = excluded.section_count,
                   code_block_count = excluded.code_block_count,
                   table_count = excluded.table_count,
                   openapi_block_count = excluded.openapi_block_count,
                   processed_at = excluded.processed_at""",
            (
                page_id,
                version_id,
                parser_version,
                parsed_json,
                section_count,
                code_block_count,
                table_count,
                openapi_block_count,
                timestamp,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def replace_chunks(
        self,
        parsed_version_id: int,
        page_id: int,
        version_id: int,
        chunks: list[dict],
        timestamp: str,
    ) -> None:
        """Atomically delete old chunks for (version_id) and insert new ones."""
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM documentation_chunks WHERE version_id = ?",
                (version_id,),
            )
            for idx, ch in enumerate(chunks):
                conn.execute(
                    """INSERT INTO documentation_chunks
                       (page_id, version_id, parsed_version_id, chunk_index,
                        chunk_type, heading, heading_path, content,
                        content_hash, token_estimate, metadata_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        page_id,
                        version_id,
                        parsed_version_id,
                        idx,
                        ch["chunk_type"],
                        ch["heading"],
                        ch["heading_path"],
                        ch["content"],
                        ch["content_hash"],
                        ch["token_estimate"],
                        ch["metadata_json"],
                        timestamp,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Phase 3 — Search
    # ------------------------------------------------------------------
    def search_fts(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
        document_type: str | None = None,
    ) -> list[dict]:
        conn = self._get_conn()
        return _execute_fts_search(conn, query, limit, category, document_type)

    def search_exact_title(self, title: str, limit: int = 5) -> list[dict]:
        """Search chunks where page title exactly matches."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT
                10 AS score, c.id, c.chunk_type, c.heading, c.heading_path,
                substr(c.content, 1, 200) AS content_excerpt,
                c.metadata_json, c.content
            FROM documentation_chunks c
            WHERE json_extract(c.metadata_json, '$.page_title') = ?
            LIMIT ?""",
            (title, limit),
        ).fetchall()
        return _rows_to_results(rows)

    def search_technical_token(self, token: str, limit: int = 20) -> list[dict]:
        """Search chunks containing an exact technical token."""
        conn = self._get_conn()
        # Try FTS first if available
        try:
            conn.execute("SELECT count(*) FROM documentation_chunks_fts").fetchone()
            rows = conn.execute(
                """SELECT
                    rank AS score, c.id, c.chunk_type, c.heading, c.heading_path,
                    snippet(documentation_chunks_fts, 2, '<b>', '</b>', '...', 40) AS content_excerpt,
                    c.metadata_json, c.content
                FROM documentation_chunks_fts f
                JOIN documentation_chunks c ON c.id = f.rowid
                WHERE documentation_chunks_fts MATCH ?
                ORDER BY rank LIMIT ?""",
                (token, limit),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                """SELECT 0 AS score, id, chunk_type, heading, heading_path,
                   substr(content, 1, 200) AS content_excerpt,
                   metadata_json, content
                FROM documentation_chunks WHERE content LIKE ?
                LIMIT ?""",
                (f"%{token}%", limit),
            ).fetchall()
        return _rows_to_results(rows)

    def search_endpoint(self, endpoint_path: str, limit: int = 10) -> list[dict]:
        """Search chunks with a matching endpoint path."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT 20 AS score, id, chunk_type, heading, heading_path,
               substr(content, 1, 200) AS content_excerpt,
               metadata_json, content
            FROM documentation_chunks
            WHERE json_extract(metadata_json, '$.endpoint_path') LIKE ?
            LIMIT ?""",
            (f"%{endpoint_path}%", limit),
        ).fetchall()
        return _rows_to_results(rows)

    def search_operation_id(self, op_id: str, limit: int = 10) -> list[dict]:
        """Search chunks with matching operation ID."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT 20 AS score, id, chunk_type, heading, heading_path,
               substr(content, 1, 200) AS content_excerpt,
               metadata_json, content
            FROM documentation_chunks
            WHERE json_extract(metadata_json, '$.operation_id') LIKE ?
            LIMIT ?""",
            (f"%{op_id}%", limit),
        ).fetchall()
        return _rows_to_results(rows)

    def search_all_chunks_block(self) -> list[dict]:
        """Return ALL chunk rows with metadata. Used for evaluation brute-force."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id, chunk_type, heading, heading_path,
               content, metadata_json
            FROM documentation_chunks"""
        ).fetchall()
        return _rows_to_results(rows)

    # ------------------------------------------------------------------
    # Phase 4 — Ticket persistence
    # ------------------------------------------------------------------
    def persist_ticket_analysis(self, ticket, report, analyzer_version: str) -> int:
        import json
        conn = self._get_conn()
        now = self._utc_now()
        try:
            # Insert ticket
            cur = conn.execute(
                """INSERT INTO support_tickets
                   (external_ticket_id, subject, customer_message, status,
                    sanitized, redaction_count, created_at, updated_at)
                   VALUES (?, ?, ?, 'analyzed', 1, 0, ?, ?)""",
                (ticket.external_ticket_id, ticket.subject,
                 ticket.customer_message, now, now),
            )
            ticket_id = cur.lastrowid

            # Insert evidence
            conn.execute(
                """INSERT INTO support_ticket_evidence
                   (ticket_id, http_method, endpoint_path, request_headers_json,
                    request_body_json, response_status, response_headers_json,
                    response_body_json, logs, expected_behavior, actual_behavior,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticket_id, ticket.http_method, ticket.endpoint_path,
                    json.dumps(ticket.request_headers or {}, default=str),
                    json.dumps(ticket.request_body or {}, default=str),
                    ticket.response_status,
                    json.dumps(ticket.response_headers or {}, default=str),
                    json.dumps(ticket.response_body or {}, default=str),
                    ticket.logs, ticket.expected_behavior, ticket.actual_behavior,
                    now,
                ),
            )

            # Insert analysis
            cur2 = conn.execute(
                """INSERT OR REPLACE INTO support_ticket_analyses
                   (ticket_id, analyzer_version, summary, signals_json,
                    observations_json, validation_findings_json,
                    hypotheses_json, missing_evidence_json,
                    investigation_steps_json, candidate_concepts_json,
                    selected_concepts_json, concept_decisions_json,
                    merged_concept_groups_json, retrieval_query,
                    retrieval_confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticket_id, analyzer_version, report.summary,
                    json.dumps(_dataclass_to_dict(report.signals), default=str),
                    json.dumps([_dataclass_to_dict(o) for o in report.observations], default=str),
                    json.dumps([_dataclass_to_dict(f) for f in report.validation_findings], default=str),
                    json.dumps([_dataclass_to_dict(h) for h in report.hypotheses], default=str),
                    json.dumps([_dataclass_to_dict(m) for m in report.missing_evidence], default=str),
                    json.dumps([_dataclass_to_dict(s) for s in report.investigation_steps], default=str),
                    json.dumps(report.candidate_concept_codes),
                    json.dumps(report.selected_concept_codes),
                    json.dumps([_dataclass_to_dict(d) for d in report.concept_decisions], default=str),
                    json.dumps([_dataclass_to_dict(g) for g in report.merged_concept_groups], default=str),
                    report.retrieval_query,
                    report.retrieval_confidence,
                    now,
                ),
            )
            analysis_id = cur2.lastrowid

            # Insert doc links
            for source in report.documentation_sources:
                conn.execute(
                    """INSERT INTO support_ticket_document_links
                       (ticket_id, analysis_id, page_title, source_url, heading,
                        relevance_score, matched_tokens_json, ranking_reasons_json,
                        source_capabilities_json, source_purposes_json,
                        usage_type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ticket_id, analysis_id, source.page_title, source.source_url,
                        source.heading, source.relevance_score,
                        json.dumps(source.matched_tokens),
                        json.dumps(source.ranking_reasons),
                        json.dumps(source.source_capabilities),
                        json.dumps(source.source_purposes),
                        source.usage_type, now,
                    ),
                )

            conn.commit()
            return ticket_id
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def _ensure_phase44_columns(self, conn: sqlite3.Connection) -> None:
        self._ensure_columns(conn, "support_ticket_analyses", {
            "candidate_concepts_json": "TEXT NOT NULL DEFAULT '[]'",
            "selected_concepts_json": "TEXT NOT NULL DEFAULT '[]'",
            "concept_decisions_json": "TEXT NOT NULL DEFAULT '[]'",
            "merged_concept_groups_json": "TEXT NOT NULL DEFAULT '[]'",
        })
        self._ensure_columns(conn, "support_ticket_document_links", {
            "source_capabilities_json": "TEXT NOT NULL DEFAULT '[]'",
            "source_purposes_json": "TEXT NOT NULL DEFAULT '[]'",
        })

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, definition in columns.items():
            if column_name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _dataclass_to_dict(obj):
    """Convert a dataclass instance to a dict, recursively."""
    from dataclasses import fields, is_dataclass
    if not is_dataclass(obj):
        return str(obj)
    result = {}
    for f in fields(obj):
        value = getattr(obj, f.name)
        if is_dataclass(value):
            result[f.name] = _dataclass_to_dict(value)
        elif isinstance(value, list):
            result[f.name] = [_dataclass_to_dict(v) if is_dataclass(v) else v for v in value]
        else:
            result[f.name] = value
    return result


def _execute_fts_search(
    conn,
    query: str,
    limit: int,
    category: str | None,
    document_type: str | None,
) -> list[dict]:
    import json

    try:
        conn.execute("SELECT count(*) FROM documentation_chunks_fts").fetchone()
        has_fts = True
    except Exception:
        has_fts = False

    if has_fts:
        where_clauses = ["documentation_chunks_fts MATCH ?"]
        params: list = [query]
        if category:
            where_clauses.append("json_extract(c.metadata_json, '$.category') = ?")
            params.append(category)
        if document_type:
            where_clauses.append("json_extract(c.metadata_json, '$.document_type') = ?")
            params.append(document_type)

        sql = f"""SELECT
            rank AS score,
            c.id,
            c.chunk_type,
            c.heading,
            c.heading_path,
            snippet(documentation_chunks_fts, 2, '<b>', '</b>', '...', 40) AS content_excerpt,
            c.metadata_json,
            c.content
        FROM documentation_chunks_fts f
        JOIN documentation_chunks c ON c.id = f.rowid
        WHERE {' AND '.join(where_clauses)}
        ORDER BY rank
        LIMIT ?"""
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    else:
        like = f"%{query}%"
        where_clauses = ["c.content LIKE ?"]
        params = [like]
        if category:
            where_clauses.append("json_extract(c.metadata_json, '$.category') = ?")
            params.append(category)
        if document_type:
            where_clauses.append("json_extract(c.metadata_json, '$.document_type') = ?")
            params.append(document_type)

        sql = f"""SELECT
            0 AS score,
            c.id,
            c.chunk_type,
            c.heading,
            c.heading_path,
            substr(c.content, 1, 120) AS content_excerpt,
            c.metadata_json,
            c.content
        FROM documentation_chunks c
        WHERE {' AND '.join(where_clauses)}
        LIMIT ?"""
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()

    return _rows_to_results(rows)


def _rows_to_results(rows) -> list[dict]:
    import json

    results: list[dict] = []
    for row in rows:
        meta = json.loads(row["metadata_json"])
        results.append(
            {
                "score": row["score"],
                "id": row["id"],
                "page_title": meta.get("page_title", ""),
                "heading": row["heading"],
                "heading_path": json.loads(row["heading_path"]),
                "content_excerpt": row["content_excerpt"],
                "source_url": meta.get("source_url", ""),
                "document_type": meta.get("document_type", ""),
                "category": meta.get("category"),
                "http_method": meta.get("http_method"),
                "endpoint_path": meta.get("endpoint_path"),
                "chunk_type": row["chunk_type"],
                "content": row["content"],
                "metadata_json": row["metadata_json"],
            }
        )
    return results
