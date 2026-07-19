from pathlib import Path

from src.support.evaluator import THRESHOLDS, evaluate_tickets


def test_tuning_evaluation_passes_thresholds():
    result = evaluate_tickets(Path("data/metronome_docs.db"), split_filter="tuning")

    assert result.passed
    assert result.tuning.cases >= 12
    assert result.tuning.purpose_source_recall >= THRESHOLDS["purpose_source_recall"]


def test_holdout_evaluation_passes_thresholds():
    result = evaluate_tickets(Path("data/metronome_docs.db"), split_filter="holdout")

    assert result.passed
    assert result.holdout.cases >= 4
    assert result.holdout.checklist_precision >= THRESHOLDS["checklist_precision"]


def test_evaluation_reports_zero_redundant_and_already_complete_rates():
    result = evaluate_tickets(Path("data/metronome_docs.db"), split_filter="holdout")

    assert result.holdout.redundant_step_rate == 0.0
    assert result.holdout.already_complete_step_rate <= THRESHOLDS["already_complete_step_rate"]


def test_threshold_failure_behavior(tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text('{"cases":[{"id":"bad","input_file":"data/examples/contract_409.json","split":"holdout","expected":{"product_area":"usage"}}]}', encoding="utf-8")

    result = evaluate_tickets(Path("data/metronome_docs.db"), cases_path=cases, split_filter="holdout")

    assert not result.passed
