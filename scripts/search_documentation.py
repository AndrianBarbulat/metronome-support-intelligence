#!/usr/bin/env python3
"""CLI entry-point for searching processed documentation chunks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search Metronome documentation articles locally.",
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query string.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/metronome_docs.db"),
        help="Path to the SQLite database (default: data/metronome_docs.db)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter results by category (e.g., alerts, contracts).",
    )
    parser.add_argument(
        "--document-type",
        type=str,
        default=None,
        help="Filter results by document_type (e.g., api_reference, guide).",
    )
    parser.add_argument(
        "--http-method",
        type=str,
        default=None,
        help="Filter results by HTTP method (e.g., POST, GET).",
    )
    parser.add_argument(
        "--endpoint-path",
        type=str,
        default=None,
        help="Filter results by endpoint path (e.g., /v1/contracts/create).",
    )
    parser.add_argument(
        "--chunk-type",
        type=str,
        default=None,
        help="Filter results by chunk type (e.g., code_example, request).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of results (default: 10).",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Show ranking reasons and matched tokens.",
    )
    parser.add_argument(
        "--include-multiple-chunks",
        action="store_true",
        help="Allow multiple chunks from the same page in results.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    database_path = project_root / args.database

    if not database_path.exists():
        print(f"Error: database not found: {database_path}", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, str(project_root))
    from src.documentation.search import search_documentation

    results = search_documentation(
        database_path=database_path,
        query=args.query,
        limit=args.limit,
        category=args.category,
        document_type=args.document_type,
        include_multiple_chunks_per_page=args.include_multiple_chunks,
    )

    # Client-side filters (post-rerank)
    if args.http_method:
        results = [r for r in results if r.http_method and r.http_method.upper() == args.http_method.upper()]
    if args.endpoint_path:
        results = [r for r in results if r.endpoint_path and args.endpoint_path in r.endpoint_path]
    if args.chunk_type:
        results = [r for r in results if r.chunk_type == args.chunk_type]
    results = results[: args.limit]

    print(f"\nSearch: {args.query}")
    print(f"Results: {len(results)}\n")

    for i, r in enumerate(results, 1):
        print(f"{i}. {r.page_title}")
        if r.heading:
            print(f"   Heading: {r.heading}")
        print(f"   Type: {r.document_type}")
        if r.category:
            print(f"   Category: {r.category}")
        if r.http_method and r.endpoint_path:
            print(f"   Endpoint: {r.http_method} {r.endpoint_path}")
        if args.explain:
            print(f"   Score: {r.final_score:.2f} (FTS: {r.base_fts_score:.2f})")
            if r.ranking_reasons:
                print(f"   Reasons: {' | '.join(r.ranking_reasons)}")
            if r.matched_terms:
                print(f"   Matched terms: {', '.join(r.matched_terms[:6])}")
            if r.matched_technical_tokens:
                print(f"   Technical tokens: {', '.join(r.matched_technical_tokens)}")
        print()
        excerpt = r.content_excerpt.replace("<b>", "").replace("</b>", "")
        print(f"   {excerpt[:200].strip()}")
        print()
        print(f"   Source:")
        print(f"   {r.source_url}")
        print()


if __name__ == "__main__":
    main()