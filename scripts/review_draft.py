#!/usr/bin/env python3
"""Approve or reject a generated draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.drafting.service import review_generated_draft

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a generated draft.")
    parser.add_argument("--draft-id", type=int, required=True, help="Draft ID to review.")
    parser.add_argument(
        "--decision",
        required=True,
        choices=["approve", "reject", "mark_used"],
        help="Review decision.",
    )
    parser.add_argument("--reviewer", required=True, help="Name of the reviewer.")
    parser.add_argument("--notes", help="Optional review notes.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    try:
        draft = review_generated_draft(
            draft_id=args.draft_id,
            decision=args.decision,
            reviewer=args.reviewer,
            notes=args.notes,
            database_path=DB_PATH,
        )
        print(f"Draft {draft.id} status updated to '{draft.status}' by {args.reviewer}.")
        print(f"Current validation: {draft.validation_status}")
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()