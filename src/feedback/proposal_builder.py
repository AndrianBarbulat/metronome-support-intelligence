"""Build deterministic draft feedback proposals from gap classifications."""

from __future__ import annotations

from src.support.resolution_models import TicketResolutionInput

from .models import FeedbackItem, GapClassification


def build_feedback_items(
    classifications: list[GapClassification],
    resolution: TicketResolutionInput,
    resolution_id: int | None = None,
) -> list[FeedbackItem]:
    items: list[FeedbackItem] = []
    for classification in classifications:
        items.append(_build_one(classification, resolution, resolution_id or 0))
    return items


def _build_one(
    classification: GapClassification,
    resolution: TicketResolutionInput,
    resolution_id: int,
) -> FeedbackItem:
    gap = classification.gap_code
    title = _title_for_gap(gap, resolution)
    proposed_change = _proposed_change_for_gap(gap, classification, resolution)
    priority = "high" if classification.confidence >= 0.88 else "medium"
    return FeedbackItem(
        id=None,
        resolution_id=resolution_id,
        feedback_type=classification.feedback_type,
        gap_code=gap,
        title=title,
        summary=classification.proposed_action,
        evidence=classification.evidence,
        affected_sources=classification.affected_sources,
        proposed_change=proposed_change,
        priority=priority,
        status="needs_review",
    )


def _title_for_gap(gap_code: str, resolution: TicketResolutionInput) -> str:
    titles = {
        "docs.missing_troubleshooting": "Add troubleshooting guidance for confirmed support workflow",
        "docs.ambiguous_field": "Clarify ambiguous documented field behavior",
        "docs.missing_workflow": "Add missing documented workflow",
        "docs.incorrect_behavior": "Correct documented behavior",
        "product.no_request_correlation": "Expose request correlation for idempotency conflicts",
        "product.error_missing_field_context": "Return structured validation field context",
        "product.no_event_matching_visibility": "Expose billable-metric matching outcome for ingested events",
        "product.configuration_visibility_gap": "Expose billing-period and configuration visibility for usage events",
        "product.defect": "Track confirmed product defect",
        "support.missing_regression_case": "Review generated regression case",
    }
    return titles.get(gap_code, resolution.root_cause_summary)


def _proposed_change_for_gap(
    gap_code: str,
    classification: GapClassification,
    resolution: TicketResolutionInput,
) -> dict[str, object]:
    if gap_code == "docs.missing_troubleshooting" and resolution.root_cause_code.startswith("idempotency."):
        return {
            "location": "API idempotency > Troubleshooting",
            "sections": [
                "How to determine whether the original request succeeded",
                "How to retrieve the existing contract",
                "When to reuse or replace a uniqueness key",
                "Evidence to include in an escalation",
            ],
        }
    if gap_code == "docs.missing_troubleshooting" and resolution.root_cause_code.startswith("usage."):
        return {
            "location": "Usage ingestion > Troubleshooting",
            "sections": [
                "How to inspect Event Search",
                "How to verify customer matching",
                "How to compare billable metric filters",
                "How to verify invoice-period attribution",
            ],
        }
    if gap_code == "product.no_event_matching_visibility":
        return {
            "options": [
                "Return matching metadata asynchronously",
                "Expose matching status through Event Search",
                "Add a correlation identifier to ingestion responses",
            ]
        }
    if gap_code == "product.no_request_correlation":
        return {
            "options": [
                "Return previous request ID in uniqueness conflicts",
                "Return resulting resource ID when available",
                "Expose lookup guidance in error metadata",
            ]
        }
    if gap_code == "support.missing_regression_case":
        return {"action": "Review generated regression candidate and decide automation status."}
    return {"action": classification.proposed_action}
