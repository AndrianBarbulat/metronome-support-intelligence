"""Confirmed-resolution evaluation with stable-code metrics."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.database.repository import DocumentationRepository
from src.feedback.evaluator import transition_is_valid

from .analyzer import analyze_support_ticket
from .resolution_models import ConfirmedResolution, TicketResolutionInput
from .resolution_service import (
    ResolutionServiceError,
    confirm_ticket_resolution,
    load_resolution_from_json,
)
from .ticket_parser import load_ticket_from_json


THRESHOLDS = {
    "validation_accuracy": 95.0,
    "root_cause_accuracy": 95.0,
    "hypothesis_outcome_accuracy": 90.0,
    "verification_completeness": 90.0,
    "regression_case_accuracy": 95.0,
    "gap_classification_accuracy": 85.0,
    "documentation_gap_accuracy": 85.0,
    "product_gap_accuracy": 85.0,
    "abstention_accuracy": 100.0,
    "secret_redaction_accuracy": 100.0,
    "invalid_resolution_rejection_accuracy": 100.0,
    "feedback_state_transition_accuracy": 100.0,
}


@dataclass
class ResolutionSplitResult:
    cases: int = 0
    validation_accuracy: float = 0.0
    root_cause_accuracy: float = 0.0
    hypothesis_outcome_accuracy: float = 0.0
    verification_completeness: float = 0.0
    regression_case_accuracy: float = 0.0
    gap_classification_accuracy: float = 0.0
    documentation_gap_accuracy: float = 0.0
    product_gap_accuracy: float = 0.0
    abstention_accuracy: float = 0.0
    secret_redaction_accuracy: float = 0.0
    invalid_resolution_rejection_accuracy: float = 0.0
    feedback_state_transition_accuracy: float = 0.0
    failed: list[dict] = field(default_factory=list)


@dataclass
class ResolutionEvalResult:
    tuning: ResolutionSplitResult = field(default_factory=ResolutionSplitResult)
    holdout: ResolutionSplitResult = field(default_factory=ResolutionSplitResult)
    passed: bool = True


def evaluate_resolutions(
    database_path: Path,
    cases_path: Path = Path("data/evaluation/resolution_cases.json"),
    split_filter: str | None = None,
) -> ResolutionEvalResult:
    with cases_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    all_cases = data.get("cases", [])
    tuning_cases = [case for case in all_cases if case.get("split") == "tuning"]
    holdout_cases = [case for case in all_cases if case.get("split") == "holdout"]

    if split_filter == "tuning":
        splits = [("tuning", tuning_cases)]
    elif split_filter == "holdout":
        splits = [("holdout", holdout_cases)]
    else:
        splits = [("tuning", tuning_cases), ("holdout", holdout_cases)]

    results: dict[str, ResolutionSplitResult] = {}
    all_passed = True
    for split_name, cases in splits:
        if not cases:
            continue
        sr = _eval_split(database_path, cases)
        results[split_name] = sr
        if not _check_thresholds(sr):
            all_passed = False

    return ResolutionEvalResult(
        tuning=results.get("tuning", ResolutionSplitResult()),
        holdout=results.get("holdout", ResolutionSplitResult()),
        passed=all_passed,
    )


def _eval_split(database_path: Path, cases: list[dict]) -> ResolutionSplitResult:
    if not cases:
        return ResolutionSplitResult()

    validation_correct = validation_total = 0
    root_correct = root_total = 0
    outcome_correct = outcome_total = 0
    verification_correct = verification_total = 0
    regression_correct = regression_total = 0
    gap_correct = gap_total = 0
    docs_gap_correct = docs_gap_total = 0
    product_gap_correct = product_gap_total = 0
    abstention_correct = abstention_total = 0
    secret_correct = secret_total = 0
    invalid_correct = invalid_total = 0
    failed: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        eval_db = Path(tmp_dir) / "resolution_eval.db"
        shutil.copyfile(database_path, eval_db)
        repo = DocumentationRepository(eval_db)
        try:
            repo.initialize_schema()
        finally:
            repo.close()

        for case in cases:
            cid = case.get("id", "")
            expected = case.get("expected", {})
            expected_valid = expected.get("expect_valid", True)
            confirmed: ConfirmedResolution | None = None
            actual_valid = False
            error = ""

            try:
                resolution = _load_case_resolution(case)
                if resolution.ticket_id <= 0 or resolution.analysis_id <= 0:
                    resolution = _persist_investigation_for_case(case, resolution, eval_db)
                confirmed = confirm_ticket_resolution(resolution, eval_db)
                actual_valid = True
            except ResolutionServiceError as exc:
                error = str(exc)
                actual_valid = False
            except Exception as exc:
                error = str(exc)
                actual_valid = False
                failed.append({"id": cid, "error": error})

            validation_total += 1
            if actual_valid == expected_valid:
                validation_correct += 1

            if not expected_valid:
                invalid_total += 1
                if not actual_valid:
                    invalid_correct += 1
                continue

            if not actual_valid or confirmed is None:
                failed.append({"id": cid, "error": error or "resolution was not confirmed"})
                continue

            expected_root = expected.get("expected_root_cause_code")
            if expected_root:
                root_total += 1
                if confirmed.root_cause_code == expected_root:
                    root_correct += 1

            expected_outcomes = expected.get("expected_hypothesis_outcomes", {})
            actual_outcomes = {
                outcome.hypothesis_code: outcome.outcome
                for outcome in confirmed.hypothesis_outcomes
            }
            for code, expected_outcome in expected_outcomes.items():
                outcome_total += 1
                if actual_outcomes.get(code) == expected_outcome:
                    outcome_correct += 1

            verification_text = _text(
                confirmed.verification_steps + confirmed.verification_results
            )
            required_terms = expected.get("required_verification_terms", [])
            for term in required_terms:
                verification_total += 1
                if term.lower() in verification_text:
                    verification_correct += 1

            if "expected_regression_case" in expected:
                regression_total += 1
                has_regression = confirmed.regression_case is not None
                if has_regression == expected["expected_regression_case"]:
                    regression_correct += 1

            if "expected_gap_codes" in expected:
                expected_gaps = set(expected.get("expected_gap_codes", []))
                actual_gaps = {item.gap_code for item in confirmed.feedback_items}
                gap_total += 1
                if actual_gaps == expected_gaps:
                    gap_correct += 1

                expected_docs = {code for code in expected_gaps if code.startswith("docs.")}
                actual_docs = {code for code in actual_gaps if code.startswith("docs.")}
                docs_gap_total += 1
                if actual_docs == expected_docs:
                    docs_gap_correct += 1

                expected_product = {code for code in expected_gaps if code.startswith("product.")}
                actual_product = {code for code in actual_gaps if code.startswith("product.")}
                product_gap_total += 1
                if actual_product == expected_product:
                    product_gap_correct += 1

            if "expect_abstention" in expected:
                abstention_total += 1
                abstained = confirmed.regression_case is None and not confirmed.feedback_items
                if abstained == expected["expect_abstention"]:
                    abstention_correct += 1

            forbidden_terms = case.get("forbidden_persisted_terms", [])
            if forbidden_terms:
                secret_total += 1
                raw = eval_db.read_bytes()
                if all(term.encode("utf-8") not in raw for term in forbidden_terms):
                    secret_correct += 1

    return ResolutionSplitResult(
        cases=len(cases),
        validation_accuracy=_pct(validation_correct, validation_total, default=100.0),
        root_cause_accuracy=_pct(root_correct, root_total, default=100.0),
        hypothesis_outcome_accuracy=_pct(outcome_correct, outcome_total, default=100.0),
        verification_completeness=_pct(verification_correct, verification_total, default=100.0),
        regression_case_accuracy=_pct(regression_correct, regression_total, default=100.0),
        gap_classification_accuracy=_pct(gap_correct, gap_total, default=100.0),
        documentation_gap_accuracy=_pct(docs_gap_correct, docs_gap_total, default=100.0),
        product_gap_accuracy=_pct(product_gap_correct, product_gap_total, default=100.0),
        abstention_accuracy=_pct(abstention_correct, abstention_total, default=100.0),
        secret_redaction_accuracy=_pct(secret_correct, secret_total, default=100.0),
        invalid_resolution_rejection_accuracy=_pct(invalid_correct, invalid_total, default=100.0),
        feedback_state_transition_accuracy=_feedback_transition_accuracy(),
        failed=failed,
    )


def _load_case_resolution(case: dict) -> TicketResolutionInput:
    input_file = Path(case.get("resolution_input_file", ""))
    if not input_file.exists():
        raise FileNotFoundError(f"Resolution input not found: {input_file}")
    return load_resolution_from_json(input_file)


def _persist_investigation_for_case(
    case: dict,
    resolution: TicketResolutionInput,
    database_path: Path,
) -> TicketResolutionInput:
    raw = json.loads(Path(case["resolution_input_file"]).read_text(encoding="utf-8"))
    ticket_file = Path(case.get("ticket_input_file") or raw.get("ticket_input_file", ""))
    if not ticket_file.exists():
        raise FileNotFoundError(f"Ticket input not found: {ticket_file}")

    repo = DocumentationRepository(database_path)
    try:
        repo.initialize_schema()
        before = repo._get_conn().execute("SELECT COALESCE(MAX(id), 0) FROM support_tickets").fetchone()[0]
    finally:
        repo.close()

    ticket = load_ticket_from_json(ticket_file)
    analyze_support_ticket(ticket=ticket, database_path=database_path, persist=True)

    repo = DocumentationRepository(database_path)
    try:
        repo.initialize_schema()
        row = repo._get_conn().execute(
            """SELECT id FROM support_tickets
               WHERE id > ?
               ORDER BY id DESC
               LIMIT 1""",
            (before,),
        ).fetchone()
        if row is None:
            raise ValueError("Ticket investigation was not persisted")
        analysis = repo.get_latest_analysis_for_ticket(row["id"])
        if analysis is None:
            raise ValueError("Ticket analysis was not persisted")
        return replace(resolution, ticket_id=row["id"], analysis_id=analysis["id"])
    finally:
        repo.close()


def _feedback_transition_accuracy() -> float:
    checks = [
        transition_is_valid("draft", "request_changes"),
        transition_is_valid("needs_review", "approve"),
        transition_is_valid("approved", "mark_planned"),
        transition_is_valid("planned", "mark_implemented"),
        transition_is_valid("implemented", "mark_verified"),
        transition_is_valid("verified", "close"),
        not transition_is_valid("approved", "mark_implemented"),
        not transition_is_valid("closed", "approve"),
    ]
    return _pct(sum(1 for item in checks if item), len(checks), default=100.0)


def _pct(correct: int, total: int, default: float) -> float:
    return (correct / total * 100) if total > 0 else default


def _text(values: list[str]) -> str:
    return " ".join(value.lower() for value in values if value)


def _check_thresholds(sr: ResolutionSplitResult) -> bool:
    checks = [
        (sr.validation_accuracy, THRESHOLDS["validation_accuracy"]),
        (sr.root_cause_accuracy, THRESHOLDS["root_cause_accuracy"]),
        (sr.hypothesis_outcome_accuracy, THRESHOLDS["hypothesis_outcome_accuracy"]),
        (sr.verification_completeness, THRESHOLDS["verification_completeness"]),
        (sr.regression_case_accuracy, THRESHOLDS["regression_case_accuracy"]),
        (sr.gap_classification_accuracy, THRESHOLDS["gap_classification_accuracy"]),
        (sr.documentation_gap_accuracy, THRESHOLDS["documentation_gap_accuracy"]),
        (sr.product_gap_accuracy, THRESHOLDS["product_gap_accuracy"]),
        (sr.abstention_accuracy, THRESHOLDS["abstention_accuracy"]),
        (sr.secret_redaction_accuracy, THRESHOLDS["secret_redaction_accuracy"]),
        (
            sr.invalid_resolution_rejection_accuracy,
            THRESHOLDS["invalid_resolution_rejection_accuracy"],
        ),
        (
            sr.feedback_state_transition_accuracy,
            THRESHOLDS["feedback_state_transition_accuracy"],
        ),
    ]
    return not sr.failed and all(value >= threshold for value, threshold in checks)
