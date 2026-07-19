"""Build evidence-linked observations with stable observation codes."""

from __future__ import annotations

from .models import (
    ExtractedTicketSignals,
    InvestigationObservation,
    SupportTicketInput,
    TicketDocumentationSource,
    ValidationFinding,
)

def build_observations(
    ticket: SupportTicketInput,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    documentation_sources: list[TicketDocumentationSource],
) -> list[InvestigationObservation]:
    obs: list[InvestigationObservation] = []

    # -- Request observations --
    if signals.http_method:
        obs.append(InvestigationObservation(
            statement=f"Request method is {signals.http_method}.",
            evidence_type="ticket_field",
            evidence_reference="http_method",
            observation_code="request.method.present",
        ))
    if signals.endpoint_path:
        obs.append(InvestigationObservation(
            statement=f"Endpoint is {signals.endpoint_path}.",
            evidence_type="ticket_field",
            evidence_reference="endpoint_path",
            observation_code="request.endpoint.present",
        ))

    # Request headers
    if ticket.request_headers:
        auth = ticket.request_headers.get("Authorization", ticket.request_headers.get("authorization"))
        if auth and auth == "[REDACTED]":
            obs.append(InvestigationObservation(
                statement="Authorization header was present and redacted.",
                evidence_type="request",
                evidence_reference="request_headers.Authorization",
                observation_code="request.auth.redacted",
            ))

    # Request fields
    if ticket.request_body is not None:
        obs.append(InvestigationObservation(
            statement="Request body was provided.",
            evidence_type="request",
            evidence_reference="request_body",
            observation_code="request.body.present",
        ))
    for f in signals.request_fields:
        obs.append(InvestigationObservation(
            statement=f"Request contains field: {f}.",
            evidence_type="request",
            evidence_reference=f"request_body.{f}",
            observation_code=f"request.field.{f}.present",
        ))

    # -- Response observations --
    if signals.status_code is not None:
        obs.append(InvestigationObservation(
            statement=f"Response status is {signals.status_code}.",
            evidence_type="response",
            evidence_reference="response_status",
            observation_code="response.status.present",
        ))
    else:
        obs.append(InvestigationObservation(
            statement="Response status was not provided.",
            evidence_type="ticket_field",
            evidence_reference="response_status",
            observation_code="response.status.absent",
        ))

    if ticket.response_body is not None:
        obs.append(InvestigationObservation(
            statement="Response body was provided.",
            evidence_type="response",
            evidence_reference="response_body",
            observation_code="response.body.present",
        ))
        if isinstance(ticket.response_body, dict) and "message" in ticket.response_body:
            m = str(ticket.response_body["message"])[:200]
            obs.append(InvestigationObservation(
                statement=f"Response body message: {m}.",
                evidence_type="response",
                evidence_reference="response_body.message",
                observation_code="response.message.present",
            ))
    else:
        obs.append(InvestigationObservation(
            statement="Response body was not provided.",
            evidence_type="ticket_field",
            evidence_reference="response_body",
            observation_code="response.body.absent",
        ))

    # -- Behaviour observations --
    if ticket.expected_behavior:
        obs.append(InvestigationObservation(
            statement=f"Expected behavior: {ticket.expected_behavior}.",
            evidence_type="ticket_field",
            evidence_reference="expected_behavior",
            observation_code="behavior.expected.present",
        ))
    if ticket.actual_behavior:
        obs.append(InvestigationObservation(
            statement=f"Actual behavior: {ticket.actual_behavior}.",
            evidence_type="ticket_field",
            evidence_reference="actual_behavior",
            observation_code="behavior.actual.present",
        ))

    # -- Validation findings observations --
    for f in findings:
        if f.status == "failed":
            obs.append(InvestigationObservation(
                statement=f"Validation failure: {f.statement}",
                evidence_type="validation",
                evidence_reference=f.rule_id,
                observation_code=f"validation.{f.rule_id}.failed",
            ))

    # -- Documentation observations --
    if documentation_sources:
        primary = [s for s in documentation_sources if s.usage_type == "primary"]
        if primary:
            obs.append(InvestigationObservation(
                statement=f"Primary documentation: {', '.join(s.page_title for s in primary[:3])}.",
                evidence_type="documentation",
                evidence_reference="search_results.primary",
                observation_code="documentation.primary.present",
            ))
        for source in documentation_sources:
            for capability in source.source_capabilities:
                obs.append(InvestigationObservation(
                    statement=f"Documentation capability retrieved: {capability}.",
                    evidence_type="documentation",
                    evidence_reference=source.source_url,
                    observation_code=f"documentation.capability.{capability}",
                ))
        if any("idempotency" in s.source_capabilities for s in documentation_sources):
            obs.append(InvestigationObservation(
                statement="Documentation describes idempotency or uniqueness-key behavior.",
                evidence_type="documentation",
                evidence_reference="search_results.idempotency",
                observation_code="documentation.behavior.idempotency",
            ))

    # Specialized observations from signals
    if signals.status_code == 409 and "uniqueness_key" in signals.request_fields:
        obs.append(InvestigationObservation(
            statement="Status 409 with uniqueness_key present suggests a possible idempotency conflict.",
            evidence_type="analysis",
            evidence_reference="signal.correlation.409_uniqueness",
            observation_code="analysis.409.uniqueness_conflict",
        ))

    if signals.status_code == 200 and signals.product_area == "usage":
        obs.append(InvestigationObservation(
            statement="Ingestion succeeded (200) but downstream billing may not have occurred.",
            evidence_type="analysis",
            evidence_reference="signal.correlation.200_usage",
            observation_code="analysis.200.usage_ingestion",
        ))

    return obs
