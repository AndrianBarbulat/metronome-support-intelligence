#!/usr/bin/env python3
"""CLI for evaluating confirmed-resolution quality."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate confirmed-resolution quality.")
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    parser.add_argument("--cases", type=Path, default=Path("data/evaluation/resolution_cases.json"))
    parser.add_argument("--split", type=str, default="all", choices=["all", "tuning", "holdout"])
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.support.resolution_evaluator import evaluate_resolutions

    db_path = args.database if args.database.is_absolute() else project_root / args.database
    cases_path = args.cases if args.cases.is_absolute() else project_root / args.cases
    split_filter = None if args.split == "all" else args.split
    result = evaluate_resolutions(
        database_path=db_path,
        cases_path=cases_path,
        split_filter=split_filter,
    )

    print("\nConfirmed Resolution Evaluation\n")
    for split_name, sr in [("Tuning", result.tuning), ("Holdout", result.holdout)]:
        if sr.cases == 0:
            continue
        print(f"{split_name} cases: {sr.cases}")
        print(f"Resolution validation: {sr.validation_accuracy:.1f}%")
        print(f"Root-cause accuracy: {sr.root_cause_accuracy:.1f}%")
        print(f"Hypothesis outcomes: {sr.hypothesis_outcome_accuracy:.1f}%")
        print(f"Verification completeness: {sr.verification_completeness:.1f}%")
        print(f"Regression-case accuracy: {sr.regression_case_accuracy:.1f}%")
        print(f"Gap classification: {sr.gap_classification_accuracy:.1f}%")
        print(f"Documentation gaps: {sr.documentation_gap_accuracy:.1f}%")
        print(f"Product gaps: {sr.product_gap_accuracy:.1f}%")
        print(f"Abstention: {sr.abstention_accuracy:.1f}%")
        print(f"Secret redaction: {sr.secret_redaction_accuracy:.1f}%")
        print(f"Invalid-resolution rejection: {sr.invalid_resolution_rejection_accuracy:.1f}%")
        print(f"Feedback transitions: {sr.feedback_state_transition_accuracy:.1f}%")
        if sr.failed:
            for failure in sr.failed:
                print(f"  FAILED: {failure}")
        print()

    if not result.passed:
        print("Resolution quality thresholds not met.")
        sys.exit(1)


if __name__ == "__main__":
    main()
