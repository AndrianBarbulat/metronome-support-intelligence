#!/usr/bin/env python3
"""CLI for evaluating ticket analysis quality."""

from __future__ import annotations

import argparse, sys
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ticket analysis quality.")
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    parser.add_argument("--cases", type=Path, default=Path("data/evaluation/ticket_cases.json"))
    parser.add_argument("--split", type=str, default="all", choices=["all", "tuning", "holdout"])
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    db_path = project_root / args.database
    cases_path = project_root / args.cases

    sys.path.insert(0, str(project_root))
    from src.support.evaluator import evaluate_tickets

    split_filter = None if args.split == "all" else args.split
    result = evaluate_tickets(database_path=db_path, cases_path=cases_path, split_filter=split_filter)

    print("\nSupport Ticket Investigation Evaluation\n")

    for split_name, sr in [("Tuning", result.tuning), ("Holdout", result.holdout)]:
        if sr.cases == 0:
            continue
        print(f"{split_name} cases: {sr.cases}")
        print(f"Signal extraction: {sr.signal_accuracy:.1f}%")
        print(f"Documentation Top-3 recall: {sr.doc_top3_recall:.1f}%")
        print(f"Primary-source accuracy: {sr.primary_source_accuracy:.1f}%")
        print(f"Discarded-source exclusion: {sr.discarded_exclusion_accuracy:.1f}%")
        print(f"Observation coverage: {sr.observation_coverage:.1f}%")
        print(f"Missing-evidence coverage: {sr.missing_evidence_coverage:.1f}%")
        print(f"Checklist coverage: {sr.checklist_coverage:.1f}%")
        print(f"Secret redaction: {sr.secret_redaction:.1f}%")
        print(f"Abstention: {sr.abstention:.1f}%")
        if sr.failed:
            for fc in sr.failed:
                print(f"  FAILED: {fc}")
        print()

    if not result.passed:
        print("Quality thresholds not met.")
        sys.exit(1)


if __name__ == "__main__":
    main()