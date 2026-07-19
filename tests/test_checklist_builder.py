from src.support.checklist_builder import build_investigation_checklist, identify_missing_evidence
from src.support.investigation_concepts import ALL_CONCEPTS
from src.support.models import ExtractedTicketSignals, SupportTicketInput, TicketDocumentationSource


def concept(code):
    return next(c for c in ALL_CONCEPTS if c.code == code)


def test_checklist_builder_preserves_concept_codes():
    steps = build_investigation_checklist([concept("contract.locate_previous_operation")], [])

    assert steps[0].concept_codes == ["contract.locate_previous_operation"]


def test_checklist_builder_links_best_source_by_capability():
    source = TicketDocumentationSource(
        "API idempotency",
        "https://docs.example/idempotency",
        None,
        10,
        source_capabilities=["idempotency"],
    )

    steps = build_investigation_checklist([concept("contract.locate_previous_operation")], [source])

    assert steps[0].source_url == "https://docs.example/idempotency"


def test_identify_missing_evidence_for_contract_409():
    missing = identify_missing_evidence(
        SupportTicketInput(response_status=409, request_body={"uniqueness_key": "u"}),
        ExtractedTicketSignals(product_area="contracts", status_code=409, request_fields=["uniqueness_key"]),
    )

    fields = {m.field for m in missing}
    assert "previous_request_result" in fields
    assert "is_retry" in fields


def test_identify_missing_evidence_for_usage_includes_billing_config():
    missing = identify_missing_evidence(
        SupportTicketInput(request_body={"transaction_id": "tx"}),
        ExtractedTicketSignals(product_area="usage", request_fields=["transaction_id"]),
    )

    fields = {m.field for m in missing}
    assert "billable_metric_config" in fields
    assert "event_search_result" in fields
