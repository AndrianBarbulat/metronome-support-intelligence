"""SQL schema for the Metronome documentation database."""

from __future__ import annotations

SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS documentation_pages (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url           TEXT    NOT NULL UNIQUE,
    title                TEXT    NOT NULL,
    index_description    TEXT    NOT NULL DEFAULT '',
    document_type        TEXT    NOT NULL DEFAULT '',
    category             TEXT,
    subcategory          TEXT,
    slug                 TEXT    NOT NULL DEFAULT '',
    file_name            TEXT    NOT NULL DEFAULT '',
    current_content_hash TEXT,
    current_version      INTEGER,
    status               TEXT    NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active', 'fetch_failed', 'missing_from_index')),
    first_seen_at        TEXT,
    last_seen_at         TEXT,
    last_checked_at      TEXT,
    last_changed_at      TEXT
);

CREATE TABLE IF NOT EXISTS documentation_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id        INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    content_hash   TEXT    NOT NULL,
    raw_markdown   TEXT    NOT NULL,
    http_status    INTEGER,
    final_url      TEXT,
    fetched_at     TEXT    NOT NULL,
    FOREIGN KEY (page_id) REFERENCES documentation_pages(id) ON DELETE CASCADE,
    UNIQUE (page_id, version_number)
);

CREATE TABLE IF NOT EXISTS documentation_sync_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT    NOT NULL,
    completed_at        TEXT,
    source_index_path   TEXT    NOT NULL,
    source_index_hash   TEXT    NOT NULL,
    discovered_count    INTEGER NOT NULL DEFAULT 0,
    fetched_count       INTEGER NOT NULL DEFAULT 0,
    new_count           INTEGER NOT NULL DEFAULT 0,
    changed_count       INTEGER NOT NULL DEFAULT 0,
    unchanged_count     INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    missing_count       INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'completed', 'completed_with_errors', 'failed')),
    errors_json         TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS documentation_parsed_versions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id             INTEGER NOT NULL,
    version_id          INTEGER NOT NULL,
    parser_version      TEXT    NOT NULL DEFAULT '1.0.0',
    parsed_json         TEXT    NOT NULL,
    section_count       INTEGER NOT NULL DEFAULT 0,
    code_block_count    INTEGER NOT NULL DEFAULT 0,
    table_count         INTEGER NOT NULL DEFAULT 0,
    openapi_block_count INTEGER NOT NULL DEFAULT 0,
    processed_at        TEXT    NOT NULL,
    FOREIGN KEY (page_id)    REFERENCES documentation_pages(id)    ON DELETE CASCADE,
    FOREIGN KEY (version_id) REFERENCES documentation_versions(id) ON DELETE CASCADE,
    UNIQUE (version_id, parser_version)
);

CREATE TABLE IF NOT EXISTS documentation_chunks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id             INTEGER NOT NULL,
    version_id          INTEGER NOT NULL,
    parsed_version_id   INTEGER NOT NULL,
    chunk_index         INTEGER NOT NULL,
    chunk_type          TEXT    NOT NULL DEFAULT 'prose',
    heading             TEXT,
    heading_path        TEXT    NOT NULL DEFAULT '[]',
    content             TEXT    NOT NULL,
    content_hash        TEXT    NOT NULL,
    token_estimate      INTEGER NOT NULL DEFAULT 0,
    metadata_json       TEXT    NOT NULL DEFAULT '{}',
    created_at          TEXT    NOT NULL,
    FOREIGN KEY (page_id)            REFERENCES documentation_pages(id)          ON DELETE CASCADE,
    FOREIGN KEY (version_id)         REFERENCES documentation_versions(id)       ON DELETE CASCADE,
    FOREIGN KEY (parsed_version_id)  REFERENCES documentation_parsed_versions(id) ON DELETE CASCADE,
    UNIQUE (version_id, chunk_index, content_hash)
);

