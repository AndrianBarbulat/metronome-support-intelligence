from pathlib import Path

import pytest

from src.support.analyzer import analyze_support_ticket
from src.support.checklist_ordering import DependencyCycleError, order_concepts
from src.support.investigation_concepts import InvestigationConcept
from src.support.ticket_parser import load_ticket_from_json


def report(name):
    return analyze_support_ticket(load_ticket_from_json(Path(f"data/examples/{name}.json")), Path("data/metronome_docs.db"), persist=False)


def test_contract_request_capture_orders_first():
    r = report("contract_409")

    assert r.investigation_steps[0].concept_codes == ["generic.capture_request_id", "generic.capture_timestamp"]


def test_escalation_orders_last():
    r = report("usage_accepted_not_billed")

    assert "usage.prepare_escalation" in r.investigation_steps[-1].concept_codes


def test_final_state_orders_before_escalation():
    r = report("usage_accepted_not_billed")
    positions = {code: idx for idx, step in enumerate(r.investigation_steps) for code in step.concept_codes}

    assert positions["usage.verify_final_state"] < positions["usage.prepare_escalation"]


def test_prerequisites_order_before_dependents():
    r = report("contract_409")
    positions = {code: idx for idx, step in enumerate(r.investigation_steps) for code in step.concept_codes}

    assert positions["contract.locate_previous_operation"] < positions["contract.inspect_previous_result"]
    assert positions["contract.compare_existing_pricing"] < positions["contract.decide_key_reuse"]


def test_ordering_detects_dependency_cycles():
    a = InvestigationConcept("a", "a", "a", None, "high", True, prerequisites=["b"])
    b = InvestigationConcept("b", "b", "b", None, "high", True, prerequisites=["a"])

    with pytest.raises(DependencyCycleError):
        order_concepts([a, b])
