#!/usr/bin/env python3
"""CLI entry-point for structured documentation processing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process current documentation articles into structured chunks.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/metronome_docs.db"),
        help="Path to the SQLite database (default: data/metronome_docs.db)",
    )
    parser.add_argument(
        "--parser-version",
        type=str,
        default="1.0.0",
        help="Parser version string (default: 1.0.0)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing of all articles.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    database_path = project_root / args.database

    if not database_path.exists():
        print(f"Error: database not found: {database_path}", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, str(project_root))
    from src.documentation.content_processor import (
        process_current_documentation,
    )

    summary = process_current_documentation(
        database_path=database_path,
        parser_version=args.parser_version,
        force=args.force,
    )

    print()
    print("Metronome documentation processing completed")
    print()
    print(f"Database:")
    print(f"  {database_path}")
    print()
    print(f"Active articles: {summary.discovered_count}")
    print(f"Processed articles: {summary.processed_count}")
    print(f"Skipped articles: {summary.skipped_count}")
    print(f"Failed articles: {summary.failed_count}")
    print()
    print(f"Sections created: {summary.sections_created}")
    print(f"Chunks created: {summary.chunks_created}")
    print(f"Code blocks detected: {summary.code_blocks_detected}")
    print(f"Tables detected: {summary.tables_detected}")
    print(f"OpenAPI blocks detected: {summary.openapi_blocks_detected}")
    print(f"Parser version: {args.parser_version}")


if __name__ == "__main__":
    main()