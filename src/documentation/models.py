"""Data models for parsed documentation entries."""

from dataclasses import dataclass, field


@dataclass
class DocumentationEntry:
    title: str
    url: str
    description: str
    document_type: str
    category: str | None
    subcategory: str | None
    slug: str
    file_name: str
    source_line_number: int
    raw_line: str


@dataclass
class ParseError:
    line_number: int
    raw_line: str
    reason: str


@dataclass
class ParseResult:
    entries: list[DocumentationEntry] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    duplicate_count: int = 0
    ignored_count: int = 0


# ---------------------------------------------------------------------------
# Phase 2 — Sync models
# ---------------------------------------------------------------------------


@dataclass
class DocumentationIndex:
    """Represents a parsed and loaded documentation index."""
    source_file: str
    parsed_at: str
    entries: list[DocumentationEntry]


@dataclass
class DownloadResult:
    """Result of downloading a single documentation article."""
    url: str
    success: bool
    raw_markdown: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class SyncSummary:
    """Aggregated counts from a documentation sync run."""
    discovered_count: int = 0
    fetched_count: int = 0
    new_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    missing_count: int = 0
