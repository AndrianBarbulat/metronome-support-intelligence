#!/usr/bin/env python3
"""Inspect a confirmed resolution for a support ticket."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a ticket's confirmed resolution.")
    parser.add_argument("--ticket-id", type=int, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.database.repository import DocumentationRepository

    db_path = args.database if args.database.is_absolute() else project_root / args.database
    repo = DocumentationRepository(db_path)
    try:
        repo.initialize_schema()
        details = repo.get_resolution_details_for_ticket(args.ticket_id)
        analysis = repo.get_latest_analysis_for_ticket(args.ticket_id)
    finally:
        repo.close()

    if details["resolution"] is None:
        print(f"No confirmed resolution found for ticket {args.ticket_id}.")
        return

    resolution = details["resolution"]
    print(f"Ticket {args.ticket_id}")
    if analysis is not None:
        print(f"Investigation: {analysis['summary']}")
        hypotheses = json.loads(analysis["hypotheses_json"])
        if hypotheses:
            print("\nEarlier hypotheses")
            for hypothesis in hypotheses:
                code = hypothesis.get("hypothesis_code") or "uncoded"
                print(f"- {code}: {hypothesis.get('title', '')}")

    print("\nConfirmed root cause")
    print(f"{resolution['root_cause_code']} ({resolution['resolution_status']})")
    print(resolution["root_cause_summary"])

    print("\nResolution steps")
    for step in json.loads(resolution["resolution_steps_json"]):
        print(f"- {step}")

    print("\nVerification results")
    for result in json.loads(resolution["verification_results_json"]):
        print(f"- {result}")

    if details["outcomes"]:
        print("\nHypothesis outcomes")
        for outcome in details["outcomes"]:
            print(f"- {outcome['hypothesis_code']}: {outcome['outcome']}")

    if details["regression_cases"]:
        print("\nRegression cases")
        for case in details["regression_cases"]:
            print(f"- {case['case_code']}: {case['title']} [{case['automation_status']}]")

    if details["feedback_items"]:
        print("\nFeedback proposals")
        for item in details["feedback_items"]:
            print(f"- [{item['status']}] {item['gap_code']}: {item['title']}")


if __name__ == "__main__":
    main()