CREATE VIRTUAL TABLE IF NOT EXISTS documentation_chunks_fts USING fts5(
    title,
    heading,
    heading_path,
    content,
    source_url,
    endpoint_path,
    http_method
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON documentation_chunks BEGIN
    INSERT INTO documentation_chunks_fts(rowid, title, heading, heading_path, content, source_url, endpoint_path, http_method)
    SELECT
        NEW.id,
        json_extract(NEW.metadata_json, '$.page_title'),
        NEW.heading,
        NEW.heading_path,
        NEW.content,
        json_extract(NEW.metadata_json, '$.source_url'),
        json_extract(NEW.metadata_json, '$.endpoint_path'),
        json_extract(NEW.metadata_json, '$.http_method');
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON documentation_chunks BEGIN
    INSERT INTO documentation_chunks_fts(documentation_chunks_fts, rowid, title, heading, heading_path, content, source_url, endpoint_path, http_method)
    VALUES ('delete', OLD.id, '', '', '', '', '', '', '');
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON documentation_chunks BEGIN
    INSERT INTO documentation_chunks_fts(documentation_chunks_fts, rowid, title, heading, heading_path, content, source_url, endpoint_path, http_method)
    VALUES ('delete', OLD.id, '', '', '', '', '', '', '');
    INSERT INTO documentation_chunks_fts(rowid, title, heading, heading_path, content, source_url, endpoint_path, http_method)
    SELECT
        NEW.id,
        json_extract(NEW.metadata_json, '$.page_title'),
        NEW.heading,
        NEW.heading_path,
        NEW.content,
        json_extract(NEW.metadata_json, '$.source_url'),
        json_extract(NEW.metadata_json, '$.endpoint_path'),
        json_extract(NEW.metadata_json, '$.http_method');
END;

CREATE TABLE IF NOT EXISTS support_tickets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    external_ticket_id  TEXT,
    subject             TEXT    NOT NULL DEFAULT '',
    customer_message    TEXT    NOT NULL DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'open',
    sanitized           INTEGER NOT NULL DEFAULT 0,
    redaction_count     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS support_ticket_evidence (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id             INTEGER NOT NULL,
    http_method           TEXT,
    endpoint_path         TEXT,
    request_headers_json  TEXT,
    request_body_json     TEXT,
    response_status       INTEGER,
    response_headers_json TEXT,
    response_body_json    TEXT,
    logs                  TEXT,
    expected_behavior     TEXT,
    actual_behavior       TEXT,
    created_at            TEXT    NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS support_ticket_analyses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id           INTEGER NOT NULL,
    analyzer_version    TEXT    NOT NULL DEFAULT '1.0.0',
    summary             TEXT    NOT NULL,
    signals_json        TEXT    NOT NULL DEFAULT '{}',
    observations_json   TEXT    NOT NULL DEFAULT '[]',
    validation_findings_json TEXT NOT NULL DEFAULT '[]',
    hypotheses_json     TEXT    NOT NULL DEFAULT '[]',
    missing_evidence_json TEXT  NOT NULL DEFAULT '[]',
    investigation_steps_json TEXT NOT NULL DEFAULT '[]',
    candidate_concepts_json TEXT NOT NULL DEFAULT '[]',
    selected_concepts_json TEXT NOT NULL DEFAULT '[]',
    concept_decisions_json TEXT NOT NULL DEFAULT '[]',
    merged_concept_groups_json TEXT NOT NULL DEFAULT '[]',
    retrieval_query     TEXT    NOT NULL DEFAULT '',
    retrieval_confidence REAL   NOT NULL DEFAULT 0.0,
    created_at          TEXT    NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE,
    UNIQUE (ticket_id, analyzer_version)
);

CREATE TABLE IF NOT EXISTS support_ticket_document_links (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id           INTEGER NOT NULL,
    analysis_id         INTEGER NOT NULL,
    page_title          TEXT    NOT NULL,
    source_url          TEXT    NOT NULL,
    heading             TEXT,
    relevance_score     REAL    NOT NULL DEFAULT 0.0,
    matched_tokens_json TEXT    NOT NULL DEFAULT '[]',
    ranking_reasons_json TEXT   NOT NULL DEFAULT '[]',
    source_capabilities_json TEXT NOT NULL DEFAULT '[]',
    source_purposes_json TEXT NOT NULL DEFAULT '[]',
    usage_type          TEXT    NOT NULL DEFAULT 'diagnosis',
    created_at          TEXT    NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_id) REFERENCES support_ticket_analyses(id) ON DELETE CASCADE
);
""".strip()
