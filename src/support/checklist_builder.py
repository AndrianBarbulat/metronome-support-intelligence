"""Concept-driven investigation checklist builder."""

from __future__ import annotations

from .checklist_ordering import order_concepts
from .investigation_concepts import InvestigationConcept
from .models import (
    ExtractedTicketSignals,
    InvestigationStep,
    MissingEvidence,
    SupportTicketInput,
    TicketDocumentationSource,
    ValidationFinding,
    InvestigationHypothesis,
)
from .source_capabilities import find_best_source_for_capability


def identify_missing_evidence(
    ticket: SupportTicketInput,
    signals: ExtractedTicketSignals,
) -> list[MissingEvidence]:
    missing: list[MissingEvidence] = []

    if not ticket.http_method:
        missing.append(MissingEvidence(field="http_method", priority="high",
            reason="Needed to confirm the operation being attempted."))
    if not ticket.endpoint_path:
        missing.append(MissingEvidence(field="endpoint_path", priority="high",
            reason="Needed to identify which API resource is involved."))
    if ticket.response_status is None:
        missing.append(MissingEvidence(field="response_status", priority="high",
            reason="Needed to determine the type of failure."))
    if not ticket.response_body:
        missing.append(MissingEvidence(field="response_body", priority="high",
            reason="Needed to understand error details returned by the API."))
    if not ticket.request_body:
        missing.append(MissingEvidence(field="request_body", priority="high",
            reason="Needed to verify which fields were sent."))

    has_request_id = (
        (ticket.request_headers or {}).get("x-request-id")
        or (ticket.response_headers or {}).get("x-request-id")
    )
    if not has_request_id:
        missing.append(MissingEvidence(field="request_id", priority="high",
            reason="Needed to correlate the request with server-side logs."))

    if not signals.timestamps and not ticket.created_at:
        missing.append(MissingEvidence(field="timestamp", priority="medium",
            reason="Helps locate the request in time-based logs."))

    if not ticket.expected_behavior:
        missing.append(MissingEvidence(field="expected_behavior", priority="medium",
            reason="Clarifies what the customer intended to achieve."))
    if not ticket.actual_behavior:
        missing.append(MissingEvidence(field="actual_behavior", priority="medium",
            reason="Clarifies what actually happened vs. what was expected."))

    # Scenario-specific
    if signals.product_area == "contracts":
        if "customer_id" not in signals.request_fields:
            missing.append(MissingEvidence(field="customer_id", priority="critical",
                reason="Required to verify the customer exists."))
        if "starting_at" not in signals.request_fields and signals.status_code == 400:
            missing.append(MissingEvidence(field="starting_at", priority="critical",
                reason="Required field for contract creation."))
        if signals.status_code == 409 and "uniqueness_key" in signals.request_fields:
            missing.append(MissingEvidence(field="previous_request_result", priority="critical",
                reason="The previous request may have already created the contract."))
            missing.append(MissingEvidence(field="is_retry", priority="critical",
                reason="Determines whether this is a retry of the same operation."))

    elif signals.product_area == "usage":
        if "transaction_id" not in signals.request_fields:
            missing.append(MissingEvidence(field="transaction_id", priority="critical",
                reason="Required to verify event ingestion via Event Search."))
        if "event_type" not in signals.request_fields:
            missing.append(MissingEvidence(field="event_type", priority="critical",
                reason="Required to verify event_type matches billable metric."))
        missing.append(MissingEvidence(field="billable_metric_config", priority="high",
            reason="Needed to compare event fields against metric filters and aggregation."))
        missing.append(MissingEvidence(field="event_search_result", priority="high",
            reason="Confirms whether the event was ingested and matched."))
        missing.append(MissingEvidence(field="active_contract", priority="high",
            reason="Usage is only billed with an active contract and rate card."))
        missing.append(MissingEvidence(field="invoice_period", priority="medium",
            reason="The event must fall within the expected billing period."))

    elif signals.product_area == "customers":
        if "name" not in signals.request_fields:
            missing.append(MissingEvidence(field="name", priority="critical",
                reason="Required field for customer creation."))

    return missing


def build_investigation_checklist(
    concepts: list[InvestigationConcept],
    documentation_sources: list[TicketDocumentationSource],
) -> list[InvestigationStep]:
    """Build an ordered checklist from selected concepts, linking documentation sources."""
    ordered = order_concepts(concepts)
    steps: list[InvestigationStep] = []
    order = 10

    for concept in ordered:
        source_url = None
        for cap in concept.source_capabilities:
            best = find_best_source_for_capability(documentation_sources, cap)
            if best:
                source_url = best.source_url
                break

        steps.append(InvestigationStep(
            order=order,
            concept_codes=concept.concept_codes or [concept.code],
            action=concept.action,
            reason=concept.reason,
            expected_evidence=concept.expected_evidence,
            source_url=source_url,
            priority=concept.priority,
            blocking=concept.blocking,
            status="pending",
        ))
        order += 10

    return steps
