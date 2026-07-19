#!/usr/bin/env python3
"""CLI for running the search evaluation suite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate search quality against golden test cases.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/metronome_docs.db"),
        help="Path to the SQLite database (default: data/metronome_docs.db)",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("data/evaluation/search_cases.json"),
        help="Path to evaluation cases JSON (default: data/evaluation/search_cases.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of search results per case (default: 10)",
    )
    parser.add_argument(
        "--threshold-top1",
        type=float,
        default=85.0,
        help="Minimum acceptable Top-1 accuracy %% (default: 85.0)",
    )
    parser.add_argument(
        "--threshold-top3",
        type=float,
        default=95.0,
        help="Minimum acceptable Top-3 recall %% (default: 95.0)",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    database_path = project_root / args.database
    cases_path = project_root / args.cases

    if not database_path.exists():
        print(f"Error: database not found: {database_path}", file=sys.stderr)
        sys.exit(1)
    if not cases_path.exists():
        print(f"Error: cases file not found: {cases_path}", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, str(project_root))
    from src.documentation.search_evaluator import evaluate_search

    result = evaluate_search(
        database_path=database_path,
        cases_path=cases_path,
        limit=args.limit,
    )

    print()
    print("Documentation search evaluation")
    print()
    print(f"Cases: {result.total_cases}")
    print(f"Top-1 accuracy: {result.top1_accuracy:.1f}%")
    print(f"Top-3 recall: {result.top3_recall:.1f}%")
    print(f"Mean reciprocal rank: {result.mean_reciprocal_rank:.3f}")
    print(f"No-result cases: {result.no_result_cases}")

    if result.failed_cases:
        print()
        for fail in result.failed_cases:
            print(f"FAILED: {fail.query}")
            print(f"  Expected: {', '.join(fail.expected_pages[:3])}")
            print(f"  Actual rank: {fail.actual_rank or 'not found'}")
            print(f"  Top result: {fail.top_result or '(none)'}")
            print()

    # Exit code based on thresholds
    failed = False
    if result.top1_accuracy < args.threshold_top1:
        print(f"Top-1 accuracy {result.top1_accuracy:.1f}% below threshold {args.threshold_top1}%")
        failed = True
    if result.top3_recall < args.threshold_top3:
        print(f"Top-3 recall {result.top3_recall:.1f}% below threshold {args.threshold_top3}%")
        failed = True
    if result.no_result_cases > 0:
        print(f"No-result cases: {result.no_result_cases} (threshold: 0)")
        failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()