"""Deterministic reranking layer for documentation search results."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.documentation.query_analyzer import AnalyzedQuery

# Weight configuration
WEIGHTS = {
    "fts_base": 2.0,
    "exact_title": 10.0,
    "title_phrase": 7.0,
    "exact_heading": 6.0,
    "technical_token": 5.0,
    "endpoint": 12.0,
    "http_method": 3.0,
    "operation_id": 12.0,
    "category": 3.0,
    "document_type": 2.0,
    "field_density": 2.0,
    "incidental_penalty": -3.0,
}


@dataclass
class SearchResult:
    """A single documentation search result with ranking metadata."""

    page_title: str
    heading: str | None
    heading_path: list[str]
    source_url: str
    document_type: str
    category: str | None
    http_method: str | None
    endpoint_path: str | None
    chunk_type: str
    content_excerpt: str
    content: str
    base_fts_score: float = 0.0
    final_score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    matched_technical_tokens: list[str] = field(default_factory=list)
    ranking_reasons: list[str] = field(default_factory=list)
    chunk_id: int = 0
    page_id: int = 0
    score: float = 0.0  # backwards compat


def _normalize_fts_score(score: float, max_score: float) -> float:
    """Normalize FTS rank to 0–1."""
    if max_score <= 0:
        return 0.0
    return max(0.0, min(1.0, score / max_score))


def _phrase_match_in_text(text: str, phrase: str) -> bool:
    """Case-insensitive phrase match."""
    return phrase.lower() in text.lower()


def _token_in_text(text: str, token: str) -> bool:
    """Case-insensitive exact word-boundary match."""
    import re

    return bool(re.search(rf"\b{re.escape(token)}\b", text, re.IGNORECASE))


def ranked_search(
    candidates: list[dict],
    analyzed: AnalyzedQuery,
    limit: int = 10,
    include_multiple_chunks_per_page: bool = False,
) -> list[SearchResult]:
    """Rerank *candidates* using deterministic signals from *analyzed*.

    Returns one result per page by default, deduplicated to the strongest chunk.
    """
    if not candidates:
        return []

    # Normalize FTS scores
    max_fts = max((c.get("score", 0) or 0) for c in candidates) or 1.0

    results: list[SearchResult] = []

    for c in candidates:
        meta = c.get("metadata_json", "{}")
        if isinstance(meta, str):
            meta = json.loads(meta)
        heading = c.get("heading", "")
        heading_path_raw = c.get("heading_path", "[]")
        if isinstance(heading_path_raw, list):
            heading_path = heading_path_raw
        else:
            heading_path = json.loads(heading_path_raw)
        content = c.get("content", "")
        page_title = meta.get("page_title", "")
        source_url = meta.get("source_url", "")
        document_type = meta.get("document_type", "")
        category = meta.get("category")
        http_method = meta.get("http_method")
        endpoint_path = meta.get("endpoint_path")

        base_fts = c.get("score", 0) or 0
        norm_fts = _normalize_fts_score(base_fts, max_fts)
        reasons: list[str] = []
        matched_terms: list[str] = []
        matched_tech: list[str] = []
        total = norm_fts * WEIGHTS["fts_base"]

        # Exact title match
        exact_title_score = 0.0
        if page_title and page_title.lower() == analyzed.normalized_query:
            exact_title_score = 1.0
            total += WEIGHTS["exact_title"]
            reasons.append("Exact article-title match")

        # Title phrase match
        title_phrase_score = 0.0
        for phrase in analyzed.phrases:
            if phrase and _phrase_match_in_text(page_title, phrase):
                title_phrase_score = 1.0
                total += WEIGHTS["title_phrase"]
                reasons.append(f"Title contains '{phrase}'")
                break
        if title_phrase_score == 0.0:
            # Check if all meaningful query terms appear in title (order-independent)
            if analyzed.terms:
                title_lower = page_title.lower()
                match_count = sum(1 for t in analyzed.terms if t in title_lower)
                if match_count >= len(analyzed.terms) * 0.6 and match_count >= 2:
                    title_phrase_score = 0.8
                    total += WEIGHTS["title_phrase"] * 0.8
                    reasons.append("Title phrase (partial) match")

        # Exact heading match
        exact_heading_score = 0.0
        if heading and heading.lower() == analyzed.normalized_query:
            exact_heading_score = 1.0
            total += WEIGHTS["exact_heading"]
            reasons.append("Exact heading match")

        # Technical token matching
        tech_score = 0.0
        for token in analyzed.technical_tokens:
            if _token_in_text(content, token) or _token_in_text(heading, token) or _token_in_text(page_title, token):
                tech_score += 1.0
                matched_tech.append(token)
        if tech_score > 0 and analyzed.technical_tokens:
            coverage = tech_score / len(analyzed.technical_tokens)
            total += WEIGHTS["technical_token"] * coverage
            reasons.append(f"Technical tokens matched: {', '.join(matched_tech)}")

        # Plain terms matched
        for term in analyzed.terms:
            if _token_in_text(content, term) or _token_in_text(heading, term) or _token_in_text(page_title, term):
                matched_terms.append(term)

        # Endpoint path match
        endpoint_score = 0.0
        for ep in analyzed.endpoint_paths:
            if endpoint_path and (ep == endpoint_path or endpoint_path.endswith(ep)):
                endpoint_score = 1.0
                total += WEIGHTS["endpoint"]
                reasons.append(f"Endpoint match: {endpoint_path}")
                break

        # HTTP method match
        http_method_score = 0.0
        if http_method and any(m == http_method.upper() for m in analyzed.http_methods):
            http_method_score = 1.0
            total += WEIGHTS["http_method"]
            reasons.append(f"HTTP method match: {http_method}")

        # Operation ID match
        op_id_score = 0.0
        op_id_from_meta = meta.get("operation_id", "")
        for op in analyzed.probable_operations:
            if op_id_from_meta and _token_in_text(op_id_from_meta, op):
                op_id_score = 1.0
                total += WEIGHTS["operation_id"]
                reasons.append(f"Operation ID match: {op_id_from_meta}")
                break

        # Category match
        cat_score = 0.0
        for cat in analyzed.probable_categories:
            if category and cat.replace("-", "_").lower() == category.lower().replace("-", "_"):
                cat_score = 1.0
                total += WEIGHTS["category"]
                reasons.append(f"Category match: {category}")
                break

        # Document type boost — API reference for operational queries
        doc_type_score = 0.0
        if document_type == "api_reference" and _query_looks_operational(analyzed):
            doc_type_score = 1.0
            total += WEIGHTS["document_type"]
            reasons.append("API-reference authority boost")

        # Field density: number of distinct tech tokens in content
        field_density = 0.0
        if analyzed.technical_tokens:
            present = sum(1 for t in analyzed.technical_tokens if _token_in_text(content, t))
            field_density = present / len(analyzed.technical_tokens)
            total += WEIGHTS["field_density"] * field_density

        # Incidental match penalty: isolated weak match
        if norm_fts < 0.1 and tech_score == 0 and exact_title_score == 0 and title_phrase_score == 0:
            total += WEIGHTS["incidental_penalty"]

        results.append(
            SearchResult(
                page_title=page_title,
                heading=heading,
                heading_path=heading_path,
                source_url=source_url,
                document_type=document_type,
                category=category,
                http_method=http_method,
                endpoint_path=endpoint_path,
                chunk_type=c.get("chunk_type", "prose"),
                content_excerpt=c.get("content_excerpt", "") or "",
                content=content or "",
                base_fts_score=base_fts,
                final_score=total,
                matched_terms=matched_terms,
                matched_technical_tokens=matched_tech,
                ranking_reasons=reasons,
                chunk_id=c.get("id", 0),
                page_id=meta.get("id", 0),
                score=total,
            )
        )

    # Sort by final score descending
    results.sort(key=lambda r: r.final_score, reverse=True)

    # Page-level deduplication: one result per page (strongest chunk)
    if not include_multiple_chunks_per_page:
        seen_urls: set[str] = set()
        deduped: list[SearchResult] = []
        for r in results:
            if r.source_url not in seen_urls:
                seen_urls.add(r.source_url)
                deduped.append(r)
        results = deduped

    return results[:limit]


def _query_looks_operational(analyzed: AnalyzedQuery) -> bool:
    """Heuristic: does the query look like an API operation request?"""
    if analyzed.http_methods or analyzed.endpoint_paths or analyzed.probable_operations:
        return True
    if analyzed.technical_tokens and analyzed.probable_operations:
        return True
    has_verb = any(op in analyzed.probable_operations for op in ["create", "get", "update", "archive"])
    has_tech = len(analyzed.technical_tokens) >= 1
    return has_verb and has_tech