#!/usr/bin/env python3
"""Run the drafting evaluation suite against the evaluation dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.drafting.evaluator import evaluate_drafting
from src.drafting.models import DRAFT_EVALUATION_METRICS

CASES_PATH = _PROJECT_ROOT / "data" / "evaluation" / "drafting_cases.json"
DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"

REQUIRED_METRICS: dict[str, float] = {
    "structured_output_validity": 100.0,
    "fact_reference_validity": 100.0,
    "claim_map_validity": 100.0,
    "source_reference_validity": 100.0,
    "unsupported_claim_rejection": 100.0,
    "hypothesis_labelling_accuracy": 95.0,
    "resolution_status_compliance": 100.0,
    "secret_redaction_accuracy": 100.0,
    "required_section_coverage": 95.0,
    "customer_safety_accuracy": 100.0,
    "human_review_transition_accuracy": 100.0,
    "holdout_pass_rate": 100.0,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate drafting quality and safety.")
    parser.add_argument(
        "--split",
        choices=["tuning", "holdout", "all"],
        default="all",
        help="Which split to evaluate (default: all).",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run scripts/sync_documentation.py first.")
        sys.exit(1)

    print(f"Evaluating drafting cases from: {CASES_PATH}")
    print(f"Split: {args.split}")
    print()

    report = evaluate_drafting(
        cases_path=CASES_PATH,
        database_path=DB_PATH,
        split=args.split,
    )

    print(f"Total cases:    {report.total_cases}")
    print(f"  Tuning:       {report.tuning_cases}")
    print(f"  Holdout:      {report.holdout_cases}")
    print()
    print(f"Passed tuning:  {report.passed_tuning}/{report.tuning_cases}")
    print(f"Passed holdout: {report.passed_holdout}/{report.holdout_cases}")
    print()

    all_passed = True
    for metric_name, threshold in sorted(REQUIRED_METRICS.items()):
        val = 0.0
        for split_name in ("tuning", "holdout"):
            m = report.metrics.get(metric_name, {})
            v = m.get(split_name, 0.0)
            if v > val:
                val = v
        status = "PASS" if val >= threshold else "FAIL"
        if val < threshold:
            all_passed = False
        print(f"  {metric_name:<45} {val:>6.1f}%  (threshold: {threshold}%)  [{status}]")

    print()
    if report.failures:
        print(f"Failures ({len(report.failures)}):")
        for f in report.failures:
            print(f"  - [{f['split']}] {f['case_id']}: {f['reason']}")
        print()

    if all_passed:
        print("All drafting evaluation thresholds passed.")
    else:
        print("Some thresholds were NOT met.")
        sys.exit(1)


if __name__ == "__main__":
    main()