"""Load and validate the documentation index JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from .metadata import validate_url
from .models import DocumentationEntry, DocumentationIndex


class IndexLoadError(Exception):
    """Fatal error loading the documentation index."""


def _entry_from_dict(data: dict, index: int) -> DocumentationEntry:
    """Build a :class:`DocumentationEntry` from a dict, raising on invalid data."""
    title = (data.get("title") or "").strip()
    url = (data.get("url") or "").strip()

    if not title:
        raise IndexLoadError(f"Entry at index {index} has an empty title.")
    if not url:
        raise IndexLoadError(f"Entry at index {index} has an empty URL.")
    if not validate_url(url):
        raise IndexLoadError(
            f"Entry at index {index} has an invalid URL: {url}"
        )

    return DocumentationEntry(
        title=title,
        url=url,
        description=(data.get("description") or "").strip(),
        document_type=data.get("document_type", ""),
        category=data.get("category"),
        subcategory=data.get("subcategory"),
        slug=data.get("slug", ""),
        file_name=data.get("file_name", ""),
        source_line_number=data.get("source_line_number", 0),
        raw_line=data.get("raw_line", ""),
    )


def load_documentation_index(path: Path) -> DocumentationIndex:
    """Read and validate the parsed documentation index at *path*.

    Raises :class:`IndexLoadError` on fatal errors such as missing file,
    invalid JSON, or missing/malformed ``entries`` list.
    """
    if not path.exists():
        raise IndexLoadError(f"Index file not found: {path}")
    if not path.is_file():
        raise IndexLoadError(f"Index path is not a file: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IndexLoadError(f"Cannot read index file {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IndexLoadError(f"Invalid JSON in index file {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise IndexLoadError(f"Index file {path} does not contain a JSON object.")

    entries_raw = data.get("entries")
    if entries_raw is None:
        raise IndexLoadError(f"Index file {path} is missing the 'entries' key.")
    if not isinstance(entries_raw, list):
        raise IndexLoadError(f"The 'entries' key in {path} is not a list.")

    source_file = data.get("source_file", str(path))
    parsed_at = data.get("parsed_at", "")

    entries: list[DocumentationEntry] = []
    skipped = 0
    for idx, item in enumerate(entries_raw):
        if not isinstance(item, dict):
            skipped += 1
            continue
        try:
            entries.append(_entry_from_dict(item, idx))
        except IndexLoadError:
            skipped += 1

    if skipped:
        import sys
        print(
            f"Warning: {skipped} invalid entry(s) skipped while loading {path}",
            file=sys.stderr,
        )

    return DocumentationIndex(
        source_file=source_file,
        parsed_at=parsed_at,
        entries=entries,
    )