"""Validation for human-submitted ticket resolutions."""

from __future__ import annotations

from datetime import datetime

from .models import SupportTicketInput, TicketInvestigationReport
from .resolution_models import (
    CONFIRMED_RESOLUTION_STATUSES,
    ROOT_CAUSE_CATEGORIES,
    ROOT_CAUSE_CODES,
    SUPPORTED_RESOLUTION_STATUSES,
    ResolutionValidationResult,
    TicketResolutionInput,
    category_for_root_cause,
)
from .sanitizer import sanitize_ticket


def validate_resolution(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> ResolutionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not resolution.ticket_id:
        errors.append("ticket_id is required")
    if not resolution.analysis_id:
        errors.append("analysis_id is required")
    if investigation.ticket_id is not None and investigation.ticket_id != resolution.ticket_id:
        errors.append("analysis does not belong to the ticket")

    if resolution.resolution_status not in SUPPORTED_RESOLUTION_STATUSES:
        errors.append(f"unsupported resolution_status: {resolution.resolution_status}")

    if resolution.root_cause_code not in ROOT_CAUSE_CODES:
        errors.append(f"unsupported root_cause_code: {resolution.root_cause_code}")
    expected_category = category_for_root_cause(resolution.root_cause_code)
    if resolution.root_cause_category not in ROOT_CAUSE_CATEGORIES:
        errors.append(f"unsupported root_cause_category: {resolution.root_cause_category}")
    elif resolution.root_cause_category != expected_category:
        errors.append("root_cause_category does not match root_cause_code")

    if resolution.resolution_status in CONFIRMED_RESOLUTION_STATUSES:
        if not resolution.root_cause_summary.strip():
            errors.append("confirmed resolutions require root_cause_summary")
        if not resolution.root_cause_details.strip():
            errors.append("confirmed resolutions require root_cause_details")
        if not resolution.resolution_steps:
            errors.append("confirmed resolutions require resolution_steps")

    if resolution.resolution_status == "unresolved" and resolution.root_cause_code != "insufficient_evidence":
        errors.append("unresolved cases cannot claim a confirmed root cause")
    if resolution.resolution_status == "cannot_reproduce" and resolution.root_cause_code != "cannot_reproduce":
        errors.append("cannot_reproduce cases must not claim a confirmed root cause")

    if not resolution.verification_steps:
        errors.append("verification_steps are required")
    if not resolution.verification_results:
        errors.append("verification_results are required")
    if not resolution.confirmed_by.strip():
        errors.append("confirmed_by is required")
    if not _valid_timestamp(resolution.confirmed_at):
        errors.append("confirmed_at must be a valid ISO-8601 timestamp")

    if resolution.resolution_status == "product_defect":
        evidence_text = _combined_text(resolution.resolution_steps + resolution.verification_steps + resolution.verification_results)
        if not any(term in evidence_text for term in ["reproduce", "reproduction", "request id", "escalat"]):
            errors.append("product_defect resolutions require reproduction or escalation evidence")

    if resolution.resolution_status == "documentation_issue" and not resolution.affected_sources:
        warnings.append("documentation_issue should identify affected documentation sources")

    if _contains_unredacted_secret(resolution):
        errors.append("resolution contains unredacted secrets")

    matched_observation_codes = _matched_observation_codes(resolution, investigation)
    matched_hypothesis_codes = _matched_hypothesis_codes(resolution, investigation)
    new_confirmed_facts = _new_confirmed_facts(resolution)

    if not _identifiers_overlap_resolution(resolution, investigation):
        warnings.append("resolution identifiers extend investigation evidence")

    return ResolutionValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        matched_observation_codes=matched_observation_codes,
        matched_hypothesis_codes=matched_hypothesis_codes,
        new_confirmed_facts=new_confirmed_facts,
    )


def _valid_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _contains_unredacted_secret(resolution: TicketResolutionInput) -> bool:
    ticket = SupportTicketInput(
        subject=resolution.root_cause_summary,
        customer_message="\n".join([
            resolution.root_cause_details,
            resolution.resolution_summary,
            "\n".join(resolution.resolution_steps),
            "\n".join(resolution.verification_steps),
            "\n".join(resolution.verification_results),
            resolution.internal_notes or "",
        ]),
    )
    return sanitize_ticket(ticket).redaction_count > 0


def _matched_observation_codes(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> list[str]:
    text = _resolution_text(resolution)
    matched: list[str] = []
    for observation in investigation.observations:
        if observation.observation_code and _code_terms_match(observation.observation_code, text):
            matched.append(observation.observation_code)
    return list(dict.fromkeys(matched))


def _matched_hypothesis_codes(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> list[str]:
    text = _resolution_text(resolution)
    matched: list[str] = []
    for hypothesis in investigation.hypotheses:
        if hypothesis.hypothesis_code and _code_terms_match(hypothesis.hypothesis_code, text):
            matched.append(hypothesis.hypothesis_code)
    return matched


def _new_confirmed_facts(resolution: TicketResolutionInput) -> list[str]:
    if resolution.resolution_status not in CONFIRMED_RESOLUTION_STATUSES:
        return []
    return [
        f"root_cause_code={resolution.root_cause_code}",
        f"root_cause_category={resolution.root_cause_category}",
        resolution.root_cause_summary,
    ]


def _identifiers_overlap_resolution(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> bool:
    identifiers = set(
        resolution.request_ids
        + resolution.transaction_ids
        + resolution.customer_ids
        + resolution.contract_ids
        + resolution.billable_metric_ids
        + resolution.invoice_ids
        + resolution.rate_card_ids
    )
    if not identifiers:
        return True
    investigation_text = _combined_text([
        investigation.summary,
        *[o.statement for o in investigation.observations],
        *[str(values) for values in investigation.signals.identifiers.values()],
    ])
    return any(identifier.lower() in investigation_text for identifier in identifiers)


def _resolution_text(resolution: TicketResolutionInput) -> str:
    return _combined_text([
        resolution.root_cause_code,
        resolution.root_cause_category,
        resolution.root_cause_summary,
        resolution.root_cause_details,
        resolution.resolution_summary,
        *resolution.resolution_steps,
        *resolution.verification_steps,
        *resolution.verification_results,
    ])


def _combined_text(values: list[str]) -> str:
    return " ".join(value.lower() for value in values if value)


def _code_terms_match(code: str, text: str) -> bool:
    parts = [part for part in code.replace(".", " ").replace("_", " ").split() if len(part) > 3]
    return bool(parts) and all(part in text for part in parts[:2])
