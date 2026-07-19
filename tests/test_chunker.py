"""Tests for the documentation chunker."""

from src.documentation.chunker import Chunk, ChunkMetadata, create_chunks
from src.documentation.markdown_parser import parse_markdown


def test_small_section_one_chunk():
    raw = "# Overview\n\nThis is a short section.\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc", source_url="https://docs.metronome.com/test.md")
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "prose"
    assert chunks[0].heading == "Overview"
    assert chunks[0].heading_path == ["Overview"]
    assert "short section" in chunks[0].content


def test_large_section_splits():
    # Create distinct paragraphs separated by blank lines
    paras = "\n\n".join("Paragraph text here block " + str(i) + "." for i in range(200))
    raw = "# Long\n\n" + paras + "\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc")
    assert len(chunks) > 1  # Should split
    for ch in chunks:
        assert len(ch.content.strip()) >= 100  # Min useful


def test_never_split_code_block():
    raw = "# Code\n\n```python\n" + ("x = 1\n" * 200) + "```\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc")
    # The code block should be inside a single chunk
    found = False
    for ch in chunks:
        if "```python" in ch.content and "```" in ch.content:
            found = True
            assert ch.content.count("```python") == 1  # Only one opening
    assert found


def test_no_empty_chunks():
    # Sections with too little content should be filtered out
    raw = "# Header\n\n\n\n\n# Header 2\n\nContent\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc")
    # Sections with content < MIN_USEFUL are omitted — only non-empty sections remain
    for ch in chunks:
        assert len(ch.content.strip()) > 0
    # "Content" alone is too small; the first section is empty too
    # So chunks may be empty list
    assert all(ch.content.strip() for ch in chunks)


def test_chunk_heading_paths():
    raw = "# API\n\n## Request\n\n### Body\n\nSome content.\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc")
    # The deepest section's chunk should have the full path
    body_chunks = [c for c in chunks if c.heading == "Body"]
    assert len(body_chunks) >= 1
    assert body_chunks[0].heading_path == ["API", "Request", "Body"]


def test_chunk_metadata():
    raw = "# Overview\n\nSome text.\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(
        parsed,
        page_title="My Page",
        source_url="https://docs.metronome.com/test.md",
        document_type="api_reference",
        category="alerts",
    )
    assert len(chunks) == 1
    meta = chunks[0].metadata
    assert meta.page_title == "My Page"
    assert meta.source_url == "https://docs.metronome.com/test.md"
    assert meta.document_type == "api_reference"
    assert meta.category == "alerts"
    assert not meta.contains_code
    assert not meta.contains_table


def test_chunk_hash_deterministic():
    raw = "# Overview\n\nSame content.\n"
    parsed1 = parse_markdown(raw, "Doc")
    parsed2 = parse_markdown(raw, "Doc")
    chunks1 = create_chunks(parsed1)
    chunks2 = create_chunks(parsed2)
    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.content_hash == c2.content_hash


def test_request_field_chunk_type():
    raw = "# Update\n\n## Path parameter: customer_id\n\n" + ("The path parameter section describing a request field that is long enough to form a valid chunk with at least one hundred characters minimum. " * 2) + "\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc")
    # A section with "parameter" in heading gets "request" chunk type
    field_chunks = [c for c in chunks if c.heading and "customer_id" in c.heading]
    if field_chunks:
        assert field_chunks[0].chunk_type in ("request", "request_field")


def test_code_example_chunk_type():
    raw = "# API\n\n## Request\n\n```curl\ncurl -X POST https://api.example.com\n```\n"
    parsed = parse_markdown(raw, "Doc")
    chunks = create_chunks(parsed, page_title="Doc")
    request_chunks = [c for c in chunks if c.heading and c.heading == "Request"]
    if request_chunks:
        assert request_chunks[0].chunk_type == "code_example"