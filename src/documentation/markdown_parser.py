"""Parse raw Markdown into structured sections, respecting code fences and tables."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .code_fence_parser import CodeBlock, extract_code_blocks
from .openapi_parser import OpenApiMetadata, detect_openapi


# Matches an ATX heading line
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# Matches a Markdown table separator row: |---|...|
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*-{3,}\s*\|.*\|\s*$")


@dataclass
class MarkdownSection:
    heading: str | None
    heading_level: int | None
    heading_path: list[str]           # breadcrumb trail
    content: str                      # raw Markdown of this section
    start_line: int
    end_line: int


@dataclass
class ParsedDocumentationArticle:
    title: str
    sections: list[MarkdownSection] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    openapi_blocks: list[OpenApiMetadata] = field(default_factory=list)


def _find_table_ranges(lines: list[str], fence_line_nums: set[int]) -> list[tuple[int, int]]:
    """Return (start, end) inclusive line-number pairs for Markdown tables,
    skipping any line inside a code fence.
    """
    tables: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        line_num = i + 1
        if line_num in fence_line_nums:
            i += 1
            continue
        # Look for a table: line above is blank or start-of-doc, current line has |...|, next line is separator
        if _TABLE_SEP_RE.match(lines[i]) and i > 0:
            # Backtrack to find the header row
            header_idx = i - 1
            while header_idx >= 0 and (header_idx + 1) in fence_line_nums:
                header_idx -= 1
            if header_idx >= 0 and "|" in lines[header_idx] and (header_idx + 1) not in fence_line_nums:
                start = header_idx + 1
                end = i + 1
                # Find end of table
                j = i + 1
                while j < len(lines) and "|" in lines[j] and (j + 1) not in fence_line_nums:
                    end = j + 1
                    j += 1
                tables.append((start, end))
                i = j
                continue
        i += 1
    return tables


def parse_markdown(raw: str, article_title: str = "") -> ParsedDocumentationArticle:
    """Parse *raw* Markdown into a :class:`ParsedDocumentationArticle`.

    Sections are delineated by ATX headings. Code fences and tables
    are never split across section boundaries.
    """
    lines = raw.splitlines(keepends=True)
    if not lines:
        return ParsedDocumentationArticle(title=article_title)

    # 1. Extract code blocks
    code_blocks = extract_code_blocks(lines)

    # Build set of line-numbers that belong to a fence interior
    fence_interior: set[int] = set()
    for cb in code_blocks:
        for ln in range(cb.start_line + 1, cb.end_line):
            fence_interior.add(ln)

    # 2. Find table ranges
    table_ranges = _find_table_ranges(lines, fence_interior)
    table_line_nums: set[int] = set()
    for s, e in table_ranges:
        for ln in range(s, e + 1):
            table_line_nums.add(ln)

    # 3. Build sections by scanning for headings
    sections: list[MarkdownSection] = []
    heading_stack: list[tuple[str, int]] = []  # (heading_text, level)

    # Find all heading positions
    heading_positions: list[tuple[int, int, str]] = []  # (line_num, level, text)
    for i, line in enumerate(lines):
        ln = i + 1
        if ln in fence_interior:
            continue
        m = _HEADING_RE.match(line)
        if m:
            heading_positions.append((ln, len(m.group(1)), m.group(2).strip()))

    if not heading_positions:
        # Entire document is one section
        full_text = "".join(lines)
        sections.append(
            MarkdownSection(
                heading=None,
                heading_level=None,
                heading_path=[],
                content=full_text,
                start_line=1,
                end_line=len(lines),
            )
        )
    else:
        # Sections between headings
        for idx, (hl_line, hl_level, hl_text) in enumerate(heading_positions):
            # Update heading path
            # Remove deeper or equal headings
            while heading_stack and heading_stack[-1][1] >= hl_level:
                heading_stack.pop()
            heading_stack.append((hl_text, hl_level))
            heading_path = [h[0] for h in heading_stack]

            # Content from just after heading to end or next heading
            content_start = hl_line + 1
            if idx + 1 < len(heading_positions):
                content_end = heading_positions[idx + 1][0] - 1
            else:
                content_end = len(lines)

            section_lines = lines[content_start - 1 : content_end]
            content = "".join(section_lines)

            sections.append(
                MarkdownSection(
                    heading=hl_text,
                    heading_level=hl_level,
                    heading_path=heading_path,
                    content=content,
                    start_line=hl_line,
                    end_line=content_end,
                )
            )

    # 4. Build table dicts
    tables: list[dict] = []
    for ts, te in table_ranges:
        table_lines = lines[ts - 1 : te]
        tables.append(
            {
                "start_line": ts,
                "end_line": te,
                "raw_markdown": "".join(table_lines),
                "row_count": len(table_lines),
            }
        )

    # 5. Detect OpenAPI from code blocks
    openapi_blocks: list[OpenApiMetadata] = []
    for cb in code_blocks:
        result = detect_openapi(cb.fence_metadata, cb.content, cb.language)
        if result.detected:
            openapi_blocks.append(result)

    return ParsedDocumentationArticle(
        title=article_title,
        sections=sections,
        code_blocks=code_blocks,
        tables=tables,
        openapi_blocks=openapi_blocks,
    )