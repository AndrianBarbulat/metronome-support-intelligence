#!/usr/bin/env python3
"""Inspect a generated draft in detail."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database.repository import DocumentationRepository

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a generated draft.")
    parser.add_argument("--draft-id", type=int, required=True, help="Draft ID to inspect.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    repo = DocumentationRepository(DB_PATH)
    repo.initialize_schema()
    try:
        row = repo.get_generated_draft(args.draft_id)
        if row is None:
            print(f"Draft {args.draft_id} not found.")
            sys.exit(1)

        print(f"Draft ID:       {row['id']}")
        print(f"Draft Type:     {row['draft_type']}")
        print(f"Audience:       {row['audience']}")
        print(f"Tone:           {row['tone']}")
        print(f"Provider:       {row['provider']}")
        print(f"Model:          {row['model']}")
        print(f"Prompt Ver:     {row['prompt_version']}")
        print(f"Package Ver:    {row['grounding_package_version']}")
        print(f"Status:         {row['status']}")
        print(f"Validation:     {row['validation_status']}")
        print(f"Created:        {row['created_at']}")
        print()

        if row["reviewed_at"]:
            print(f"Reviewed at:    {row['reviewed_at']}")
            print(f"Reviewed by:    {row['reviewed_by']}")
            if row["review_notes"]:
                print(f"Review notes:   {row['review_notes']}")
            print()

        subject = row["subject"]
        if subject:
            print(f"Subject: {subject}")
            print()

        # Validation
        validation_errors = json.loads(row["validation_errors_json"])
        validation_warnings = json.loads(row["validation_warnings_json"])
        unsupported_claims = json.loads(row["unsupported_claims_json"])

        if validation_errors:
            print("Validation errors:")
            for e in validation_errors:
                print(f"  - {e}")
            print()
        if validation_warnings:
            print("Validation warnings:")
            for w in validation_warnings:
                print(f"  - {w}")
            print()
        if unsupported_claims:
            print("Unsupported claims:")
            for c in unsupported_claims:
                print(f"  - {c}")
            print()

        # Fact codes
        used_fact_codes = json.loads(row["used_fact_codes_json"])
        print(f"Used fact codes ({len(used_fact_codes)}):")
        for fc in used_fact_codes:
            print(f"  - {fc}")
        print()

        # Source URLs
        used_source_urls = json.loads(row["used_source_urls_json"])
        print(f"Used source URLs ({len(used_source_urls)}):")
        for url in used_source_urls:
            print(f"  - {url}")
        print()

        print("--- Draft Body ---")
        print(row["body"])

    finally:
        repo.close()


if __name__ == "__main__":
    main()