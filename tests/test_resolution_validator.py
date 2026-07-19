from src.support.resolution_validator import validate_resolution

from tests.phase5_helpers import make_report, make_resolution


def test_valid_confirmed_resolution():
    result = validate_resolution(make_resolution(), make_report())

    assert result.valid
    assert "root_cause_code=idempotency.previous_operation_succeeded" in result.new_confirmed_facts


def test_missing_root_cause_summary_is_invalid():
    result = validate_resolution(make_resolution(root_cause_summary=""), make_report())

    assert not result.valid
    assert "confirmed resolutions require root_cause_summary" in result.errors


def test_missing_verification_steps_is_invalid():
    result = validate_resolution(make_resolution(verification_steps=[]), make_report())

    assert not result.valid
    assert "verification_steps are required" in result.errors


def test_missing_verification_results_is_invalid():
    result = validate_resolution(make_resolution(verification_results=[]), make_report())

    assert not result.valid
    assert "verification_results are required" in result.errors


def test_invalid_confirmation_timestamp_is_invalid():
    result = validate_resolution(make_resolution(confirmed_at="July 19"), make_report())

    assert not result.valid
    assert "confirmed_at must be a valid ISO-8601 timestamp" in result.errors


def test_analysis_belongs_to_another_ticket_is_invalid():
    result = validate_resolution(make_resolution(ticket_id=2), make_report(ticket_id=1))

    assert not result.valid
    assert "analysis does not belong to the ticket" in result.errors


def test_unresolved_case_cannot_claim_confirmed_root_cause():
    result = validate_resolution(make_resolution(resolution_status="unresolved"), make_report())

    assert not result.valid
    assert "unresolved cases cannot claim a confirmed root cause" in result.errors


def test_cannot_reproduce_case_must_use_cannot_reproduce_code():
    result = validate_resolution(make_resolution(resolution_status="cannot_reproduce"), make_report())

    assert not result.valid
    assert "cannot_reproduce cases must not claim a confirmed root cause" in result.errors


def test_cannot_reproduce_case_without_confirmed_root_is_valid():
    result = validate_resolution(
        make_resolution(
            resolution_status="cannot_reproduce",
            root_cause_code="cannot_reproduce",
            root_cause_category="cannot_reproduce",
        ),
        make_report(),
    )

    assert result.valid


def test_product_defect_requires_reproduction_or_escalation_evidence():
    result = validate_resolution(
        make_resolution(
            resolution_status="product_defect",
            root_cause_code="product.defect",
            root_cause_category="product",
            resolution_steps=["Checked the ticket."],
            verification_steps=["Verified customer impact."],
            verification_results=["Impact confirmed."],
        ),
        make_report(),
    )

    assert not result.valid
    assert "product_defect resolutions require reproduction or escalation evidence" in result.errors


def test_documentation_issue_without_source_warns():
    result = validate_resolution(
        make_resolution(
            resolution_status="documentation_issue",
            root_cause_code="documentation.ambiguous",
            root_cause_category="documentation",
            affected_sources=[],
        ),
        make_report(),
    )

    assert result.valid
    assert "documentation_issue should identify affected documentation sources" in result.warnings


def test_unredacted_secret_is_invalid():
    result = validate_resolution(
        make_resolution(root_cause_details="The customer pasted sk_test_secret12345."),
        make_report(),
    )

    assert not result.valid
    assert "resolution contains unredacted secrets" in result.errors
