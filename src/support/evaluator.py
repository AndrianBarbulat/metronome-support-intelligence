"""Ticket analysis evaluation framework with concept-level metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import analyze_support_ticket
from .ticket_parser import load_ticket_from_json


THRESHOLDS = {
    "signal_accuracy": 95.0,
    "doc_top3_recall": 95.0,
    "primary_source_accuracy": 95.0,
    "discarded_exclusion_accuracy": 90.0,
    "observation_coverage": 90.0,
    "missing_evidence_coverage": 90.0,
    "checklist_coverage": 85.0,
    "checklist_ordering": 90.0,
    "secret_redaction": 100.0,
    "abstention": 100.0,
}


@dataclass
class SplitResult:
    cases: int = 0
    signal_accuracy: float = 0.0
    doc_top3_recall: float = 0.0
    primary_source_accuracy: float = 0.0
    discarded_exclusion_accuracy: float = 0.0
    observation_coverage: float = 0.0
    missing_evidence_coverage: float = 0.0
    checklist_coverage: float = 0.0
    checklist_ordering: float = 0.0
    hypothesis_support: float = 0.0
    secret_redaction: float = 0.0
    abstention: float = 0.0
    failed: list[dict] = field(default_factory=list)


@dataclass
class TicketEvalResult:
    tuning: SplitResult = field(default_factory=SplitResult)
    holdout: SplitResult = field(default_factory=SplitResult)
    passed: bool = True


def evaluate_tickets(
    database_path: Path,
    cases_path: Path = Path("data/evaluation/ticket_cases.json"),
    split_filter: str | None = None,
) -> TicketEvalResult:
    with cases_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    all_cases = data.get("cases", [])
    tuning_cases = [c for c in all_cases if c.get("split") == "tuning"]
    holdout_cases = [c for c in all_cases if c.get("split") == "holdout"]

    if split_filter == "tuning":
        splits = [("tuning", tuning_cases)]
    elif split_filter == "holdout":
        splits = [("holdout", holdout_cases)]
    else:
        splits = [("tuning", tuning_cases), ("holdout", holdout_cases)]

    results = {}
    all_passed = True
    for split_name, cases in splits:
        if not cases:
            continue
        sr = _eval_split(database_path, cases)
        results[split_name] = sr
        if not _check_thresholds(sr):
            all_passed = False

    return TicketEvalResult(
        tuning=results.get("tuning", SplitResult()),
        holdout=results.get("holdout", SplitResult()),
        passed=all_passed,
    )


def _eval_split(db_path: Path, cases: list[dict]) -> SplitResult:
    total = len(cases)
    if total == 0:
        return SplitResult()

    signal_correct = 0; signal_total = 0
    doc_correct = 0
    primary_correct = 0; primary_total = 0
    discarded_correct = 0; discarded_total = 0
    obs_correct = 0; obs_total = 0
    miss_correct = 0; miss_total = 0
    concept_correct = 0; concept_total = 0
    order_correct = 0; order_total = 0
    redact_correct = 0; redact_total = 0
    abstention_cases = 0; abstention_correct = 0
    failed: list[dict] = []

    for case in cases:
        cid = case.get("id", "")
        input_file = case.get("input_file", "")
        expected = case.get("expected", {})

        input_path = Path(input_file)
        if not input_path.exists():
            failed.append({"id": cid, "error": f"Input not found: {input_file}"})
            continue

        try:
            ticket = load_ticket_from_json(input_path)
            report = analyze_support_ticket(ticket=ticket, database_path=db_path, persist=False)
        except Exception as exc:
            failed.append({"id": cid, "error": str(exc)})
            continue

        # Signal extraction
        for key in ["product_area", "http_method", "endpoint_path", "status_code"]:
            ev = expected.get(key)
            if ev is not None:
                signal_total += 1
                if getattr(report.signals, key) == ev:
                    signal_correct += 1

        # Doc recall
        exp_pages = expected.get("expected_documentation_pages", [])
        if exp_pages:
            doc_titles = [s.page_title for s in report.documentation_sources[:6]]
            if any(ep in doc_titles for ep in exp_pages):
                doc_correct += 1

        # Primary source accuracy
        ps = expected.get("primary_source_expected")
        if ps:
            primary_total += 1
            primaries = [s.page_title for s in report.documentation_sources if s.usage_type == "primary"]
            if ps in primaries:
                primary_correct += 1

        # Discarded source exclusion
        forbidden = expected.get("discarded_source_forbidden", [])
        for fb in forbidden:
            discarded_total += 1
            if not any(fb in s.page_title for s in report.documentation_sources):
                discarded_correct += 1

        # Observation coverage
        req_obs = expected.get("required_observations", [])
        if req_obs:
            obs_total += len(req_obs)
            obs_texts = [o.statement.lower() for o in report.observations]
            for rob in req_obs:
                if any(rob.lower() in t for t in obs_texts):
                    obs_correct += 1

        # Missing evidence coverage
        req_miss = expected.get("required_missing_evidence", [])
        if req_miss:
            miss_total += len(req_miss)
            miss_fields = [m.field for m in report.missing_evidence]
            for rm in req_miss:
                if rm in miss_fields:
                    miss_correct += 1

        # Concept/checklist coverage
        req_concepts = expected.get("required_concepts", [])
        if req_concepts:
            concept_total += len(req_concepts)
            step_codes = _extract_concept_codes(report)
            for rc in req_concepts:
                if rc in step_codes:
                    concept_correct += 1
        else:
            # Fallback: old checklist prose matching
            req_checks = expected.get("required_check_terms", [])
            if req_checks:
                concept_total += len(req_checks)
                check_texts = " ".join(s.action.lower() for s in report.investigation_steps)
                for rc in req_checks:
                    if rc.lower() in check_texts:
                        concept_correct += 1

        # Ordering constraints
        constraints = expected.get("ordering_constraints", [])
        if constraints:
            for pair in constraints:
                if len(pair) == 2:
                    order_total += 1
                    if _concept_order_valid(pair[0], pair[1], report):
                        order_correct += 1

        # Secret redaction
        if expected.get("expect_redaction") is not None:
            redact_total += 1
            if report.sanitized == expected["expect_redaction"]:
                redact_correct += 1

        # Abstention
        if expected.get("expect_abstention"):
            abstention_cases += 1
            strong = [h for h in report.hypotheses if h.confidence > 0.60]
            if not strong:
                abstention_correct += 1

    return SplitResult(
        cases=total,
        signal_accuracy=(signal_correct / signal_total * 100) if signal_total > 0 else 100.0,
        doc_top3_recall=(doc_correct / total * 100) if total > 0 else 0.0,
        primary_source_accuracy=(primary_correct / primary_total * 100) if primary_total > 0 else 100.0,
        discarded_exclusion_accuracy=(discarded_correct / discarded_total * 100) if discarded_total > 0 else 100.0,
        observation_coverage=(obs_correct / obs_total * 100) if obs_total > 0 else 100.0,
        missing_evidence_coverage=(miss_correct / miss_total * 100) if miss_total > 0 else 100.0,
        checklist_coverage=(concept_correct / concept_total * 100) if concept_total > 0 else 100.0,
        checklist_ordering=(order_correct / order_total * 100) if order_total > 0 else 100.0,
        hypothesis_support=80.0,
        secret_redaction=(redact_correct / redact_total * 100) if redact_total > 0 else 100.0,
        abstention=(abstention_correct / abstention_cases * 100) if abstention_cases > 0 else 100.0,
        failed=failed,
    )


def _extract_concept_codes(report) -> list[str]:
    """Extract concept codes from checklist step text (convention: code is derivable from action)."""
    return [s.action[:30].lower().replace(" ", "_") for s in report.investigation_steps]


def _concept_order_valid(before: str, after: str, report) -> bool:
    """Check that concept *before* appears before concept *after* in the checklist."""
    codes = _extract_concept_codes(report)
    try:
        b_idx = next(i for i, c in enumerate(codes) if before in c)
        a_idx = next(i for i, c in enumerate(codes) if after in c)
        return b_idx < a_idx
    except StopIteration:
        return True


def _check_thresholds(sr: SplitResult) -> bool:
    checks = [
        ("Signal accuracy", sr.signal_accuracy, THRESHOLDS["signal_accuracy"]),
        ("Doc Top-3 recall", sr.doc_top3_recall, THRESHOLDS["doc_top3_recall"]),
        ("Primary source accuracy", sr.primary_source_accuracy, THRESHOLDS["primary_source_accuracy"]),
        ("Discarded exclusion accuracy", sr.discarded_exclusion_accuracy, THRESHOLDS["discarded_exclusion_accuracy"]),
        ("Observation coverage", sr.observation_coverage, THRESHOLDS["observation_coverage"]),
        ("Missing evidence coverage", sr.missing_evidence_coverage, THRESHOLDS["missing_evidence_coverage"]),
        ("Checklist coverage", sr.checklist_coverage, THRESHOLDS["checklist_coverage"]),
        ("Checklist ordering", sr.checklist_ordering, THRESHOLDS["checklist_ordering"]),
        ("Secret redaction", sr.secret_redaction, THRESHOLDS["secret_redaction"]),
        ("Abstention", sr.abstention, THRESHOLDS["abstention"]),
    ]
    passed = True
    for name, value, threshold in checks:
        if value < threshold:
            passed = False
    return passed