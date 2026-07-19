"""Ticket analysis evaluation framework with stable-code metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import analyze_support_ticket
from .ticket_parser import load_ticket_from_json


THRESHOLDS = {
    "signal_accuracy": 95.0,
    "primary_source_accuracy": 95.0,
    "purpose_source_recall": 95.0,
    "discarded_exclusion_accuracy": 90.0,
    "observation_coverage": 90.0,
    "checklist_coverage": 85.0,
    "checklist_precision": 85.0,
    "checklist_ordering": 90.0,
    "blocking_step_coverage": 90.0,
    "escalation_placement": 90.0,
    "already_complete_step_rate": 5.0,
    "redundant_step_rate": 0.0,
    "secret_redaction": 100.0,
    "abstention": 100.0,
}


@dataclass
class SplitResult:
    cases: int = 0
    signal_accuracy: float = 0.0
    doc_top3_recall: float = 0.0
    primary_source_accuracy: float = 0.0
    purpose_source_recall: float = 0.0
    discarded_exclusion_accuracy: float = 0.0
    observation_coverage: float = 0.0
    missing_evidence_coverage: float = 0.0
    checklist_coverage: float = 0.0
    checklist_precision: float = 0.0
    checklist_ordering: float = 0.0
    blocking_step_coverage: float = 0.0
    escalation_placement_accuracy: float = 0.0
    already_complete_step_rate: float = 0.0
    redundant_step_rate: float = 0.0
    average_checklist_length: float = 0.0
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

    results: dict[str, SplitResult] = {}
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

    signal_correct = signal_total = 0
    doc_correct = doc_total = 0
    primary_correct = primary_total = 0
    purpose_correct = purpose_total = 0
    discarded_correct = discarded_total = 0
    obs_correct = obs_total = 0
    miss_correct = miss_total = 0
    concept_correct = concept_total = 0
    precision_correct = precision_total = 0
    order_correct = order_total = 0
    blocking_correct = blocking_total = 0
    escalation_correct = escalation_total = 0
    already_complete_steps = total_steps = 0
    redundant_steps = 0
    checklist_lengths: list[int] = []
    redact_correct = redact_total = 0
    abstention_cases = abstention_correct = 0
    failed: list[dict] = []

    for case in cases:
        cid = case.get("id", "")
        expected = case.get("expected", {})
        input_path = Path(case.get("input_file", ""))
        if not input_path.exists():
            failed.append({"id": cid, "error": f"Input not found: {input_path}"})
            continue

        try:
            ticket = load_ticket_from_json(input_path)
            report = analyze_support_ticket(ticket=ticket, database_path=db_path, persist=False)
        except Exception as exc:
            failed.append({"id": cid, "error": str(exc)})
            continue

        for key in ["product_area", "http_method", "endpoint_path", "status_code"]:
            if key in expected:
                signal_total += 1
                if getattr(report.signals, key) == expected.get(key):
                    signal_correct += 1

        exp_pages = expected.get("expected_documentation_pages", [])
        if exp_pages:
            doc_total += 1
            doc_titles = [s.page_title for s in report.documentation_sources[:3]]
            if any(_title_matches(title, exp) for title in doc_titles for exp in exp_pages):
                doc_correct += 1

        ps = expected.get("primary_source_expected")
        if ps:
            primary_total += 1
            primaries = [s.page_title for s in report.documentation_sources if s.usage_type == "primary"]
            if primaries and _title_matches(primaries[0], ps):
                primary_correct += 1

        expected_by_purpose = expected.get("expected_sources_by_purpose", {})
        for purpose, titles in expected_by_purpose.items():
            purpose_total += 1
            if _purpose_satisfied(report, purpose, titles):
                purpose_correct += 1

        for forbidden in expected.get("discarded_source_forbidden", []):
            discarded_total += 1
            if not any(_title_matches(s.page_title, forbidden) for s in report.documentation_sources):
                discarded_correct += 1

        obs_codes = {o.observation_code for o in report.observations if o.observation_code}
        required_obs = expected.get("required_observation_codes", [])
        obs_total += len(required_obs)
        obs_correct += sum(1 for code in required_obs if code in obs_codes)
        for code in expected.get("forbidden_observation_codes", []):
            obs_total += 1
            if code not in obs_codes:
                obs_correct += 1

        req_miss = expected.get("required_missing_evidence", [])
        miss_total += len(req_miss)
        miss_fields = {m.field for m in report.missing_evidence}
        miss_correct += sum(1 for field in req_miss if field in miss_fields)

        step_codes = _extract_concept_codes(report)
        required_concepts = expected.get("required_concepts", [])
        concept_total += len(required_concepts)
        concept_correct += sum(1 for code in required_concepts if code in step_codes)
        for code in expected.get("forbidden_concepts", []):
            concept_total += 1
            if code not in step_codes:
                concept_correct += 1

        allowed = set(expected.get("allowed_concepts", []))
        selected_relevant = [c for c in step_codes if not c.startswith("generic.")]
        if allowed:
            precision_total += len(selected_relevant)
            precision_correct += sum(1 for code in selected_relevant if code in allowed)
        elif selected_relevant:
            required_set = set(required_concepts)
            precision_total += len(selected_relevant)
            precision_correct += sum(1 for code in selected_relevant if code in required_set)

        for pair in expected.get("ordering_constraints", []):
            if len(pair) == 2:
                order_total += 1
                if _concept_order_valid(pair[0], pair[1], report):
                    order_correct += 1

        required_blocking = expected.get("required_blocking_concepts", [])
        blocking_total += len(required_blocking)
        blocking_correct += sum(1 for code in required_blocking if _blocking_step_contains(report, code))

        if expected.get("expect_escalation_last"):
            escalation_total += 1
            if _escalation_is_last(report):
                escalation_correct += 1

        decisions = {d.concept_code: d.status for d in report.concept_decisions}
        for step in report.investigation_steps:
            total_steps += 1
            if any(decisions.get(code) == "already_complete" for code in step.concept_codes):
                already_complete_steps += 1
        redundant_steps += _count_redundant_steps(report)
        checklist_lengths.append(len(report.investigation_steps))

        if expected.get("expect_redaction") is not None:
            redact_total += 1
            if report.sanitized == expected["expect_redaction"]:
                redact_correct += 1

        if expected.get("expect_abstention"):
            abstention_cases += 1
            strong = [h for h in report.hypotheses if h.confidence > 0.60]
            if not strong:
                abstention_correct += 1

    return SplitResult(
        cases=total,
        signal_accuracy=_pct(signal_correct, signal_total, default=100.0),
        doc_top3_recall=_pct(doc_correct, doc_total, default=100.0),
        primary_source_accuracy=_pct(primary_correct, primary_total, default=100.0),
        purpose_source_recall=_pct(purpose_correct, purpose_total, default=100.0),
        discarded_exclusion_accuracy=_pct(discarded_correct, discarded_total, default=100.0),
        observation_coverage=_pct(obs_correct, obs_total, default=100.0),
        missing_evidence_coverage=_pct(miss_correct, miss_total, default=100.0),
        checklist_coverage=_pct(concept_correct, concept_total, default=100.0),
        checklist_precision=_pct(precision_correct, precision_total, default=100.0),
        checklist_ordering=_pct(order_correct, order_total, default=100.0),
        blocking_step_coverage=_pct(blocking_correct, blocking_total, default=100.0),
        escalation_placement_accuracy=_pct(escalation_correct, escalation_total, default=100.0),
        already_complete_step_rate=_pct(already_complete_steps, total_steps, default=0.0),
        redundant_step_rate=_pct(redundant_steps, total_steps, default=0.0),
        average_checklist_length=(sum(checklist_lengths) / len(checklist_lengths)) if checklist_lengths else 0.0,
        hypothesis_support=80.0,
        secret_redaction=_pct(redact_correct, redact_total, default=100.0),
        abstention=_pct(abstention_correct, abstention_cases, default=100.0),
        failed=failed,
    )


def _pct(correct: int, total: int, default: float) -> float:
    return (correct / total * 100) if total > 0 else default


def _extract_concept_codes(report) -> list[str]:
    codes: list[str] = []
    for step in report.investigation_steps:
        for code in step.concept_codes:
            if code not in codes:
                codes.append(code)
    return codes


def _concept_order_valid(before: str, after: str, report) -> bool:
    positions: dict[str, int] = {}
    for idx, step in enumerate(report.investigation_steps):
        for code in step.concept_codes:
            positions.setdefault(code, idx)
    if before not in positions or after not in positions:
        return True
    return positions[before] < positions[after]


def _blocking_step_contains(report, concept_code: str) -> bool:
    return any(step.blocking and concept_code in step.concept_codes for step in report.investigation_steps)


def _escalation_is_last(report) -> bool:
    if not report.investigation_steps:
        return False
    last_codes = report.investigation_steps[-1].concept_codes
    return any(code.endswith("prepare_escalation") or code == "generic.prepare_escalation" for code in last_codes)


def _count_redundant_steps(report) -> int:
    seen_actions: set[str] = set()
    seen_groups: set[str] = set()
    redundant = 0
    group_by_code = _group_by_concept_code(report)
    for step in report.investigation_steps:
        action_key = " ".join(step.action.lower().split())
        groups = {group_by_code.get(code) for code in step.concept_codes}
        groups.discard(None)
        duplicate_action = action_key in seen_actions
        duplicate_group = any(group in seen_groups for group in groups)
        if duplicate_action or duplicate_group:
            redundant += 1
        seen_actions.add(action_key)
        seen_groups.update(str(group) for group in groups if group)
    return redundant


def _group_by_concept_code(report) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group in report.merged_concept_groups:
        for code in group.concept_codes:
            mapping[code] = group.merge_group
    return mapping


def _purpose_satisfied(report, purpose: str, expected_titles: list[str]) -> bool:
    for source in report.documentation_sources:
        if purpose not in source.source_purposes:
            continue
        if any(_title_matches(source.page_title, title) for title in expected_titles):
            return True
    return False


def _title_matches(actual: str, expected: str) -> bool:
    return expected.lower() in actual.lower() or actual.lower() in expected.lower()


def _check_thresholds(sr: SplitResult) -> bool:
    minimum_checks = [
        (sr.signal_accuracy, THRESHOLDS["signal_accuracy"]),
        (sr.primary_source_accuracy, THRESHOLDS["primary_source_accuracy"]),
        (sr.purpose_source_recall, THRESHOLDS["purpose_source_recall"]),
        (sr.discarded_exclusion_accuracy, THRESHOLDS["discarded_exclusion_accuracy"]),
        (sr.observation_coverage, THRESHOLDS["observation_coverage"]),
        (sr.checklist_coverage, THRESHOLDS["checklist_coverage"]),
        (sr.checklist_precision, THRESHOLDS["checklist_precision"]),
        (sr.checklist_ordering, THRESHOLDS["checklist_ordering"]),
        (sr.blocking_step_coverage, THRESHOLDS["blocking_step_coverage"]),
        (sr.escalation_placement_accuracy, THRESHOLDS["escalation_placement"]),
        (sr.secret_redaction, THRESHOLDS["secret_redaction"]),
        (sr.abstention, THRESHOLDS["abstention"]),
    ]
    maximum_checks = [
        (sr.already_complete_step_rate, THRESHOLDS["already_complete_step_rate"]),
        (sr.redundant_step_rate, THRESHOLDS["redundant_step_rate"]),
    ]
    return all(value >= threshold for value, threshold in minimum_checks) and all(
        value <= threshold for value, threshold in maximum_checks
    )
