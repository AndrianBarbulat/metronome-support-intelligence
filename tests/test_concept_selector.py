from pathlib import Path

from src.support.analyzer import analyze_support_ticket
from src.support.concept_registry import InvestigationConceptRegistry
from src.support.ticket_parser import load_ticket_from_json

DB = Path("data/metronome_docs.db")


def report(name):
    return analyze_support_ticket(load_ticket_from_json(Path(f"data/examples/{name}.json")), DB, persist=False)


def codes(report):
    return {code for step in report.investigation_steps for code in step.concept_codes}


def decisions(report, status):
    return {d.concept_code for d in report.concept_decisions if d.status == status}


def test_contract_409_suppresses_completed_payload_and_response_capture():
    r = report("contract_409")

    assert "generic.capture_complete_request" in decisions(r, "already_complete")
    assert "generic.capture_complete_response" in decisions(r, "already_complete")
    assert "generic.capture_complete_request" not in codes(r)


def test_contract_409_selects_uniqueness_workflow_only():
    selected = codes(report("contract_409"))

    assert "contract.locate_previous_operation" in selected
    assert "contract.validate_starting_at" not in selected
    assert "generic.verify_authentication" not in selected


def test_contract_409_escalation_is_last():
    r = report("contract_409")

    assert "contract.prepare_escalation" in r.investigation_steps[-1].concept_codes


def test_accepted_not_billed_selects_all_matching_concepts():
    selected = codes(report("usage_accepted_not_billed"))

    for code in [
        "usage.search_event",
        "usage.verify_customer_match",
        "usage.verify_billable_metric_match",
        "usage.compare_event_type",
        "usage.compare_property_filters",
        "usage.compare_aggregation_key",
        "usage.verify_active_contract",
        "usage.verify_active_rate_card",
        "usage.verify_invoice_period",
        "usage.verify_final_state",
    ]:
        assert code in selected


def test_duplicate_transaction_does_not_activate_invoice_zero_workflow():
    selected = codes(report("usage_duplicate_transaction"))

    assert "usage.locate_original_transaction" in selected
    assert "usage.verify_invoice_period" not in selected
    assert "usage.verify_final_state" not in selected


def test_vague_ticket_selects_only_generic_evidence_gathering():
    selected = codes(report("vague_ticket"))

    assert "generic.capture_complete_request" in selected
    assert "generic.prepare_escalation" not in selected
    assert all(not code.startswith(("contract.", "usage.", "customer.")) for code in selected)


def test_auth_failure_selects_authentication_without_contract_validation():
    selected = codes(report("auth_failure"))

    assert "generic.verify_authentication" in selected
    assert "contract.verify_customer_reference" not in selected


def test_registry_select_returns_merged_concepts_for_legacy_call():
    registry = InvestigationConceptRegistry()
    r = report("contract_409")

    assert registry.get("contract.locate_previous_operation") is not None
    assert "contract.locate_previous_operation" in codes(r)
