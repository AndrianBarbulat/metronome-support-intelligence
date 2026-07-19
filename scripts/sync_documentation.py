#!/usr/bin/env python3
"""CLI entry-point for synchronizing documentation articles into SQLite."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Metronome documentation into a local SQLite database.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("data/parsed/documentation_index.json"),
        help="Path to the parsed documentation index JSON (default: data/parsed/documentation_index.json)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/metronome_docs.db"),
        help="Path to the SQLite database (default: data/metronome_docs.db)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum concurrent downloads (default: 5)",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    index_path = project_root / args.index
    database_path = project_root / args.database

    # Validate input
    if not index_path.exists():
        print(f"Error: index file not found: {index_path}", file=sys.stderr)
        sys.exit(1)
    if not index_path.is_file():
        print(f"Error: index path is not a file: {index_path}", file=sys.stderr)
        sys.exit(1)

    # Ensure parent directory exists for the database
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # Import project modules
    sys.path.insert(0, str(project_root))
    from src.documentation.synchronizer import synchronize_documentation  # noqa: E402

    try:
        summary = asyncio.run(
            synchronize_documentation(
                index_path=index_path,
                database_path=database_path,
                concurrency=args.concurrency,
            )
        )
    except Exception as exc:
        print(f"Fatal error during synchronization: {exc}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Metronome documentation synchronization completed")
    print()
    print(f"Index:")
    print(f"  {index_path}")
    print()
    print(f"Database:")
    print(f"  {database_path}")
    print()
    print(f"Discovered articles: {summary.discovered_count}")
    print(f"Fetched successfully: {summary.fetched_count}")
    print(f"New articles: {summary.new_count}")
    print(f"Changed articles: {summary.changed_count}")
    print(f"Unchanged articles: {summary.unchanged_count}")
    print(f"Missing from index: {summary.missing_count}")
    print(f"Failed downloads: {summary.failed_count}")


if __name__ == "__main__":
    main()