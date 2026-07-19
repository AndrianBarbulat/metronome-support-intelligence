"""Suppress concepts that are already satisfied by ticket evidence."""

from __future__ import annotations

from dataclasses import dataclass, field

from .investigation_concepts import InvestigationConcept
from .models import ExtractedTicketSignals, SupportTicketInput, ValidationFinding


@dataclass
class ConceptSelectionDecision:
    concept_code: str
    status: str  # selected, already_complete, not_applicable, suppressed
    reasons: list[str] = field(default_factory=list)
    satisfied_by: list[str] = field(default_factory=list)


def evaluate_evidence_state(
    ticket: SupportTicketInput,
    signals: ExtractedTicketSignals,
) -> set[str]:
    """Return the set of active evidence-state flags for this ticket."""
    flags: set[str] = set()

    # Request evidence
    if ticket.http_method and signals.http_method:
        flags.add("http_method_present")
    if ticket.endpoint_path and signals.endpoint_path:
        flags.add("endpoint_present")
    if ticket.request_body:
        flags.add("request_body_present")

    # Response evidence
    if ticket.response_status is not None:
        flags.add("response_status_present")
    if ticket.response_body:
        flags.add("response_body_present")

    # Headers
    has_req_id = (
        (ticket.request_headers or {}).get("x-request-id")
        or (ticket.response_headers or {}).get("x-request-id")
    )
    if has_req_id:
        flags.add("request_id_present")

    # Behavior
    if ticket.expected_behavior:
        flags.add("expected_behavior_present")
    if ticket.actual_behavior:
        flags.add("actual_behavior_present")

    # Application-level responses (non-auth-error)
    if ticket.response_status and ticket.response_status not in (401, 403):
        if ticket.response_status >= 200 and ticket.response_status < 500:
            flags.add("status_2xx_application_response")

    # 409-specific
    if ticket.response_status == 409:
        flags.add("status_409")
    if ticket.response_status in (400, 422):
        flags.add("status_400")

    # Contract-specific
    if signals.product_area == "contracts":
        if "starting_at" in signals.request_fields:
            # Basic check: does it look like ISO-8601?
            st = None
            if isinstance(ticket.request_body, dict):
                st = ticket.request_body.get("starting_at")
            if st and isinstance(st, str) and "T" in st:
                flags.add("starting_at_valid_format")
        if "uniqueness_key" in signals.request_fields:
            flags.add("uniqueness_key_recorded")

    # Usage-specific
    if signals.product_area == "usage":
        if "transaction_id" in signals.request_fields:
            flags.add("transaction_id_present")

    return flags


def suppress_redundant_concepts(
    concepts: list[InvestigationConcept],
    ticket: SupportTicketInput,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
) -> tuple[list[InvestigationConcept], list[ConceptSelectionDecision]]:
    """Return (selected_concepts, all_decisions) after evidence-state evaluation."""
    flags = evaluate_evidence_state(ticket, signals)
    selected: list[InvestigationConcept] = []
    decisions: list[ConceptSelectionDecision] = []

    for c in concepts:
        decision = _evaluate_concept(c, flags, signals)
        decisions.append(decision)
        if decision.status == "selected":
            selected.append(c)

    return selected, decisions


def _evaluate_concept(
    concept: InvestigationConcept,
    flags: set[str],
    signals: ExtractedTicketSignals,
) -> ConceptSelectionDecision:
    # Check skip conditions
    for skip_cond in concept.skip_when:
        if skip_cond in flags:
            return ConceptSelectionDecision(
                concept_code=concept.code,
                status="suppressed",
                reasons=[f"Skip condition met: {skip_cond}"],
            )

    # Check complete conditions
    satisfied = [c for c in concept.complete_when if c in flags]
    if satisfied and concept.complete_when:
        return ConceptSelectionDecision(
            concept_code=concept.code,
            status="already_complete",
            reasons=[f"Evidence present: {', '.join(satisfied)}"],
            satisfied_by=satisfied,
        )

    # Check triggered_by — if triggers exist, none match → not applicable
    if concept.triggered_by:
        trigger_matched = False
        for trigger in concept.triggered_by:
            # Simple rule: trigger must be a flag in the evidence state
            for flag_val in flags:
                if trigger in flag_val or flag_val in trigger:
                    trigger_matched = True
                    break
            if trigger_matched:
                break

        if not trigger_matched:
            return ConceptSelectionDecision(
                concept_code=concept.code,
                status="not_applicable",
                reasons=[f"No trigger matched: {concept.triggered_by}"],
            )

    return ConceptSelectionDecision(
        concept_code=concept.code,
        status="selected",
    )