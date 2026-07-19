"""Split parsed documentation articles into searchable chunks."""

from __future__ import annotations

from dataclasses import dataclass, field

from .hashing import calculate_content_hash
from .markdown_parser import ParsedDocumentationArticle, MarkdownSection
from .openapi_parser import OpenApiMetadata


PREFERRED_MAX = 4000
HARD_MAX = 8000
MIN_USEFUL = 100


@dataclass
class ChunkMetadata:
    page_title: str = ""
    source_url: str = ""
    document_type: str = ""
    category: str | None = None
    subcategory: str | None = None
    heading_level: int | None = None
    heading_path: list[str] = field(default_factory=list)
    http_method: str | None = None
    endpoint_path: str | None = None
    operation_id: str | None = None
    contains_code: bool = False
    contains_table: bool = False


@dataclass
class Chunk:
    chunk_type: str
    heading: str | None
    heading_path: list[str]
    content: str   # raw Markdown
    content_hash: str
    token_estimate: int
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)


def _infer_chunk_type(section: MarkdownSection, has_code: bool, has_table: bool) -> str:
    """Return a chunk-type string based on heading and content signals."""
    h = (section.heading or "").lower()
    hp = " ".join(section.heading_path).lower() if section.heading_path else ""

    if any(kw in h for kw in ("request", "body", "payload", "path parameter", "query parameter")):
        if has_code:
            return "code_example"
        return "request"
    if any(kw in h for kw in ("response", "returns", "status code")):
        return "response"
    if any(kw in h for kw in ("field", "property", "parameter")):
        return "request_field"
    if any(kw in h for kw in ("authentication", "auth", "api key", "bearer", "token")):
        return "authentication"
    if any(kw in h for kw in ("example", "sample", "usage", "quickstart")):
        return "code_example"
    if any(kw in h for kw in ("warning", "note", "important", "caution", "deprecated")):
        return "warning"
    if has_table:
        return "table"
    if "openapi" in h or "api reference" in hp:
        return "openapi"
    if h and not has_code:
        return "prose"
    return "prose"


def _can_attach_content(last: str, addition: str) -> bool:
    return (len(last) + len(addition)) <= PREFERRED_MAX


def _split_paragraphs(content: str) -> list[str]:
    """Split content on blank lines into paragraph blocks."""
    blocks = content.split("\n\n")
    result: list[str] = []
    for b in blocks:
        trimmed = b.strip()
        if trimmed:
            result.append(trimmed + "\n\n")
    return result


def create_chunks(
    parsed: ParsedDocumentationArticle,
    page_title: str = "",
    source_url: str = "",
    document_type: str = "",
    category: str | None = None,
    subcategory: str | None = None,
) -> list[Chunk]:
    """Convert a parsed article into a list of searchable :class:`Chunk` objects."""
    chunks: list[Chunk] = []

    for section in parsed.sections:
        section_text = section.content.strip()
        if not section_text:
            continue  # skip empty sections

        # Determine if this section contains code fences or tables
        has_code = False
        has_table = False
        section_start = section.start_line
        section_end = section.end_line

        for cb in parsed.code_blocks:
            if cb.start_line >= section_start and cb.end_line <= section_end:
                has_code = True
                break
        for tbl in parsed.tables:
            if tbl["start_line"] >= section_start and tbl["end_line"] <= section_end:
                has_table = True
                break

        chunk_type = _infer_chunk_type(section, has_code, has_table)

        # Find closest OpenAPI metadata for endpoint context
        best_openapi: OpenApiMetadata | None = None
        for oa in parsed.openapi_blocks:
            # crude match: see if any code block from this OA is in section range
            for cb in parsed.code_blocks:
                if cb.start_line >= section_start and (oa.http_method or oa.endpoint_path):
                    best_openapi = oa
                    break

        meta = ChunkMetadata(
            page_title=page_title,
            source_url=source_url,
            document_type=document_type,
            category=category,
            subcategory=subcategory,
            heading_level=section.heading_level,
            heading_path=section.heading_path,
            http_method=best_openapi.http_method if best_openapi else None,
            endpoint_path=best_openapi.endpoint_path if best_openapi else None,
            operation_id=best_openapi.operation_id if best_openapi else None,
            contains_code=has_code,
            contains_table=has_table,
        )

        if len(section_text) <= PREFERRED_MAX:
            # Whole section fits in one chunk
            content = section.content  # preserve original
            h = calculate_content_hash(content)
            chunks.append(
                Chunk(
                    chunk_type=chunk_type,
                    heading=section.heading,
                    heading_path=section.heading_path,
                    content=content,
                    content_hash=h,
                    token_estimate=max(1, len(content) // 4),
                    metadata=meta,
                )
            )
        else:
            # Split into paragraph blocks, keeping code fences intact
            paragraphs = _split_paragraphs(section_text)
            buffer_parts: list[str] = []
            buffer_len = 0

            for para in paragraphs:
                plen = len(para)
                if buffer_parts and not _can_attach_content(
                    "\n\n".join(buffer_parts), "\n\n" + para
                ):
                    _emit_chunk(
                        chunks, buffer_parts, chunk_type, section, meta,
                    )
                    buffer_parts = []
                    buffer_len = 0

                buffer_parts.append(para)
                buffer_len += plen

            if buffer_parts:
                _emit_chunk(
                    chunks, buffer_parts, chunk_type, section, meta,
                )

    return chunks


def _emit_chunk(
    chunks: list[Chunk],
    buffer_parts: list[str],
    chunk_type: str,
    section: MarkdownSection,
    meta: ChunkMetadata,
) -> None:
    content = "\n\n".join(buffer_parts)
    if len(content.strip()) < MIN_USEFUL:
        return
    h = calculate_content_hash(content)
    chunks.append(
        Chunk(
            chunk_type=chunk_type,
            heading=section.heading,
            heading_path=section.heading_path,
            content=content,
            content_hash=h,
            token_estimate=max(1, len(content) // 4),
            metadata=meta,
        )
    )