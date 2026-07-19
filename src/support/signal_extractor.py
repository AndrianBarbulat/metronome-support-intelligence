"""Extract technical signals from support-ticket evidence."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import ExtractedTicketSignals, SupportTicketInput

_SNAKE_RE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
_ENDPOINT_PATH_RE = re.compile(r"(/[a-zA-Z0-9_{}/-]+(?:/v\d+(?:/[a-zA-Z0-9_{}/-]+)?)?)")
_HTTP_METHOD_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?\b")
_ID_RE = re.compile(r"\b[a-f0-9]{32}\b|\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b", re.IGNORECASE)

_AREA_MAP: dict[str, str] = {
    "/contracts/": "contracts",
    "/customers/": "customers",
    "/ingest": "usage",
    "/events": "usage",
    "/alerts/": "alerts",
    "/invoices/": "invoices",
    "/billable-metrics": "billable-metrics",
    "/rate-cards": "rate-cards",
    "/credits": "credits-and-commits",
    "/products": "products",
    "/packages": "packages",
}

_VERB_MAP: dict[str, str] = {
    "create": "create", "add": "create", "provision": "create",
    "get": "get", "retrieve": "get", "fetch": "get",
    "list": "list",
    "update": "update", "edit": "update", "modify": "update",
    "archive": "archive", "delete": "archive", "remove": "archive",
    "ingest": "ingest", "send": "ingest",
    "search": "search",
}

_ERROR_TERMS = {"error", "failed", "invalid", "missing", "duplicate",
                "rejected", "unauthorized", "forbidden", "not found",
                "timeout", "409", "400", "404", "500", "503"}


def _fields_from_body(body) -> list[str]:
    """Extract top-level field names from a dict or list."""
    if isinstance(body, dict):
        return [k for k in body if isinstance(k, str)]
    if isinstance(body, list) and len(body) > 0 and isinstance(body[0], dict):
        return list(body[0].keys())
    return []


def extract_signals(ticket: SupportTicketInput) -> ExtractedTicketSignals:
    # HTTP method: explicit field first
    http_method = None
    if ticket.http_method and _HTTP_METHOD_RE.fullmatch(ticket.http_method.strip()):
        http_method = ticket.http_method.strip().upper()

    # Endpoint path: explicit field first
    endpoint_path = ticket.endpoint_path
    if not endpoint_path:
        m = _ENDPOINT_PATH_RE.search(ticket.subject + " " + ticket.customer_message)
        if m:
            endpoint_path = m.group(0)

    # Status code
    status_code = ticket.response_status

    # Request / response fields
    request_fields = _fields_from_body(ticket.request_body)
    response_fields = _fields_from_body(ticket.response_body)

    # Technical tokens from body+logs
    all_text = " ".join([
        ticket.subject, ticket.customer_message,
        ticket.logs or "",
        ticket.expected_behavior or "",
        ticket.actual_behavior or "",
    ])
    technical_tokens = list(dict.fromkeys(
        t for t in _SNAKE_RE.findall(all_text)
    ))

    # Also add fields from structured bodies as technical tokens
    for f in request_fields + response_fields:
        if f not in technical_tokens and f.islower() and "_" in f:
            technical_tokens.append(f)

    # Error terms
    error_terms = list(dict.fromkeys(
        t for t in _ERROR_TERMS if t in all_text.lower()
    ))

    # Identifiers
    identifiers: dict[str, list[str]] = {}
    id_matches = _ID_RE.findall(all_text)
    if id_matches:
        identifiers["ids"] = id_matches[:5]

    # Timestamps
    timestamps = _TIMESTAMP_RE.findall(all_text)

    # Product area
    product_area = None
    if endpoint_path:
        for prefix, area in _AREA_MAP.items():
            if prefix in endpoint_path:
                product_area = area
                break

    # Probable operation
    probable_operation = None
    verb_text = all_text.lower()
    for verb, op in _VERB_MAP.items():
        if verb in verb_text.split():
            probable_operation = op
            break

    return ExtractedTicketSignals(
        product_area=product_area,
        probable_operation=probable_operation,
        http_method=http_method,
        endpoint_path=endpoint_path,
        status_code=status_code,
        request_fields=request_fields,
        response_fields=response_fields,
        technical_tokens=technical_tokens,
        error_terms=error_terms,
        identifiers=identifiers,
        timestamps=timestamps,
        expected_behavior=ticket.expected_behavior,
        actual_behavior=ticket.actual_behavior,
    )