"""Parser for the Metronome ``llms.txt`` documentation index."""

from __future__ import annotations

import re
from pathlib import Path

from .metadata import derive_metadata, validate_url
from .models import DocumentationEntry, ParseError, ParseResult

# Matches a Markdown list entry with a link and optional description.
#   - [Title](URL): Optional description
# Group 1: title     (inside the brackets)
# Group 2: url       (inside the parentheses)
# Group 3: description (after ``): `` — optional)
_LINE_PATTERN = re.compile(r"^- \[(.+?)]\((.+?)\)(?::\s+(.*))?$")


def _looks_like_doc_entry(line: str) -> bool:
    """Return True if *line* starts like a documentation list entry."""
    return line.startswith("- [") and "](" in line


def _parse_line(line: str, line_number: int) -> DocumentationEntry | ParseError | None:
    """Attempt to parse a single line into a :class:`DocumentationEntry`,
    :class:`ParseError`, or ``None`` (skip).
    """
    stripped = line.strip()
    if not stripped:
        return None  # blank line → skip

    # Only process lines that look like ``- [Title](URL)...``
    if not _looks_like_doc_entry(stripped):
        return None  # heading, prose, non-doc link → silently ignored

    match = _LINE_PATTERN.match(stripped)
    if not match:
        return ParseError(
            line_number=line_number,
            raw_line=line,
            reason="Malformed documentation entry — could not parse title/URL structure.",
        )

    title = match.group(1).strip()
    url = match.group(2).strip()
    description = (match.group(3) or "").strip()

    if not validate_url(url):
        return ParseError(
            line_number=line_number,
            raw_line=line,
            reason="URL is not a valid Metronome documentation article link.",
        )

    meta = derive_metadata(url)

    return DocumentationEntry(
        title=title,
        url=url,
        description=description,
        document_type=meta["document_type"],
        category=meta["category"],
        subcategory=meta["subcategory"],
        slug=meta["slug"],
        file_name=meta["file_name"],
        source_line_number=line_number,
        raw_line=line,
    )


def parse_llms_file(file_path: Path) -> ParseResult:
    """Read *file_path* and return a :class:`ParseResult` with all parsed
    entries, errors, and counts.
    """
    result = ParseResult()
    seen_urls: dict[str, int] = {}  # normalized url → first line number
    with file_path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            parsed = _parse_line(line, line_number)

            if parsed is None:
                # Count non-blank, non-doc-entry lines as ignored (headings, prose, etc.)
                if line.strip():
                    result.ignored_count += 1
                continue

            if isinstance(parsed, ParseError):
                result.errors.append(parsed)
                continue

            # It's a DocumentationEntry
            norm_url = parsed.url.strip().lower()
            if norm_url in seen_urls:
                result.duplicate_count += 1
                continue

            seen_urls[norm_url] = parsed.source_line_number
            result.entries.append(parsed)
    return result