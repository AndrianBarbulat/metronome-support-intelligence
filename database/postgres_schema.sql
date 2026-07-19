-- Metronome Support Intelligence — PostgreSQL Schema
-- For Vercel production deployment via Supabase.
-- Run once to initialize all tables and indexes.

BEGIN;

-- documentation_pages
CREATE TABLE IF NOT EXISTS documentation_pages (
    id                   SERIAL PRIMARY KEY,
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

-- documentation_versions
CREATE TABLE IF NOT EXISTS documentation_versions (
    id             SERIAL PRIMARY KEY,
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

-- documentation_sync_runs
CREATE TABLE IF NOT EXISTS documentation_sync_runs (
    id                  SERIAL PRIMARY KEY,
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

-- documentation_parsed_versions
CREATE TABLE IF NOT EXISTS documentation_parsed_versions (
    id                  SERIAL PRIMARY KEY,
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

-- documentation_chunks
CREATE TABLE IF NOT EXISTS documentation_chunks (
    id                  SERIAL PRIMARY KEY,
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

-- PostgreSQL full-text search index on chunks
CREATE INDEX IF NOT EXISTS idx_chunks_fts
    ON documentation_chunks
    USING gin(to_tsvector('english', coalesce(content, '')));

-- Index for documentation search & lookup
CREATE INDEX IF NOT EXISTS idx_pages_source_url ON documentation_pages(source_url);
CREATE INDEX IF NOT EXISTS idx_pages_status ON documentation_pages(status);
CREATE INDEX IF NOT EXISTS idx_chunks_page_id ON documentation_chunks(page_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type ON documentation_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_heading ON documentation_chunks(heading);

-- Indexes for JSON metadata access
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_endpoint ON documentation_chunks ((metadata_json::jsonb->>'endpoint_path'));
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_http_method ON documentation_chunks ((metadata_json::jsonb->>'http_method'));
CREATE INDEX IF NOT EXISTS idx_pages_category ON documentation_pages(category);
CREATE INDEX IF NOT EXISTS idx_pages_document_type ON documentation_pages(document_type);

-- support_tickets
CREATE TABLE IF NOT EXISTS support_tickets (
    id                  SERIAL PRIMARY KEY,
    external_ticket_id  TEXT,
    subject             TEXT    NOT NULL DEFAULT '',
    customer_message    TEXT    NOT NULL DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'open',
    sanitized           INTEGER NOT NULL DEFAULT 0,
    redaction_count     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_created ON support_tickets(created_at DESC);

-- support_ticket_evidence
CREATE TABLE IF NOT EXISTS support_ticket_evidence (
    id                    SERIAL PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_evidence_ticket ON support_ticket_evidence(ticket_id);

-- support_ticket_analyses
CREATE TABLE IF NOT EXISTS support_ticket_analyses (
    id                  SERIAL PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_analyses_ticket ON support_ticket_analyses(ticket_id);

-- support_ticket_document_links
CREATE TABLE IF NOT EXISTS support_ticket_document_links (
    id                  SERIAL PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_links_ticket ON support_ticket_document_links(ticket_id);
CREATE INDEX IF NOT EXISTS idx_links_source ON support_ticket_document_links(source_url);

-- support_ticket_resolutions
CREATE TABLE IF NOT EXISTS support_ticket_resolutions (
    id                    SERIAL PRIMARY KEY,
    ticket_id             INTEGER NOT NULL,
    analysis_id           INTEGER NOT NULL,
    resolution_status     TEXT    NOT NULL,
    root_cause_code       TEXT    NOT NULL,
    root_cause_category   TEXT    NOT NULL,
    root_cause_summary    TEXT    NOT NULL,
    root_cause_details    TEXT    NOT NULL,
    resolution_summary    TEXT    NOT NULL,
    resolution_steps_json TEXT    NOT NULL DEFAULT '[]',
    verification_steps_json TEXT  NOT NULL DEFAULT '[]',
    verification_results_json TEXT NOT NULL DEFAULT '[]',
    affected_component    TEXT,
    affected_endpoint     TEXT,
    affected_configuration TEXT,
    confirmed_by          TEXT    NOT NULL,
    confirmed_at          TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_id) REFERENCES support_ticket_analyses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_resolutions_ticket ON support_ticket_resolutions(ticket_id);

-- support_resolution_identifiers
CREATE TABLE IF NOT EXISTS support_resolution_identifiers (
    id               SERIAL PRIMARY KEY,
    resolution_id    INTEGER NOT NULL,
    identifier_type  TEXT    NOT NULL,
    identifier_value TEXT    NOT NULL,
    created_at       TEXT    NOT NULL,
    FOREIGN KEY (resolution_id) REFERENCES support_ticket_resolutions(id) ON DELETE CASCADE
);

-- support_hypothesis_outcomes
CREATE TABLE IF NOT EXISTS support_hypothesis_outcomes (
    id              SERIAL PRIMARY KEY,
    resolution_id   INTEGER NOT NULL,
    hypothesis_code TEXT    NOT NULL,
    outcome         TEXT    NOT NULL,
    explanation     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (resolution_id) REFERENCES support_ticket_resolutions(id) ON DELETE CASCADE
);

-- support_regression_cases
CREATE TABLE IF NOT EXISTS support_regression_cases (
    id                     SERIAL PRIMARY KEY,
    resolution_id          INTEGER NOT NULL,
    case_code              TEXT    NOT NULL,
    title                  TEXT    NOT NULL,
    scenario               TEXT    NOT NULL,
    preconditions_json     TEXT    NOT NULL DEFAULT '{}',
    input_json             TEXT    NOT NULL DEFAULT '{}',
    expected_behavior_json TEXT    NOT NULL DEFAULT '{}',
    failure_signature_json TEXT    NOT NULL DEFAULT '{}',
    verification_json      TEXT    NOT NULL DEFAULT '{}',
    automation_status      TEXT    NOT NULL DEFAULT 'candidate',
    created_at             TEXT    NOT NULL,
    updated_at             TEXT    NOT NULL,
    FOREIGN KEY (resolution_id) REFERENCES support_ticket_resolutions(id) ON DELETE CASCADE
);

-- support_feedback_items
CREATE TABLE IF NOT EXISTS support_feedback_items (
    id                    SERIAL PRIMARY KEY,
    resolution_id         INTEGER NOT NULL,
    feedback_type         TEXT    NOT NULL,
    gap_code              TEXT    NOT NULL,
    title                 TEXT    NOT NULL,
    summary               TEXT    NOT NULL,
    evidence_json         TEXT    NOT NULL DEFAULT '[]',
    affected_sources_json TEXT    NOT NULL DEFAULT '[]',
    proposed_change_json  TEXT    NOT NULL DEFAULT '{}',
    priority              TEXT    NOT NULL DEFAULT 'medium',
    status                TEXT    NOT NULL DEFAULT 'needs_review',
    owner                 TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    reviewed_at           TEXT,
    reviewed_by           TEXT,
    review_notes          TEXT,
    FOREIGN KEY (resolution_id) REFERENCES support_ticket_resolutions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON support_feedback_items(feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON support_feedback_items(status);

-- support_generated_drafts
CREATE TABLE IF NOT EXISTS support_generated_drafts (
    id                    SERIAL PRIMARY KEY,
    ticket_id             INTEGER,
    analysis_id           INTEGER,
    resolution_id         INTEGER,
    feedback_id           INTEGER,

    draft_type            TEXT    NOT NULL,
    audience              TEXT    NOT NULL DEFAULT 'internal',
    tone                  TEXT    NOT NULL DEFAULT 'professional',

    subject               TEXT,
    body                  TEXT    NOT NULL DEFAULT '',

    grounding_package_json TEXT   NOT NULL DEFAULT '{}',
    used_fact_codes_json  TEXT    NOT NULL DEFAULT '[]',
    used_source_urls_json TEXT    NOT NULL DEFAULT '[]',
    claim_map_json        TEXT    NOT NULL DEFAULT '[]',

    provider              TEXT    NOT NULL DEFAULT '',
    model                 TEXT    NOT NULL DEFAULT '',
    prompt_version        TEXT    NOT NULL DEFAULT '',
    grounding_package_version TEXT NOT NULL DEFAULT '1.0.0',

    validation_status     TEXT    NOT NULL DEFAULT '',
    validation_errors_json TEXT   NOT NULL DEFAULT '[]',
    validation_warnings_json TEXT  NOT NULL DEFAULT '[]',
    unsupported_claims_json TEXT   NOT NULL DEFAULT '[]',

    status                TEXT    NOT NULL DEFAULT 'generated',

    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    reviewed_at           TEXT,
    reviewed_by           TEXT,
    review_notes          TEXT,

    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE SET NULL,
    FOREIGN KEY (analysis_id) REFERENCES support_ticket_analyses(id) ON DELETE SET NULL,
    FOREIGN KEY (resolution_id) REFERENCES support_ticket_resolutions(id) ON DELETE SET NULL,
    FOREIGN KEY (feedback_id) REFERENCES support_feedback_items(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_ticket ON support_generated_drafts(ticket_id);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON support_generated_drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_validation ON support_generated_drafts(validation_status);

COMMIT;