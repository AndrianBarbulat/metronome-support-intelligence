"""Hybrid search pipeline: FTS candidate retrieval + deterministic reranking."""

from __future__ import annotations

from pathlib import Path

from src.database.repository import DocumentationRepository
from src.documentation.query_analyzer import AnalyzedQuery, analyze_query
from src.documentation.reranker import SearchResult, ranked_search


def search_documentation(
    database_path: Path,
    query: str,
    limit: int = 10,
    category: str | None = None,
    document_type: str | None = None,
    include_multiple_chunks_per_page: bool = False,
) -> list[SearchResult]:
    """Search documentation with hybrid FTS + deterministic reranking."""

    analyzed = analyze_query(query)
    repo = DocumentationRepository(database_path)
    try:
        candidates: list[dict] = []
        seen_ids: set[int] = set()

        def _add(c_list: list[dict]) -> None:
            for c in c_list:
                cid = c.get("id", 0)
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append(c)

        # 1. FTS on the inner-joined token set
        safe_query = _build_safe_fts_query(analyzed)
        fts_results = repo.search_fts(safe_query, limit=max(limit * 5, 30),
                                      category=category, document_type=document_type)
        _add(fts_results)

        # 2. Exact title searches for extracted phrases
        for phrase in analyzed.phrases:
            _add(repo.search_exact_title(phrase, limit=5))

        # 3. Title phrase matches from all terms
        if analyzed.terms:
            phrase_guess = " ".join(analyzed.terms[:6])
            _add(repo.search_exact_title(phrase_guess, limit=5))

        # 4. Technical tokens
        for token in analyzed.technical_tokens:
            _add(repo.search_technical_token(token, limit=20))

        # 5. Endpoint paths
        for ep in analyzed.endpoint_paths:
            _add(repo.search_endpoint(ep, limit=10))

        # 6. Operation IDs
        for op_id in analyzed.probable_operations:
            _add(repo.search_operation_id(op_id, limit=10))

        # Rerank
        results = ranked_search(candidates, analyzed, limit=limit,
                                include_multiple_chunks_per_page=include_multiple_chunks_per_page)
        return results
    finally:
        repo.close()


def _build_safe_fts_query(analyzed: AnalyzedQuery) -> str:
    """Build an FTS-safe query string from analyzed components.

    Removes punctuation and reserved FTS characters, preserving
    technical tokens joined by AND.
    """
    parts: list[str] = []

    # Include all simple terms
    for term in analyzed.terms:
        safe = _sanitize_fts_term(term)
        if safe:
            parts.append(safe)

    # Include technical tokens
    for token in analyzed.technical_tokens:
        safe = _sanitize_fts_term(token)
        if safe and safe not in parts:
            parts.append(safe)

    if not parts:
        # Minimal query from original
        safe = _sanitize_fts_term(analyzed.original_query)
        if safe:
            parts.append(safe)

    if not parts:
        return "metronome"  # fallback

    # Join with AND for precision when we have enough tokens
    if len(parts) >= 2:
        return " AND ".join(parts)
    return parts[0]


def _sanitize_fts_term(term: str) -> str:
    """Remove characters unsafe for FTS5 MATCH expressions."""
    import re

    # Remove parentheses, quotes, colons, slashes, hyphens (keep alphanumeric + underscore)
    cleaned = re.sub(r'[()":/\-\'\[\]{}<>!@#$%^&*+=|\\;,.?~`]', " ", term)
    parts = [p for p in cleaned.split() if len(p) >= 2]
    return " ".join(parts)