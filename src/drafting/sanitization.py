"""Sanitize drafting data to prevent secret leakage."""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns that indicate secrets or credentials
# ---------------------------------------------------------------------------
_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"Bearer\s+[\w\-\.]+", "Bearer token"),
    (r"sk_live_[a-zA-Z0-9]+", "Stripe live secret key"),
    (r"sk_test_[a-zA-Z0-9]+", "Stripe test key"),
    (r"Authorization:\s*.+", "Authorization header value"),
    (r"api[_-]?key[:=]\s*\S+", "API key assignment"),
    (r"password[:=]\s*\S+", "Password assignment"),
    (r"secret[:=]\s*\S+", "Secret assignment"),
    (r"token[:=]\s*\S+", "Token assignment"),
    (r"x-api-key:\s*.+", "x-api-key header"),
]


def contains_secrets(text: str) -> bool:
    """Return True if *text* contains any known secret patterns."""
    for pattern, _desc in _SECRET_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def find_secret_patterns(text: str) -> list[str]:
    """Return descriptions of any detected secret patterns."""
    found: list[str] = []
    for pattern, desc in _SECRET_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(desc)
    return found


def sanitize_for_display(data: dict[str, object], max_string_length: int = 200) -> dict[str, object]:
    """Return a copy of *data* safe for display (truncated, no secrets)."""
    result: dict[str, object] = {}
    for key, value in data.items():
        if _is_sensitive_key(key):
            result[key] = "***REDACTED***"
            continue
        if isinstance(value, str):
            if contains_secrets(value):
                result[key] = "***SECRET_REDACTED***"
            elif len(value) > max_string_length:
                result[key] = value[:max_string_length] + "..."
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = sanitize_for_display(value, max_string_length)
        elif isinstance(value, list):
            result[key] = [
                sanitize_for_display(v, max_string_length) if isinstance(v, dict) else _sanitize_scalar(v, max_string_length)
                for v in value
            ]
        else:
            result[key] = value
    return result


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    sensitive = {
        "api_key", "apikey", "password", "secret", "token",
        "authorization", "auth", "credential", "private_key",
    }
    return any(s in lower for s in sensitive)


def _sanitize_scalar(value: object, max_length: int) -> object:
    if isinstance(value, str):
        if contains_secrets(value):
            return "***SECRET_REDACTED***"
        if len(value) > max_length:
            return value[:max_length] + "..."
    return value