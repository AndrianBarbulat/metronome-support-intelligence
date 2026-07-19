#!/usr/bin/env python3
"""Apply a human review decision to a feedback proposal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a feedback proposal.")
    parser.add_argument("--feedback-id", type=int, required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes")
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.feedback.review_service import FeedbackReviewError, review_feedback_item

    db_path = args.database if args.database.is_absolute() else project_root / args.database
    try:
        item = review_feedback_item(
            feedback_id=args.feedback_id,
            decision=args.decision,
            reviewer=args.reviewer,
            notes=args.notes,
            database_path=db_path,
        )
    except FeedbackReviewError as exc:
        print(f"Review failed: {exc}")
        sys.exit(1)

    print(f"Feedback {item.id} is now {item.status}.")


if __name__ == "__main__":
    main()
