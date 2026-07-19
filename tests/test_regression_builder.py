from src.support.regression_builder import build_regression_case

from tests.phase5_helpers import make_report, make_resolution


def test_contract_regression_case_generation():
    case = build_regression_case(make_resolution(), make_report())

    assert case is not None
    assert case.case_code == "idempotency-previous_operation_succeeded"
    assert case.scenario == "contract_creation"
    assert case.expected_behavior["response_status"] == 409


def test_usage_regression_case_generation():
    case = build_regression_case(
        make_resolution(
            resolution_status="customer_configuration",
            root_cause_code="usage.property_filter_mismatch",
            root_cause_category="usage",
            affected_endpoint="/v1/ingest",
            affected_configuration="cost_usd",
        ),
        make_report(),
    )

    assert case is not None
    assert case.scenario == "usage_ingestion"
    assert case.input["properties"] == {"token_cost_usd": 0.12}
    assert case.expected_behavior["billable_metric_match"] is False


def test_unresolved_resolution_does_not_create_regression_case():
    case = build_regression_case(
        make_resolution(
            resolution_status="unresolved",
            root_cause_code="insufficient_evidence",
            root_cause_category="insufficient_evidence",
        ),
        make_report(),
    )

    assert case is None


def test_documentation_issue_does_not_create_regression_case():
    case = build_regression_case(
        make_resolution(
            resolution_status="documentation_issue",
            root_cause_code="documentation.ambiguous",
            root_cause_category="documentation",
        ),
        make_report(),
    )

    assert case is None


def test_regression_case_preconditions_are_sanitized():
    case = build_regression_case(
        make_resolution(
            resolution_status="customer_configuration",
            root_cause_code="usage.property_filter_mismatch",
            root_cause_category="usage",
            affected_configuration="cost_usd sk_test_secret12345",
        ),
        make_report(),
    )

    assert case is not None
    assert "sk_test_secret12345" not in str(case.preconditions)
    assert "[REDACTED]" in str(case.preconditions)
