"""Tests for the llms.txt parser."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so that src.documentation is importable.
# (This assumes tests are run from the project root, e.g. via ``pytest``.)
from src.documentation.llms_parser import parse_llms_file
from src.documentation.metadata import derive_metadata, validate_url


# ---------------------------------------------------------------------------
# Helper: write a temporary llms.txt file and parse it
# ---------------------------------------------------------------------------
def _parse_text(content: str) -> tuple:
    """Write *content* to a temp file, parse, and return the ParseResult."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        path = Path(f.name)

    try:
        result = parse_llms_file(path)
    finally:
        path.unlink()
    return result


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------
class TestValidateUrl:
    def test_valid_api_reference(self):
        assert validate_url(
            "https://docs.metronome.com/api-reference/alerts/create-a-threshold-notification.md"
        )

    def test_valid_guide(self):
        assert validate_url(
            "https://docs.metronome.com/guides/get-started/home.md"
        )

    def test_not_https(self):
        assert not validate_url(
            "http://docs.metronome.com/api-reference/alerts/create-a-threshold-notification.md"
        )

    def test_wrong_host(self):
        assert not validate_url(
            "https://example.com/article.md"
        )

    def test_not_markdown(self):
        assert not validate_url(
            "https://docs.metronome.com/api-reference/alerts"
        )

    def test_homepage(self):
        assert not validate_url("https://docs.metronome.com/")

    def test_mailto(self):
        assert not validate_url("mailto:test@example.com")

    def test_empty(self):
        assert not validate_url("")


