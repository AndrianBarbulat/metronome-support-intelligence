from src.feedback.models import GapClassification
from src.feedback.proposal_builder import build_feedback_items

from tests.phase5_helpers import make_resolution


def test_documentation_proposal_generation():
    items = build_feedback_items(
        [
            GapClassification(
                gap_code="docs.missing_troubleshooting",
                feedback_type="documentation",
                confidence=0.9,
                evidence=["Docs lack the support workflow."],
                affected_sources=["API idempotency"],
                proposed_action="Add troubleshooting guidance.",
            )
        ],
        make_resolution(),
    )

    assert items[0].title == "Add troubleshooting guidance for confirmed support workflow"
    assert "sections" in items[0].proposed_change


def test_product_proposal_generation():
    items = build_feedback_items(
        [
            GapClassification(
                gap_code="product.no_event_matching_visibility",
                feedback_type="observability",
                confidence=0.9,
                evidence=["Matching status is not visible."],
                proposed_action="Expose matching outcome.",
            )
        ],
        make_resolution(root_cause_code="usage.property_filter_mismatch", root_cause_category="usage"),
    )

    assert items[0].title == "Expose billable-metric matching outcome for ingested events"
    assert "options" in items[0].proposed_change


def test_proposal_includes_evidence_and_sources():
    items = build_feedback_items(
        [
            GapClassification(
                gap_code="docs.ambiguous_field",
                feedback_type="documentation",
                confidence=0.8,
                evidence=["Timestamp behavior was ambiguous."],
                affected_sources=["Ingest events"],
                proposed_action="Clarify timestamp behavior.",
            )
        ],
        make_resolution(),
    )

    assert items[0].evidence == ["Timestamp behavior was ambiguous."]
    assert items[0].affected_sources == ["Ingest events"]


def test_draft_proposal_requires_review():
    items = build_feedback_items(
        [
            GapClassification(
                gap_code="support.missing_regression_case",
                feedback_type="regression",
                confidence=0.9,
                evidence=["Confirmed outcome should become a test."],
                proposed_action="Review generated regression case.",
            )
        ],
        make_resolution(),
    )

    assert items[0].status == "needs_review"


def test_high_confidence_proposal_gets_high_priority():
    items = build_feedback_items(
        [
            GapClassification(
                gap_code="product.defect",
                feedback_type="product",
                confidence=0.95,
                evidence=["Defect reproduced."],
                proposed_action="Track product defect.",
            )
        ],
        make_resolution(root_cause_code="product.defect", root_cause_category="product"),
    )

    assert items[0].priority == "high"
