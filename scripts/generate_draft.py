#!/usr/bin/env python3
"""Generate a grounded draft from an existing ticket, resolution, or feedback item."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.drafting.config import load_config  # loads .env before provider access
from src.drafting.service import generate_grounded_draft, review_generated_draft
from src.drafting.providers.mock import MockDraftingProvider
from src.drafting.models import SUPPORTED_DRAFT_TYPES

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a grounded draft using deterministic evidence + LLM drafting."
    )
    parser.add_argument("--ticket-id", type=int, help="Ticket ID from the database.")
    parser.add_argument("--analysis-id", type=int, help="Analysis ID (optional).")
    parser.add_argument("--resolution-id", type=int, help="Resolution ID (optional).")
    parser.add_argument("--feedback-id", type=int, help="Feedback item ID (optional).")
    parser.add_argument(
        "--type",
        dest="draft_type",
        required=True,
        choices=sorted(SUPPORTED_DRAFT_TYPES),
        help="Type of draft to generate.",
    )
    parser.add_argument("--provider", default=None, help="Override provider (mock or gemini).")
    parser.add_argument("--tone", default="professional", help="Tone of the draft.")
    parser.add_argument(
        "--show-grounding", action="store_true", help="Print the grounding package facts."
    )
    parser.add_argument(
        "--show-validation", action="store_true", help="Print validation details."
    )
    parser.add_argument("--output", type=Path, help="Write draft body to file.")
    parser.add_argument("--no-persist", action="store_true", help="Do NOT persist to database.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run scripts/sync_documentation.py first.")
        sys.exit(1)

    # Build provider
    provider = None
    if args.provider:
        if args.provider == "mock":
            provider = MockDraftingProvider(mode="valid")
        elif args.provider == "gemini":
            # Let default provider handle this
            pass
        else:
            print(f"Unknown provider: {args.provider}")
            sys.exit(1)

    generate_kwargs: dict = {
        "draft_type": args.draft_type,
        "database_path": DB_PATH,
        "ticket_id": args.ticket_id,
        "analysis_id": args.analysis_id,
        "resolution_id": args.resolution_id,
        "feedback_id": args.feedback_id,
        "tone": args.tone,
    }
    if args.provider:
        generate_kwargs["provider"] = provider

    try:
        draft = generate_grounded_draft(**generate_kwargs)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        sys.exit(1)

    # Print result
    print(f"Draft ID: {draft.id}")
    print(f"Type: {draft.draft_type}")
    print(f"Provider: {draft.provider} ({draft.model})")
    print(f"Status: {draft.status}")
    print(f"Validation: {draft.validation_status}")
    print(f"Subject: {draft.subject}")
    print()

    if args.show_validation:
        if draft.validation_errors:
            print("Validation errors:")
            for e in draft.validation_errors:
                print(f"  - {e}")
            print()
        if draft.validation_warnings:
            print("Validation warnings:")
            for w in draft.validation_warnings:
                print(f"  - {w}")
            print()
        if draft.unsupported_claims:
            print("Unsupported claims:")
            for c in draft.unsupported_claims:
                print(f"  - {c}")
            print()

    if args.show_grounding:
        print("Used fact codes:")
        for fc in draft.used_fact_codes:
            print(f"  - {fc}")
        print()
        print("Used source URLs:")
        for url in draft.used_source_urls:
            print(f"  - {url}")
        print()

    print("--- Draft Body ---")
    print(draft.body)

    if args.output:
        args.output.write_text(draft.body, encoding="utf-8")
        print(f"\nDraft written to {args.output}")


if __name__ == "__main__":
    main()