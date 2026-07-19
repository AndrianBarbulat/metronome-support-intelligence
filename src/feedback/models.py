"""Feedback models and stable workflow states."""

from __future__ import annotations

from dataclasses import dataclass, field


FEEDBACK_TYPES = {
    "documentation",
    "product",
    "api",
    "validation",
    "error_message",
    "observability",
    "support_process",
    "regression",
}

FEEDBACK_STATUSES = {
    "draft",
    "needs_review",
    "approved",
    "rejected",
    "planned",
    "implemented",
    "verified",
    "closed",
}

FEEDBACK_DECISIONS = {
    "approve",
    "reject",
    "request_changes",
    "mark_planned",
    "mark_implemented",
    "mark_verified",
    "close",
}

GAP_CODES = {
    "docs.no_gap",
    "docs.missing_workflow",
    "docs.missing_troubleshooting",
    "docs.missing_error_explanation",
    "docs.ambiguous_field",
    "docs.missing_example",
    "docs.outdated_example",
    "docs.incorrect_behavior",
    "docs.cross_article_inconsistency",
    "product.no_gap",
    "product.validation_missing",
    "product.validation_inconsistent",
    "product.error_too_generic",
    "product.error_missing_field_context",
    "product.no_request_correlation",
    "product.no_event_matching_visibility",
    "product.configuration_visibility_gap",
    "product.defect",
    "support.no_gap",
    "support.missing_runbook",
    "support.missing_escalation_template",
    "support.missing_regression_case",
    "support.missing_observability_step",
}


@dataclass
class GapClassification:
    gap_code: str
    feedback_type: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    affected_sources: list[str] = field(default_factory=list)
    proposed_action: str = ""


@dataclass
class FeedbackItem:
    id: int | None
    resolution_id: int
    feedback_type: str
    gap_code: str
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    affected_sources: list[str] = field(default_factory=list)
    proposed_change: dict[str, object] = field(default_factory=dict)
    priority: str = "medium"
    status: str = "needs_review"
    owner: str | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None