# ---------------------------------------------------------------------------
# Metadata derivation
# ---------------------------------------------------------------------------
class TestDeriveMetadata:
    def test_api_reference_two_segments(self):
        meta = derive_metadata(
            "https://docs.metronome.com/api-reference/authentication.md"
        )
        assert meta["document_type"] == "api_reference"
        assert meta["category"] is None
        assert meta["subcategory"] is None
        assert meta["slug"] == "authentication"
        assert meta["file_name"] == "authentication.md"

    def test_api_reference_three_segments(self):
        meta = derive_metadata(
            "https://docs.metronome.com/api-reference/alerts/create-a-threshold-notification.md"
        )
        assert meta["document_type"] == "api_reference"
        assert meta["category"] == "alerts"
        assert meta["subcategory"] is None
        assert meta["slug"] == "create-a-threshold-notification"
        assert meta["file_name"] == "create-a-threshold-notification.md"

    def test_api_reference_four_segments(self):
        meta = derive_metadata(
            "https://docs.metronome.com/api-reference/contracts/get-contracts/get-a-contract.md"
        )
        assert meta["document_type"] == "api_reference"
        assert meta["category"] == "contracts"
        assert meta["subcategory"] == "get-contracts"
        assert meta["slug"] == "get-a-contract"
        assert meta["file_name"] == "get-a-contract.md"

    def test_guide_url(self):
        meta = derive_metadata(
            "https://docs.metronome.com/guides/implement-metronome/core-concepts/send-usage-events.md"
        )
        assert meta["document_type"] == "guide"
        assert meta["category"] == "implement-metronome"
        assert meta["subcategory"] == "core-concepts"
        assert meta["slug"] == "send-usage-events"
        assert meta["file_name"] == "send-usage-events.md"

    def test_integrations_url(self):
        meta = derive_metadata(
            "https://docs.metronome.com/integrations/platform-integrations/segment.md"
        )
        assert meta["document_type"] == "guide"
        assert meta["category"] == "platform-integrations"
        assert meta["subcategory"] is None
        assert meta["slug"] == "segment"
        assert meta["file_name"] == "segment.md"


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------
class TestParseLlmsFile:
    def test_valid_entry_with_description(self):
        content = (
            "- [Create a threshold notification](https://docs.metronome.com/api-reference/alerts/create-a-threshold-notification.md): "
            "Create a new threshold notification to monitor customer spending.\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert e.title == "Create a threshold notification"
        assert "customer spending" in e.description
        assert e.document_type == "api_reference"
        assert e.category == "alerts"
        assert e.source_line_number == 1

    def test_valid_entry_without_description(self):
        content = "- [API Authentication](https://docs.metronome.com/api-reference/authentication.md)\n"
        result = _parse_text(content)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert e.title == "API Authentication"
        assert e.description == ""

    def test_description_containing_colons(self):
        content = (
            "- [Example](https://docs.metronome.com/api-reference/example.md): "
            "Behaviour: this value has additional meaning.\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert e.description == "Behaviour: this value has additional meaning."

    def test_api_reference_url(self):
        content = "- [Test](https://docs.metronome.com/api-reference/alerts/test.md): desc\n"
        result = _parse_text(content)
        assert len(result.entries) == 1
        assert result.entries[0].document_type == "api_reference"
        assert result.entries[0].category == "alerts"

    def test_guide_url(self):
        content = "- [Test](https://docs.metronome.com/guides/get-started/home.md): desc\n"
        result = _parse_text(content)
        assert len(result.entries) == 1
        assert result.entries[0].document_type == "guide"

    def test_nested_url_with_subcategory(self):
        content = (
            "- [Get a contract](https://docs.metronome.com/api-reference/contracts/get-contracts/get-a-contract.md): desc\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert e.category == "contracts"
        assert e.subcategory == "get-contracts"
        assert e.slug == "get-a-contract"

    def test_duplicate_urls(self):
        content = (
            "- [First](https://docs.metronome.com/api-reference/alerts/test.md): desc\n"
            "- [Second](https://docs.metronome.com/api-reference/alerts/test.md): desc 2\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 1
        assert result.duplicate_count == 1

    def test_malformed_markdown_entry(self):
        content = "- Not a link but looks like entry\n"
        result = _parse_text(content)
        # This line starts with "- ["? No, it starts with "- Not" — so it's ignored.
        assert len(result.entries) == 0
        assert len(result.errors) == 0

    def test_malformed_with_brackets_but_no_parens(self):
        content = "- [No URL here just brackets]\n"
        result = _parse_text(content)
        # _looks_like_doc_entry requires "](" — this has no parens, so ignored.
        assert len(result.entries) == 0
        assert len(result.errors) == 0

    def test_malformed_with_brackets_and_parens_but_no_match(self):
        content = "- [Broken](no-valid-url-pattern): desc\n"
        result = _parse_text(content)
        # The regex does match (no spaces), but the URL fails validation.
        assert len(result.entries) == 0
        assert len(result.errors) == 1
        assert "not a valid Metronome" in result.errors[0].reason

    def test_url_from_another_domain(self):
        content = (
            "- [External](https://example.com/article.md): desc\n"
            "- [Valid](https://docs.metronome.com/api-reference/alerts/test.md): valid desc\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 1
        assert result.entries[0].title == "Valid"
        assert len(result.errors) == 1
        assert "not a valid Metronome" in result.errors[0].reason

    def test_metronome_url_not_md(self):
        content = "- [No .md](https://docs.metronome.com/api-reference/alerts): desc\n"
        result = _parse_text(content)
        assert len(result.entries) == 0
        assert len(result.errors) == 1
        assert "not a valid Metronome" in result.errors[0].reason

    def test_blank_lines_and_headings(self):
        content = (
            "# Heading\n"
            "\n"
            "- [Valid](https://docs.metronome.com/api-reference/test.md): ok\n"
            "Some prose here\n"
            "\n"
            "## Another heading\n"
            "\n"
            "- [Also valid](https://docs.metronome.com/api-reference/alerts/alert.md): yep\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 2
        # Blank lines are ignored (counted as ignore since they are non-blank? No — blank lines have
        # no stripped content, so they are not counted. Headings and prose are non-blank and non-doc,
        # so they are counted as ignored.)
        assert result.ignored_count >= 3  # heading + prose + another heading

    def test_unicode_and_apostrophes(self):
        content = (
            "- [Café résumé](https://docs.metronome.com/api-reference/test.md): "
            "L'avis d'un élève — 100€\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert "Café résumé" in e.title
        assert "L'avis d'un élève" in e.description
        assert "100€" in e.description

    def test_correct_source_line_numbers(self):
        content = (
            "# Heading\n"
            "\n"
            "- [First](https://docs.metronome.com/api-reference/first.md): first\n"
            "\n"
            "- [Second](https://docs.metronome.com/api-reference/second.md): second\n"
            "\n"
            "  some indented prose\n"
            "- [Third](https://docs.metronome.com/api-reference/third.md): third\n"
        )
        result = _parse_text(content)
        assert len(result.entries) == 3
        line_numbers = [e.source_line_number for e in result.entries]
        assert line_numbers == [3, 5, 8]

    def test_correct_json_serialization(self):
        content = (
            "- [A](https://docs.metronome.com/api-reference/test.md): desc\n"
        )
        result = _parse_text(content)
        entry = result.entries[0]
        data = {
            "title": entry.title,
            "url": entry.url,
            "description": entry.description,
            "document_type": entry.document_type,
            "category": entry.category,
            "subcategory": entry.subcategory,
            "slug": entry.slug,
            "file_name": entry.file_name,
            "source_line_number": entry.source_line_number,
            "raw_line": entry.raw_line,
        }
        json_str = json.dumps(data, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["title"] == "A"
        assert parsed["url"] == "https://docs.metronome.com/api-reference/test.md"
        assert parsed["slug"] == "test"

    def test_description_with_long_text(self):
        desc = (
            "This is a very long description " * 20
        ).strip()
        content = f"- [Long](https://docs.metronome.com/api-reference/long.md): {desc}\n"
        result = _parse_text(content)
        assert len(result.entries) == 1
        assert result.entries[0].description == desc

    def test_openapi_json_ignored(self):
        """The llms.txt has entries for openapi.json — these are not .md and should be errors."""
        content = "- [openapi](https://docs.metronome.com/openapi.json)\n"
        result = _parse_text(content)
        assert len(result.entries) == 0
        assert len(result.errors) == 1

    def test_openapi_plans_json_ignored(self):
        content = "- [openapi.plans](https://docs.metronome.com/openapi.plans.json)\n"
        result = _parse_text(content)
        assert len(result.entries) == 0
        assert len(result.errors) == 1

    def test_non_docs_metronome_links_ignored(self):
        content = (
            "- [Status](https://status.metronome.com/)\n"
            "- [Blog](https://metronome.com/blog)\n"
        )
        result = _parse_text(content)
        # These start with "- [" but the host is wrong → errors.
        assert len(result.entries) == 0
        assert len(result.errors) == 2