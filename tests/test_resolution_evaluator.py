from pathlib import Path

from src.support.resolution_evaluator import THRESHOLDS, evaluate_resolutions


def test_tuning_resolution_evaluation_passes_thresholds():
    result = evaluate_resolutions(Path("data/metronome_docs.db"), split_filter="tuning")

    assert result.passed
    assert result.tuning.cases >= 10
    assert result.tuning.root_cause_accuracy >= THRESHOLDS["root_cause_accuracy"]


def test_holdout_resolution_evaluation_passes_thresholds():
    result = evaluate_resolutions(Path("data/metronome_docs.db"), split_filter="holdout")

    assert result.passed
    assert result.holdout.cases >= 3
    assert result.holdout.gap_classification_accuracy >= THRESHOLDS["gap_classification_accuracy"]


def test_resolution_evaluation_case_count():
    result = evaluate_resolutions(Path("data/metronome_docs.db"))

    assert result.tuning.cases + result.holdout.cases >= 12


def test_resolution_evaluation_reports_invalid_rejection_and_transition_metrics():
    result = evaluate_resolutions(Path("data/metronome_docs.db"), split_filter="tuning")

    assert result.tuning.invalid_resolution_rejection_accuracy == 100.0
    assert result.tuning.feedback_state_transition_accuracy == 100.0


def test_resolution_threshold_failure_behavior(tmp_path):
    cases = tmp_path / "bad_resolution_cases.json"
    cases.write_text(
        """
{
  "cases": [
    {
      "id": "bad-root",
      "resolution_input_file": "data/examples/resolutions/usage_property_mismatch.json",
      "ticket_input_file": "data/examples/usage_property_filter_mismatch.json",
      "split": "holdout",
      "expected": {
        "expected_root_cause_code": "usage.event_type_mismatch",
        "expected_gap_codes": [
          "docs.missing_troubleshooting",
          "product.no_event_matching_visibility",
          "support.missing_regression_case"
        ],
        "expected_regression_case": true
      }
    }
  ]
}
""",
        encoding="utf-8",
    )

    result = evaluate_resolutions(
        Path("data/metronome_docs.db"),
        cases_path=cases,
        split_filter="holdout",
    )

    assert not result.passed
    assert result.holdout.root_cause_accuracy == 0.0
