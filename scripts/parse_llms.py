#!/usr/bin/env python3
"""CLI entry-point for parsing the Metronome ``llms.txt`` documentation index."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Metronome llms.txt into structured JSON and CSV.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/llms.txt"),
        help="Path to llms.txt (default: data/llms.txt)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/parsed/documentation_index.json"),
        help="Path for JSON output (default: data/parsed/documentation_index.json)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/parsed/documentation_index.csv"),
        help="Path for CSV output (default: data/parsed/documentation_index.csv)",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Skip CSV generation.",
    )
    args = parser.parse_args()

    # Resolve relative to the project root (two dirs up from this script).
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    input_path = project_root / args.input
    output_path = project_root / args.output
    csv_path = project_root / args.csv

    # Validate input
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not input_path.is_file():
        print(f"Error: input path is not a file: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Import parser modules (add project root to path so src is findable).
    sys.path.insert(0, str(project_root))
    from src.documentation.llms_parser import parse_llms_file  # noqa: E402

    result = parse_llms_file(input_path)

    # Build serialisable output
    entries_data = []
    for e in result.entries:
        entries_data.append(
            {
                "title": e.title,
                "url": e.url,
                "description": e.description,
                "document_type": e.document_type,
                "category": e.category,
                "subcategory": e.subcategory,
                "slug": e.slug,
                "file_name": e.file_name,
                "source_line_number": e.source_line_number,
                "raw_line": e.raw_line,
            }
        )

    output_doc = {
        "source_file": str(args.input),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(result.entries),
        "duplicate_count": result.duplicate_count,
        "ignored_count": result.ignored_count,
        "error_count": len(result.errors),
        "entries": entries_data,
        "errors": [
            {"line_number": e.line_number, "raw_line": e.raw_line, "reason": e.reason}
            for e in result.errors
        ],
    }

    # Write JSON
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"Error: cannot write JSON output: {exc}", file=sys.stderr)
        sys.exit(1)

    # Write CSV
    if not args.no_csv:
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", encoding="utf-8", newline="") as cf:
                writer = csv.writer(cf)
                writer.writerow(
                    [
                        "title",
                        "url",
                        "description",
                        "document_type",
                        "category",
                        "subcategory",
                        "slug",
                        "file_name",
                        "source_line_number",
                    ]
                )
                for e in result.entries:
                    writer.writerow(
                        [
                            e.title,
                            e.url,
                            e.description,
                            e.document_type,
                            e.category,
                            e.subcategory,
                            e.slug,
                            e.file_name,
                            e.source_line_number,
                        ]
                    )
        except OSError as exc:
            print(f"Error: cannot write CSV output: {exc}", file=sys.stderr)
            sys.exit(1)

    # Summary
    print("Metronome documentation index parsed")
    print()
    print(f"Source: {args.input}")
    print(f"Valid articles: {len(result.entries)}")
    print(f"Duplicate URLs: {result.duplicate_count}")
    print(f"Ignored lines: {result.ignored_count}")
    print(f"Parse errors: {len(result.errors)}")
    print()
    print(f"JSON output:")
    print(f"  {output_path}")
    if not args.no_csv:
        print(f"CSV output:")
        print(f"  {csv_path}")


if __name__ == "__main__":
    main()