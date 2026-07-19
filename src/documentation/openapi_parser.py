"""Lightweight OpenAPI block detection and endpoint metadata extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Simple patterns for detecting OpenAPI content
_OPENAPI_SIGNALS = [
    r"^openapi\s*:",
    r"^paths\s*:",
    r"^components\s*:",
    r"^\s*operationId\s*:",
    r"^\s*requestBody\s*:",
    r"^\s*responses\s*:",
]
_OPENAPI_SIGNAL_RE = re.compile("|".join(_OPENAPI_SIGNALS), re.MULTILINE)

# Fence metadata: e.g. "/openapi.json post /v1/alerts/create"
_FENCE_META_RE = re.compile(
    r"(\S+)\s+(get|post|put|patch|delete|head|options)\s+(\S+)",
    re.IGNORECASE,
)

# Extract operationId from YAML/JSON
_OPERATION_ID_RE = re.compile(r"operationId\s*:\s*(\S+)")

# Extract response codes
_RESPONSE_CODE_RE = re.compile(r"""^\s*(\d{3}|'?\d{3}'?|"?'?\d{3}"?'?):""", re.MULTILINE)

# Extract field names from requestBody / properties
_REQUEST_FIELD_RE = re.compile(r"^\s+(\w+)\s*:", re.MULTILINE)

# Extract required fields block
_REQUIRED_RE = re.compile(r"required\s*:\s*\n((?:\s+-\s+\w+\n?)+)", re.MULTILINE)


@dataclass
class OpenApiMetadata:
    detected: bool = False
    http_method: str | None = None
    endpoint_path: str | None = None
    operation_id: str | None = None
    request_fields: list[dict] = field(default_factory=list)
    response_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _looks_like_openapi(content: str) -> bool:
    """Return True if *content* contains OpenAPI-like signals."""
    return bool(_OPENAPI_SIGNAL_RE.search(content))


def _extract_http_method(fence_metadata: str | None) -> str | None:
    if not fence_metadata:
        return None
    m = _FENCE_META_RE.search(fence_metadata)
    return m.group(2).upper() if m else None


def _extract_endpoint_path(fence_metadata: str | None) -> str | None:
    if not fence_metadata:
        return None
    m = _FENCE_META_RE.search(fence_metadata)
    return m.group(3) if m else None


def _extract_operation_id(content: str) -> str | None:
    m = _OPERATION_ID_RE.search(content)
    return m.group(1) if m else None


def _extract_response_codes(content: str) -> list[str]:
    codes: list[str] = []
    for m in _RESPONSE_CODE_RE.finditer(content):
        code = m.group(1).strip("'\"")
        if code not in codes:
            codes.append(code)
    return codes


def _extract_required_fields(content: str) -> list[str]:
    fields: list[str] = []
    for m in _REQUIRED_RE.finditer(content):
        block = m.group(1)
        for line in block.strip().splitlines():
            field = line.lstrip("- ").strip()
            if field and field not in fields:
                fields.append(field)
    return fields


def detect_openapi(
    fence_metadata: str | None,
    content: str,
    language: str | None,
) -> OpenApiMetadata:
    """Analyze a code block for OpenAPI metadata.

    Uses both fence metadata (``yaml /openapi.json POST /v1/endpoint``)
    and content signals (``openapi:``, ``paths:``, etc.).
    """
    is_likely = _looks_like_openapi(content)
    if not is_likely:
        return OpenApiMetadata(detected=False)

    warnings: list[str] = []
    http_method = _extract_http_method(fence_metadata)
    endpoint_path = _extract_endpoint_path(fence_metadata)
    operation_id = _extract_operation_id(content)
    response_codes = _extract_response_codes(content)

    # Try to extract request fields from requestBody properties
    required_set = set(_extract_required_fields(content))
    request_fields: list[dict] = []

    # Very basic: find a properties block inside requestBody or schema
    try:
        _find_request_fields(content, required_set, request_fields)
    except Exception:
        warnings.append("Failed to parse request field descriptions.")

    return OpenApiMetadata(
        detected=True,
        http_method=http_method,
        endpoint_path=endpoint_path,
        operation_id=operation_id,
        request_fields=request_fields,
        response_codes=response_codes,
        warnings=warnings,
    )


def _find_request_fields(
    content: str,
    required_set: set[str],
    out: list[dict],
) -> None:
    """Walk a simplified YAML-like structure to find field names
    under ``requestBody`` → ``properties``.
    """
    lines = content.splitlines()
    in_properties = False
    base_indent = -1

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        if re.match(r"^\s*properties\s*:", line):
            in_properties = True
            base_indent = indent
            continue

        if in_properties:
            if indent <= base_indent and stripped:
                # Moved out of properties block
                break

            # Look for a field name line: e.g. "  customer_id:"
            field_match = re.match(r"^\s+(\w+)\s*:", line)
            if field_match:
                name = field_match.group(1)
                out.append(
                    {
                        "name": name,
                        "required": name in required_set,
                    }
                )