from src.feedback.documentation_gap import classify_documentation_gap
from src.feedback.gap_classifier import classify_gaps
from src.feedback.observability_gap import classify_observability_gap
from src.feedback.product_gap import classify_product_gap

from tests.phase5_helpers import make_report, make_resolution


def test_documentation_no_gap_for_missing_required_field():
    gap = classify_documentation_gap(
        make_resolution(
            root_cause_code="request.missing_required_field",
            root_cause_category="request",
        ),
        make_report(),
    )

    assert gap.gap_code == "docs.no_gap"


def test_missing_troubleshooting_for_idempotency_conflict():
    gap = classify_documentation_gap(make_resolution(), make_report())

    assert gap.gap_code == "docs.missing_troubleshooting"
    assert "Create a contract" in gap.affected_sources


def test_ambiguous_field_documentation_classification():
    gap = classify_documentation_gap(
        make_resolution(
            resolution_status="documentation_issue",
            root_cause_code="documentation.ambiguous",
            root_cause_category="documentation",
            affected_sources=["Ingest events"],
        ),
        make_report(),
    )

    assert gap.gap_code == "docs.ambiguous_field"
    assert gap.affected_sources == ["Ingest events"]


def test_generic_error_message_classification_for_missing_field():
    gap = classify_product_gap(
        make_resolution(
            root_cause_code="request.missing_required_field",
            root_cause_category="request",
        ),
        make_report(),
    )

    assert gap.gap_code == "product.error_missing_field_context"
    assert gap.feedback_type == "error_message"


def test_missing_event_matching_visibility_classification():
    gap = classify_observability_gap(
        make_resolution(
            root_cause_code="usage.property_filter_mismatch",
            root_cause_category="usage",
        ),
        make_report(),
    )

    assert gap.gap_code == "product.no_event_matching_visibility"
    assert gap.feedback_type == "observability"


def test_timestamp_outside_period_configuration_visibility_classification():
    gap = classify_observability_gap(
        make_resolution(
            root_cause_code="usage.timestamp_outside_period",
            root_cause_category="usage",
        ),
        make_report(),
    )

    assert gap.gap_code == "product.configuration_visibility_gap"


def test_no_false_product_gap_for_wrong_customer_configuration():
    gap = classify_product_gap(
        make_resolution(
            resolution_status="customer_configuration",
            root_cause_code="contract.wrong_customer",
            root_cause_category="contract",
        ),
        make_report(),
    )

    assert gap.gap_code == "product.no_gap"


def test_classify_gaps_deduplicates_same_gap_code():
    gaps = classify_gaps(make_resolution(), make_report())
    codes = [gap.gap_code for gap in gaps]

    assert codes.count("product.no_request_correlation") == 1
    assert "docs.missing_troubleshooting" in codes
    assert "support.missing_regression_case" in codes
