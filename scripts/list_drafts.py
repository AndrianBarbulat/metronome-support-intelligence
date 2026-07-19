#!/usr/bin/env python3
"""List generated drafts, optionally filtered by status or type."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database.repository import DocumentationRepository
from src.drafting.models import SUPPORTED_DRAFT_TYPES

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="List generated drafts.")
    parser.add_argument("--ticket-id", type=int, help="Filter by ticket ID.")
    parser.add_argument("--status", help="Filter by workflow status.")
    parser.add_argument("--validation-status", help="Filter by validation status.")
    parser.add_argument(
        "--type", dest="draft_type", choices=sorted(SUPPORTED_DRAFT_TYPES), help="Filter by draft type."
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    repo = DocumentationRepository(DB_PATH)
    repo.initialize_schema()
    try:
        rows = repo.list_generated_drafts(
            ticket_id=args.ticket_id,
            draft_type=args.draft_type,
            status=args.status,
            validation_status=args.validation_status,
        )

        if not rows:
            print("No drafts found.")
            return

        print(f"{'ID':>4}  {'Ticket':>6}  {'Type':<28}  {'Status':<18}  {'Valid':<8}  {'Provider':<8}  {'Created'}")
        print("-" * 110)
        for r in rows:
            print(
                f"{r['id']:>4}  "
                f"{r['ticket_id'] or '':>6}  "
                f"{r['draft_type']:<28}  "
                f"{r['status']:<18}  "
                f"{r['validation_status']:<8}  "
                f"{r['provider']:<8}  "
                f"{r['created_at'][:19]}"
            )

        print(f"\n{len(rows)} draft(s) found.")
    finally:
        repo.close()


if __name__ == "__main__":
    main()