"""Classify confirmed resolutions into structured feedback gaps."""

from __future__ import annotations

from src.support.models import TicketInvestigationReport
from src.support.resolution_models import TicketResolutionInput

from .documentation_gap import classify_documentation_gap
from .models import GapClassification
from .observability_gap import classify_observability_gap
from .product_gap import classify_product_gap


def classify_gaps(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> list[GapClassification]:
    classifications = [
        classify_documentation_gap(resolution, investigation),
        classify_product_gap(resolution, investigation),
        classify_observability_gap(resolution, investigation),
        _support_gap(resolution),
    ]
    selected: dict[str, GapClassification] = {}
    for item in classifications:
        if item.gap_code.endswith(".no_gap"):
            continue
        existing = selected.get(item.gap_code)
        if existing is None or item.confidence > existing.confidence:
            selected[item.gap_code] = item
    return list(selected.values())


def _support_gap(resolution: TicketResolutionInput) -> GapClassification:
    if resolution.resolution_status in {"confirmed", "customer_configuration", "product_defect"}:
        return GapClassification(
            gap_code="support.missing_regression_case",
            feedback_type="regression",
            confidence=0.9,
            evidence=["Confirmed outcome should become a reusable regression case."],
            affected_sources=[],
            proposed_action="Review and automate the generated regression case when feasible.",
        )
    return GapClassification(
        gap_code="support.no_gap",
        feedback_type="support_process",
        confidence=0.7,
        evidence=[],
        affected_sources=[],
        proposed_action="No support-process proposal required.",
    )
