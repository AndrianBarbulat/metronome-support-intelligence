from src.support.models import (
    ExtractedTicketSignals,
    SupportTicketInput,
    TicketDocumentationSource,
    ValidationFinding,
)
from src.support.observation_builder import build_observations


def test_observation_builder_emits_stable_request_and_response_codes():
    observations = build_observations(
        SupportTicketInput(
            http_method="POST",
            endpoint_path="/v1/contracts/create",
            request_body={"uniqueness_key": "u"},
            response_status=409,
            response_body={"message": "duplicate"},
        ),
        ExtractedTicketSignals(
            http_method="POST",
            endpoint_path="/v1/contracts/create",
            status_code=409,
            request_fields=["uniqueness_key"],
        ),
        [],
        [],
    )

    codes = {o.observation_code for o in observations}
    assert "request.method.present" in codes
    assert "request.field.uniqueness_key.present" in codes
    assert "response.status.present" in codes
    assert "response.body.present" in codes


def test_observation_builder_emits_absent_response_codes():
    observations = build_observations(SupportTicketInput(), ExtractedTicketSignals(), [], [])

    codes = {o.observation_code for o in observations}
    assert "response.status.absent" in codes
    assert "response.body.absent" in codes


def test_observation_builder_emits_documentation_capability_codes():
    source = TicketDocumentationSource(
        "API idempotency",
        "https://docs.example/idempotency",
        None,
        1,
        source_capabilities=["idempotency"],
        source_purposes=["error_behavior"],
    )

    observations = build_observations(SupportTicketInput(), ExtractedTicketSignals(), [], [source])

    codes = {o.observation_code for o in observations}
    assert "documentation.capability.idempotency" in codes
    assert "documentation.behavior.idempotency" in codes


def test_observation_builder_emits_validation_failures():
    observations = build_observations(
        SupportTicketInput(),
        ExtractedTicketSignals(),
        [ValidationFinding("contract-required-fields", "failed", "missing starting_at")],
        [],
    )

    assert any(o.observation_code == "validation.contract-required-fields.failed" for o in observations)


def test_observation_builder_does_not_claim_forbidden_root_cause():
    observations = build_observations(
        SupportTicketInput(response_status=409, request_body={"uniqueness_key": "u"}),
        ExtractedTicketSignals(status_code=409, request_fields=["uniqueness_key"]),
        [],
        [],
    )

    assert "root_cause.uniqueness_reuse.confirmed" not in {o.observation_code for o in observations}
