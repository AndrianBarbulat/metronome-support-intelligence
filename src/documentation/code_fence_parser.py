"""Extract and parse fenced code blocks from Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches a fenced code block opening: ≥3 backticks, optional language + metadata
_FENCE_OPEN_RE = re.compile(r"^(```+)\s*(.*)$")


@dataclass
class CodeBlock:
    """A single fenced code block extracted from Markdown."""
    language: str | None
    fence_metadata: str | None
    content: str
    start_line: int
    end_line: int


def _extract_fence_info(info_str: str) -> tuple[str | None, str | None]:
    """Parse ``info_str`` (e.g. ``yaml /openapi.json post /v1/alerts/create``)
    into ``(language, fence_metadata)``.
    """
    if not info_str.strip():
        return (None, None)
    parts = info_str.split(maxsplit=1)
    language = parts[0] if parts else None
    metadata = parts[1] if len(parts) > 1 else None
    return (language, metadata)


def extract_code_blocks(lines: list[str]) -> list[CodeBlock]:
    """Walk *lines* (1-indexed) and return every fenced code block found.

    Handles:

    * 3+ backticks
    * matching closing fence length
    * custom info strings (language + metadata)
    """
    blocks: list[CodeBlock] = []
    in_fence = False
    fence_char = ""   # The exact backtick sequence used to open
    fence_info = ""
    fence_language: str | None = None
    fence_metadata: str | None = None
    fence_content: list[str] = []
    fence_start = 0

    for i, line in enumerate(lines, start=1):
        if in_fence:
            # Look for closing fence
            close_match = _FENCE_OPEN_RE.match(line)
            if close_match and close_match.group(1) == fence_char:
                # Closing fence
                blocks.append(
                    CodeBlock(
                        language=fence_language,
                        fence_metadata=fence_metadata,
                        content="".join(fence_content),
                        start_line=fence_start,
                        end_line=i,
                    )
                )
                in_fence = False
                fence_content = []
            else:
                fence_content.append(line)
        else:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                fence_char = m.group(1)  # e.g. "```" or "````"
                fence_info = m.group(2)
                fence_language, fence_metadata = _extract_fence_info(fence_info)
                in_fence = True
                fence_start = i
                fence_content = []

    # Unclosed fence at end-of-file — capture what we have
    if in_fence and fence_content:
        blocks.append(
            CodeBlock(
                language=fence_language,
                fence_metadata=fence_metadata,
                content="".join(fence_content),
                start_line=fence_start,
                end_line=len(lines),
            )
        )

    return blocks