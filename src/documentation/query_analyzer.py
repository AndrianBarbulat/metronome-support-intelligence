"""Query analysis — detect technical tokens, phrases, HTTP identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Snake-case identifiers: starting_at, billable_metric_id, uniqueness_key
_SNAKE_RE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")

# camelCase identifiers: createAlert, ingestEvents
_CAMEL_RE = re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b")

# kebab-case: create-alert
_KEBAB_RE = re.compile(r"\b[a-z]+(?:-[a-z0-9]+)+\b")

# HTTP methods
_HTTP_METHOD_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.IGNORECASE
)

# Status codes: three digits, optionally with leading quote
_STATUS_CODE_RE = re.compile(r"(?<![.\d])\b(\d{3})\b(?![.\d])")

# API paths: start with /, contain words or v1/v2, may have {}
_ENDPOINT_PATH_RE = re.compile(r"(/[a-zA-Z0-9_{}/-]+(?:/v\d+(?:/[a-zA-Z0-9_{}/-]+)?)?)")

# Quoted phrases: "exact match" or 'exact match'
_QUOTED_RE = re.compile(r"""["']([^"']+)["']""")

# Operation-ish tokens: verb-noun concatenated with -v suffix
_OP_ID_RE = re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]*)+(?:-v\d+)?\b")

_VERB_MAP: dict[str, str] = {
    "create": "create",
    "add": "create",
    "provision": "create",
    "retrieve": "get",
    "fetch": "get",
    "get": "get",
    "list": "list",
    "modify": "update",
    "edit": "update",
    "update": "update",
    "remove": "archive",
    "archive": "archive",
    "delete": "archive",
    "send": "ingest",
    "ingest": "ingest",
    "search": "search",
    "void": "void",
    "audit": "get",
    "audit logs": "get",
    "disable": "archive",
    "enable": "create",
}

_PROBABLE_CATEGORIES: set[str] = {
    "alerts", "billable-metrics", "billable_metrics", "contracts",
    "credits-and-commits", "credits_and_commits", "customers",
    "invoices", "notifications", "packages", "products",
    "rate-cards", "rate_cards", "usage", "security", "settings",
    "events", "pricing", "subscription", "integrations",
}


@dataclass
class AnalyzedQuery:
    original_query: str
    normalized_query: str
    terms: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    technical_tokens: list[str] = field(default_factory=list)
    status_codes: list[str] = field(default_factory=list)
    http_methods: list[str] = field(default_factory=list)
    endpoint_paths: list[str] = field(default_factory=list)
    probable_operations: list[str] = field(default_factory=list)
    probable_categories: list[str] = field(default_factory=list)


def analyze_query(raw: str) -> AnalyzedQuery:
    """Parse *raw* into an :class:`AnalyzedQuery` with extracted signals."""
    original = raw.strip()
    normalized = original.lower()

    # 1. Phrases (quoted)
    phrases = _QUOTED_RE.findall(original)

    # 2. Remove quoted parts for further analysis
    body = _QUOTED_RE.sub(" ", original)

    # 3. Technical tokens
    technical: list[str] = []
    for pat in (_SNAKE_RE, _CAMEL_RE, _KEBAB_RE):
        for m in pat.finditer(body):
            token = m.group(0)
            if token not in technical:
                technical.append(token)

    # 4. Status codes
    status_codes = list(dict.fromkeys(_STATUS_CODE_RE.findall(body)))

    # 5. HTTP methods
    http_methods = list(dict.fromkeys(m.upper() for m in _HTTP_METHOD_RE.findall(body)))

    # 6. Endpoint paths
    endpoint_paths = list(dict.fromkeys(_ENDPOINT_PATH_RE.findall(body)))

    # 7. Operation IDs
    probable_operations: list[str] = []
    for m in _OP_ID_RE.finditer(body):
        op = m.group(0)
        # Only capture if camelCase-ish
        if re.search(r"[A-Z]", op):
            probable_operations.append(op)

    # 8. Simple terms (remove technical tokens, keep meaningful words)
    cleaned = body.lower()
    for token in technical:
        cleaned = cleaned.replace(token.lower(), " ")
    cleaned = _HTTP_METHOD_RE.sub(" ", cleaned)
    simple_terms = [t for t in cleaned.split() if len(t) > 1]

    # 9. Probable categories
    probable_categories = list(
        dict.fromkeys(
            cat for cat in _PROBABLE_CATEGORIES if cat.replace("-", "_") in normalized
        )
    )

    # 10. Probable operation verbs
    ops: list[str] = []
    for verb, mapped in _VERB_MAP.items():
        if verb in simple_terms:
            ops.append(mapped)

    return AnalyzedQuery(
        original_query=original,
        normalized_query=normalized,
        terms=simple_terms,
        phrases=phrases,
        technical_tokens=technical,
        status_codes=status_codes,
        http_methods=http_methods,
        endpoint_paths=endpoint_paths,
        probable_operations=list(dict.fromkeys(ops)),
        probable_categories=probable_categories,
    )