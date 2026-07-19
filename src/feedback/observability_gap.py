"""Observability gap classification for confirmed resolutions."""

from __future__ import annotations

from src.support.models import TicketInvestigationReport
from src.support.resolution_models import TicketResolutionInput

from .models import GapClassification


def classify_observability_gap(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> GapClassification:
    root = resolution.root_cause_code
    if root in {
        "usage.customer_not_matched",
        "usage.event_type_mismatch",
        "usage.property_filter_mismatch",
        "usage.aggregation_key_missing",
        "usage.aggregation_value_invalid",
    }:
        return GapClassification(
            gap_code="product.no_event_matching_visibility",
            feedback_type="observability",
            confidence=0.9,
            evidence=["Ingestion can succeed while customer, metric, filter, or aggregation matching fails downstream."],
            affected_sources=[s.page_title for s in investigation.documentation_sources[:3]],
            proposed_action="Expose event matching outcome through Event Search or ingestion correlation.",
        )
    if root == "usage.timestamp_outside_period":
        return GapClassification(
            gap_code="product.configuration_visibility_gap",
            feedback_type="observability",
            confidence=0.82,
            evidence=["Invoice-period attribution requires correlating event timestamp, grace period, and invoice state."],
            affected_sources=[s.page_title for s in investigation.documentation_sources[:3]],
            proposed_action="Expose billing-period attribution and grace-period status for ingested events.",
        )
    if root.startswith("idempotency."):
        return GapClassification(
            gap_code="product.no_request_correlation",
            feedback_type="observability",
            confidence=0.82,
            evidence=["Previous operation correlation is required to resolve uniqueness conflicts."],
            affected_sources=[],
            proposed_action="Expose previous operation correlation for idempotency conflicts.",
        )
    return GapClassification(
        gap_code="support.no_gap",
        feedback_type="support_process",
        confidence=0.7,
        evidence=["No deterministic observability gap identified."],
        affected_sources=[],
        proposed_action="No observability proposal required.",
    )
