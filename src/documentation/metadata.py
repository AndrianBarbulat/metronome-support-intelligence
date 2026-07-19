"""URL metadata derivation for Metronome documentation articles."""

from __future__ import annotations

import re
from urllib.parse import urlparse

METRONOME_HOST = "docs.metronome.com"

DOCUMENT_TYPE_MAP: dict[str, str] = {
    "api-reference": "api_reference",
    "guides": "guide",
    "integrations": "guide",
}


def _normalize_doc_type(path_segment: str) -> str:
    """Map a URL-first-path-segment to a normalized document type."""
    return DOCUMENT_TYPE_MAP.get(path_segment, path_segment)


def _strip_md_suffix(filename: str) -> str:
    """Return the slug derived from a filename like 'create-a-thing.md'."""
    return filename.removesuffix(".md")


def validate_url(url: str) -> bool:
    """Return True if *url* is a valid Metronome documentation article URL.

    Valid URLs must:
      * use ``https``
      * belong to ``docs.metronome.com``
      * point to a path ending in ``.md``
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError):
        return False

    if parsed.scheme != "https":
        return False
    if parsed.hostname != METRONOME_HOST:
        return False
    if not parsed.path.endswith(".md"):
        return False
    return True


def derive_metadata(url: str) -> dict[str, str | None]:
    """Derive ``document_type``, ``category``, ``subcategory``, ``slug``, and
    ``file_name`` from a validated Metronome documentation URL.
    """
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")

    # Split into segments: e.g. ['api-reference','alerts','create-a-threshold-notification.md']
    segments = path.split("/")

    if not segments:
        return _empty_metadata()

    doc_type = _normalize_doc_type(segments[0])

    category: str | None = None
    subcategory: str | None = None
    slug: str = ""
    file_name: str = ""

    if len(segments) == 2:
        # e.g. api-reference/authentication.md
        category = None
        subcategory = None
        file_name = segments[1]
        slug = _strip_md_suffix(file_name)
    elif len(segments) == 3:
        # e.g. api-reference/alerts/create-a-threshold-notification.md
        category = segments[1]
        subcategory = None
        file_name = segments[2]
        slug = _strip_md_suffix(file_name)
    elif len(segments) >= 4:
        # e.g. api-reference/contracts/get-contracts/get-a-contract.md
        category = segments[1]
        subcategory = segments[2]
        file_name = segments[-1]
        slug = _strip_md_suffix(file_name)
    else:
        file_name = segments[-1]
        slug = _strip_md_suffix(file_name)

    return {
        "document_type": doc_type,
        "category": category,
        "subcategory": subcategory,
        "slug": slug,
        "file_name": file_name,
    }


def _empty_metadata() -> dict[str, str | None]:
    return {
        "document_type": "",
        "category": None,
        "subcategory": None,
        "slug": "",
        "file_name": "",
    }