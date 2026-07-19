"""Secret and sensitive-data sanitization for support tickets."""

from __future__ import annotations

import copy
import re

from .models import SanitizationResult, SupportTicketInput

SENSITIVE_HEADER_KEYS = {
    "authorization", "proxy-authorization", "x-api-key", "api-key",
    "cookie", "set-cookie", "x-auth-token", "webhook-secret",
}

_BEARER_RE = re.compile(r"bearer\s+[^\s]+", re.IGNORECASE)
_JWT_RE = re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")
_API_KEY_RE = re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*\S+", re.IGNORECASE)
_SK_KEY_RE = re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9_\-]+\b")
_LONG_HEX_RE = re.compile(r"\b[a-f0-9]{40,}\b", re.IGNORECASE)
_CONN_STRING_PWD_RE = re.compile(r"(?:password|pwd)\s*=\s*\S+", re.IGNORECASE)

_EMAIL_RE = re.compile(r"\b[\w.-]+@[\w.-]+\.\w+\b")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def sanitize_ticket(
    ticket: SupportTicketInput,
    strict: bool = False,
) -> SanitizationResult:
    """Sanitize *ticket* in-place (deep copy) and return a result with counts.

    Default mode preserves UUIDs, emails, and IPs.
    *strict* mode additionally redacts emails, IPs, and UUIDs.
    """
    redacted_fields: list[str] = []
    redaction_count = 0
    warnings: list[str] = []

    sanitized = copy.deepcopy(ticket)

    # 1. Redact sensitive headers
    if sanitized.request_headers:
        for key in list(sanitized.request_headers.keys()):
            if key.lower() in SENSITIVE_HEADER_KEYS:
                sanitized.request_headers[key] = "[REDACTED]"
                redacted_fields.append(f"request_header.{key}")
                redaction_count += 1

    if sanitized.response_headers:
        for key in list(sanitized.response_headers.keys()):
            if key.lower() in SENSITIVE_HEADER_KEYS:
                sanitized.response_headers[key] = "[REDACTED]"
                redacted_fields.append(f"response_header.{key}")
                redaction_count += 1

    # 2. Redact secrets in text fields
    text_fields = {
        "customer_message": sanitized.customer_message,
        "logs": sanitized.logs or "",
        "subject": sanitized.subject,
    }
    if sanitized.expected_behavior:
        text_fields["expected_behavior"] = sanitized.expected_behavior
    if sanitized.actual_behavior:
        text_fields["actual_behavior"] = sanitized.actual_behavior

    for field_name, text in text_fields.items():
        new_text, count = _redact_secrets_in_text(text, strict)
        if count > 0:
            redaction_count += count
            redacted_fields.append(f"text.{field_name}")
            if field_name == "customer_message":
                sanitized.customer_message = new_text
            elif field_name == "logs":
                sanitized.logs = new_text
            elif field_name == "subject":
                sanitized.subject = new_text
            elif field_name == "expected_behavior":
                sanitized.expected_behavior = new_text
            elif field_name == "actual_behavior":
                sanitized.actual_behavior = new_text

    # 3. Redact secrets in request/response bodies
    for body_attr, label in [
        ("request_body", "request_body"),
        ("response_body", "response_body"),
    ]:
        body = getattr(sanitized, body_attr, None)
        if isinstance(body, dict):
            new_body, bcount = _redact_body_dict(body, strict)
            if bcount > 0:
                redaction_count += bcount
                redacted_fields.append(label)
                setattr(sanitized, body_attr, new_body)
        elif isinstance(body, str):
            new_body, bcount = _redact_secrets_in_text(body, strict)
            if bcount > 0:
                redaction_count += bcount
                redacted_fields.append(label)
                setattr(sanitized, body_attr, new_body)

    return SanitizationResult(
        sanitized_ticket=sanitized,
        redaction_count=redaction_count,
        redacted_fields=redacted_fields,
        warnings=warnings,
    )


def _redact_secrets_in_text(text: str, strict: bool) -> tuple[str, int]:
    count = 0
    result = text

    for pat, label in [
        (_BEARER_RE, "bearer_token"),
        (_JWT_RE, "jwt"),
        (_API_KEY_RE, "api_key"),
        (_SK_KEY_RE, "secret_key"),
        (_LONG_HEX_RE, "long_hex"),
        (_CONN_STRING_PWD_RE, "connection_string_password"),
    ]:
        matches = pat.findall(result)
        if matches:
            count += len(matches)
            result = pat.sub("[REDACTED]", result)

    if strict:
        for pat, label in [
            (_EMAIL_RE, "email"),
            (_IP_RE, "ip_address"),
            (_UUID_RE, "uuid"),
        ]:
            matches = pat.findall(result)
            if matches:
                count += len(matches)
                result = pat.sub("[REDACTED]", result)

    return result, count


def _redact_body_dict(
    body: dict, strict: bool
) -> tuple[dict, int]:
    count = 0
    result = copy.deepcopy(body)

    # Redact values under sensitive-sounding keys
    for key in list(result.keys()):
        if any(sk in key.lower() for sk in ["password", "secret", "token", "api_key", "apikey"]):
            result[key] = "[REDACTED]"
            count += 1
        elif isinstance(result[key], str):
            new_val, c = _redact_secrets_in_text(str(result[key]), strict)
            if c > 0:
                result[key] = new_val
                count += c

    return result, count
