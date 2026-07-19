"""Documentation-gap classification for confirmed resolutions."""

from __future__ import annotations

from src.support.models import TicketInvestigationReport
from src.support.resolution_models import TicketResolutionInput

from .models import GapClassification


def classify_documentation_gap(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> GapClassification:
    root = resolution.root_cause_code
    sources = [s.page_title for s in investigation.documentation_sources]

    if root in {"request.missing_required_field", "request.invalid_timestamp"}:
        return GapClassification(
            gap_code="docs.no_gap",
            feedback_type="documentation",
            confidence=0.85,
            evidence=["API reference includes contract creation fields."],
            affected_sources=_matching_sources(sources, ["Create a contract"]),
            proposed_action="No documentation proposal required.",
        )
    if root.startswith("idempotency."):
        return GapClassification(
            gap_code="docs.missing_troubleshooting",
            feedback_type="documentation",
            confidence=0.9,
            evidence=["Existing docs describe uniqueness keys but not the support workflow for unknown previous-operation results."],
            affected_sources=_matching_sources(sources, ["Create a contract", "API idempotency"]),
            proposed_action="Add troubleshooting guidance for contract uniqueness conflicts.",
        )
    if root.startswith("usage."):
        return GapClassification(
            gap_code="docs.missing_troubleshooting",
            feedback_type="documentation",
            confidence=0.88,
            evidence=["Usage docs cover ingestion and metrics but not a concise accepted-but-not-billed diagnostic workflow."],
            affected_sources=_matching_sources(sources, ["Ingest events", "Search events", "billable metric"]),
            proposed_action="Add accepted-but-not-billed troubleshooting guidance.",
        )
    if root == "documentation.ambiguous":
        return GapClassification(
            gap_code="docs.ambiguous_field",
            feedback_type="documentation",
            confidence=0.9,
            evidence=[resolution.root_cause_summary],
            affected_sources=resolution.affected_sources,
            proposed_action="Clarify the ambiguous field behavior.",
        )
    if root.startswith("documentation."):
        return GapClassification(
            gap_code="docs.incorrect_behavior" if root == "documentation.incorrect" else "docs.missing_workflow",
            feedback_type="documentation",
            confidence=0.9,
            evidence=[resolution.root_cause_summary],
            affected_sources=resolution.affected_sources,
            proposed_action="Update the affected documentation.",
        )
    return GapClassification(
        gap_code="docs.no_gap",
        feedback_type="documentation",
        confidence=0.7,
        evidence=["No deterministic documentation gap identified."],
        affected_sources=[],
        proposed_action="No documentation proposal required.",
    )


def _matching_sources(sources: list[str], terms: list[str]) -> list[str]:
    matched: list[str] = []
    for source in sources:
        if any(term.lower() in source.lower() for term in terms):
            matched.append(source)
    return list(dict.fromkeys(matched))
