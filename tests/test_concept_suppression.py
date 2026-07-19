from src.support.concept_registry import InvestigationConceptRegistry
from src.support.concept_suppression import evaluate_evidence_state, suppress_redundant_concepts
from src.support.investigation_concepts import ALL_CONCEPTS
from src.support.models import ExtractedTicketSignals, SupportTicketInput, ValidationFinding


def concept(code):
    return next(c for c in ALL_CONCEPTS if c.code == code)


def test_complete_request_suppresses_request_capture_concept():
    selected, decisions = suppress_redundant_concepts(
        [concept("generic.capture_complete_request")],
        SupportTicketInput(http_method="POST", endpoint_path="/v1/ingest", request_body={"x": 1}),
        ExtractedTicketSignals(http_method="POST", endpoint_path="/v1/ingest"),
        [],
    )

    assert selected == []
    assert decisions[0].status == "already_complete"


def test_complete_response_suppresses_response_capture_concept():
    selected, decisions = suppress_redundant_concepts(
        [concept("generic.capture_complete_response")],
        SupportTicketInput(response_status=200, response_body={"status": "accepted"}),
        ExtractedTicketSignals(status_code=200),
        [],
    )

    assert selected == []
    assert decisions[0].status == "already_complete"


def test_application_response_suppresses_authentication_check():
    selected, decisions = suppress_redundant_concepts(
        [concept("generic.verify_authentication")],
        SupportTicketInput(response_status=409, response_body={"message": "conflict"}),
        ExtractedTicketSignals(status_code=409),
        [],
    )

    assert selected == []
    assert decisions[0].status == "suppressed"


def test_valid_starting_at_suppresses_timestamp_validation():
    selected, decisions = suppress_redundant_concepts(
        [concept("contract.validate_starting_at")],
        SupportTicketInput(
            request_body={"starting_at": "2026-08-01T00:00:00Z"},
            response_status=409,
        ),
        ExtractedTicketSignals(product_area="contracts", status_code=409, request_fields=["starting_at"]),
        [],
    )

    assert selected == []
    assert decisions[0].status == "suppressed"


def test_evidence_state_includes_finding_flags():
    flags = evaluate_evidence_state(
        SupportTicketInput(),
        ExtractedTicketSignals(),
        [ValidationFinding("contract-required-fields", "failed", "missing")],
    )

    assert "finding.contract-required-fields.failed" in flags
