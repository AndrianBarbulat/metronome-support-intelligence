"""Service for confirming ticket resolutions and generating feedback artifacts."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from src.database.repository import DocumentationRepository
from src.feedback.gap_classifier import classify_gaps
from src.feedback.proposal_builder import build_feedback_items

from .models import (
    ConceptSelectionDecision,
    ExtractedTicketSignals,
    InvestigationHypothesis,
    MergedConceptGroup,
    InvestigationObservation,
    InvestigationStep,
    MissingEvidence,
    SupportTicketInput,
    TicketDocumentationSource,
    TicketInvestigationReport,
    ValidationFinding,
)
from .regression_builder import build_regression_case
from .resolution_comparator import compare_hypotheses_to_resolution
from .resolution_models import ConfirmedResolution, TicketResolutionInput
from .resolution_validator import ResolutionValidationResult, validate_resolution
from .sanitizer import sanitize_ticket


class ResolutionServiceError(Exception):
    """Raised when a resolution cannot be confirmed."""

    def __init__(self, message: str, validation: ResolutionValidationResult | None = None) -> None:
        super().__init__(message)
        self.validation = validation


def confirm_ticket_resolution(
    resolution: TicketResolutionInput,
    database_path: Path,
) -> ConfirmedResolution:
    repo = DocumentationRepository(database_path)
    try:
        repo.initialize_schema()
        ticket_row, analysis_row = repo.get_ticket_analysis_pair(
            resolution.ticket_id, resolution.analysis_id,
        )
        if ticket_row is None:
            raise ResolutionServiceError(f"Ticket not found: {resolution.ticket_id}")
        if analysis_row is None:
            raise ResolutionServiceError(f"Analysis not found: {resolution.analysis_id}")
        if analysis_row["ticket_id"] != resolution.ticket_id:
            report = _report_from_analysis_row(analysis_row, repo)
            report.ticket_id = analysis_row["ticket_id"]
            validation = validate_resolution(resolution, report)
            raise ResolutionServiceError("analysis does not belong to the ticket", validation)

        report = _report_from_analysis_row(analysis_row, repo)
        report.ticket_id = resolution.ticket_id
        validation = validate_resolution(resolution, report)
        if not validation.valid:
            raise ResolutionServiceError("resolution validation failed", validation)

        sanitized_resolution = _sanitize_resolution(resolution)
        outcomes = compare_hypotheses_to_resolution(report.hypotheses, sanitized_resolution)
        regression = build_regression_case(sanitized_resolution, report)
        classifications = classify_gaps(sanitized_resolution, report)
        feedback_items = build_feedback_items(classifications, sanitized_resolution)

        resolution_id, _regression_id, _feedback_ids = repo.persist_resolution_bundle(
            sanitized_resolution,
            outcomes,
            regression,
            feedback_items,
        )
        return ConfirmedResolution(
            id=resolution_id,
            ticket_id=sanitized_resolution.ticket_id,
            analysis_id=sanitized_resolution.analysis_id,
            resolution_status=sanitized_resolution.resolution_status,
            root_cause_code=sanitized_resolution.root_cause_code,
            root_cause_category=sanitized_resolution.root_cause_category,
            root_cause_summary=sanitized_resolution.root_cause_summary,
            root_cause_details=sanitized_resolution.root_cause_details,
            resolution_summary=sanitized_resolution.resolution_summary,
            resolution_steps=sanitized_resolution.resolution_steps,
            verification_steps=sanitized_resolution.verification_steps,
            verification_results=sanitized_resolution.verification_results,
            confirmed_by=sanitized_resolution.confirmed_by,
            confirmed_at=sanitized_resolution.confirmed_at,
            hypothesis_outcomes=outcomes,
            regression_case=regression,
            feedback_items=feedback_items,
        )
    finally:
        repo.close()


def load_resolution_from_json(path: Path) -> TicketResolutionInput:
    data = json.loads(path.read_text(encoding="utf-8"))
    return TicketResolutionInput(
        ticket_id=int(data.get("ticket_id", 0)),
        analysis_id=int(data.get("analysis_id", 0)),
        resolution_status=data.get("resolution_status", ""),
        root_cause_code=data.get("root_cause_code", ""),
        root_cause_category=data.get("root_cause_category", ""),
        root_cause_summary=data.get("root_cause_summary", ""),
        root_cause_details=data.get("root_cause_details", ""),
        resolution_summary=data.get("resolution_summary", ""),
        resolution_steps=list(data.get("resolution_steps", [])),
        verification_steps=list(data.get("verification_steps", [])),
        verification_results=list(data.get("verification_results", [])),
        confirmed_by=data.get("confirmed_by", ""),
        confirmed_at=data.get("confirmed_at", ""),
        affected_component=data.get("affected_component"),
        affected_endpoint=data.get("affected_endpoint"),
        affected_configuration=data.get("affected_configuration"),
        request_ids=list(data.get("request_ids", [])),
        transaction_ids=list(data.get("transaction_ids", [])),
        customer_ids=list(data.get("customer_ids", [])),
        contract_ids=list(data.get("contract_ids", [])),
        billable_metric_ids=list(data.get("billable_metric_ids", [])),
        invoice_ids=list(data.get("invoice_ids", [])),
        rate_card_ids=list(data.get("rate_card_ids", [])),
        affected_sources=list(data.get("affected_sources", [])),
        internal_notes=data.get("internal_notes"),
    )


def _sanitize_resolution(resolution: TicketResolutionInput) -> TicketResolutionInput:
    text_ticket = SupportTicketInput(
        subject=resolution.root_cause_summary,
        customer_message=resolution.root_cause_details,
        expected_behavior=resolution.resolution_summary,
        actual_behavior="\n".join(
            resolution.resolution_steps + resolution.verification_steps + resolution.verification_results
        ),
        logs=resolution.internal_notes or "",
    )
    sanitized = sanitize_ticket(text_ticket).sanitized_ticket
    return TicketResolutionInput(
        **{
            **resolution.__dict__,
            "root_cause_summary": sanitized.subject,
            "root_cause_details": sanitized.customer_message,
            "resolution_summary": sanitized.expected_behavior or "",
            "internal_notes": sanitized.logs,
            "resolution_steps": _split_sanitized_list(sanitized.actual_behavior, len(resolution.resolution_steps), 0),
            "verification_steps": _split_sanitized_list(
                sanitized.actual_behavior,
                len(resolution.verification_steps),
                len(resolution.resolution_steps),
            ),
            "verification_results": _split_sanitized_list(
                sanitized.actual_behavior,
                len(resolution.verification_results),
                len(resolution.resolution_steps) + len(resolution.verification_steps),
            ),
        }
    )


def _split_sanitized_list(value: str | None, length: int, offset: int) -> list[str]:
    original = (value or "").splitlines()
    return original[offset:offset + length]


def _report_from_analysis_row(row, repo: DocumentationRepository) -> TicketInvestigationReport:
    signals = _from_dict(ExtractedTicketSignals, json.loads(row["signals_json"]))
    observations = [_from_dict(InvestigationObservation, item) for item in json.loads(row["observations_json"])]
    findings = [_from_dict(ValidationFinding, item) for item in json.loads(row["validation_findings_json"])]
    hypotheses = [_from_dict(InvestigationHypothesis, item) for item in json.loads(row["hypotheses_json"])]
    missing = [_from_dict(MissingEvidence, item) for item in json.loads(row["missing_evidence_json"])]
    steps = [_from_dict(InvestigationStep, item) for item in json.loads(row["investigation_steps_json"])]
    decisions = [
        _from_dict(ConceptSelectionDecision, item)
        for item in json.loads(row["concept_decisions_json"] if "concept_decisions_json" in row.keys() else "[]")
    ]
    merged_groups = [
        _from_dict(MergedConceptGroup, item)
        for item in json.loads(row["merged_concept_groups_json"] if "merged_concept_groups_json" in row.keys() else "[]")
    ]
    sources = _sources_for_analysis(row["id"], repo)
    return TicketInvestigationReport(
        ticket_id=row["ticket_id"],
        summary=row["summary"],
        sanitized=True,
        signals=signals,
        observations=observations,
        validation_findings=findings,
        hypotheses=hypotheses,
        missing_evidence=missing,
        investigation_steps=steps,
        documentation_sources=sources,
        concept_decisions=decisions,
        merged_concept_groups=merged_groups,
        retrieval_query=row["retrieval_query"],
        retrieval_confidence=row["retrieval_confidence"],
    )


def _sources_for_analysis(analysis_id: int, repo: DocumentationRepository) -> list[TicketDocumentationSource]:
    rows = repo._get_conn().execute(
        """SELECT * FROM support_ticket_document_links
           WHERE analysis_id = ?
           ORDER BY id""",
        (analysis_id,),
    ).fetchall()
    sources: list[TicketDocumentationSource] = []
    for row in rows:
        sources.append(TicketDocumentationSource(
            page_title=row["page_title"],
            source_url=row["source_url"],
            heading=row["heading"],
            relevance_score=row["relevance_score"],
            matched_tokens=json.loads(row["matched_tokens_json"]),
            ranking_reasons=json.loads(row["ranking_reasons_json"]),
            usage_type=row["usage_type"],
            source_capabilities=json.loads(row["source_capabilities_json"] if "source_capabilities_json" in row.keys() else "[]"),
            source_purposes=json.loads(row["source_purposes_json"] if "source_purposes_json" in row.keys() else "[]"),
        ))
    return sources


def _from_dict(cls, data: dict):
    names = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in names})
