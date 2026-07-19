"""Product/API gap classification for confirmed resolutions."""

from __future__ import annotations

from src.support.models import TicketInvestigationReport
from src.support.resolution_models import TicketResolutionInput

from .models import GapClassification


def classify_product_gap(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> GapClassification:
    root = resolution.root_cause_code
    if root.startswith("idempotency."):
        return GapClassification(
            gap_code="product.no_request_correlation",
            feedback_type="api",
            confidence=0.86,
            evidence=["409 uniqueness conflict response does not identify the previous request or resulting resource."],
            affected_sources=[s.page_title for s in investigation.documentation_sources[:3]],
            proposed_action="Expose previous request or resource correlation for uniqueness conflicts.",
        )
    if root in {"request.missing_required_field", "request.invalid_timestamp", "request.invalid_field"}:
        return GapClassification(
            gap_code="product.error_missing_field_context",
            feedback_type="error_message",
            confidence=0.82,
            evidence=["Validation failures are resolved faster when the missing or invalid field is explicit."],
            affected_sources=[],
            proposed_action="Return structured field context in validation errors.",
        )
    if root == "product.defect":
        return GapClassification(
            gap_code="product.defect",
            feedback_type="product",
            confidence=0.95,
            evidence=[resolution.root_cause_summary],
            affected_sources=[],
            proposed_action="Track and fix the confirmed product defect.",
        )
    return GapClassification(
        gap_code="product.no_gap",
        feedback_type="product",
        confidence=0.7,
        evidence=["No deterministic product gap identified."],
        affected_sources=[],
        proposed_action="No product proposal required.",
    )
