#!/usr/bin/env python3
"""List resolution feedback proposals."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="List feedback proposals.")
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    parser.add_argument("--type", dest="feedback_type")
    parser.add_argument("--status")
    parser.add_argument("--priority")
    parser.add_argument("--gap-code")
    parser.add_argument("--owner")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.database.repository import DocumentationRepository

    db_path = args.database if args.database.is_absolute() else project_root / args.database
    repo = DocumentationRepository(db_path)
    try:
        repo.initialize_schema()
        rows = repo.list_feedback_items(
            feedback_type=args.feedback_type,
            status=args.status,
            priority=args.priority,
            gap_code=args.gap_code,
            owner=args.owner,
        )
    finally:
        repo.close()

    if not rows:
        print("No feedback proposals found.")
        return

    for row in rows:
        print(
            f"{row['id']}: [{row['status']}] {row['gap_code']} "
            f"({row['feedback_type']}, {row['priority']}) - {row['title']}"
        )


if __name__ == "__main__":
    main()
