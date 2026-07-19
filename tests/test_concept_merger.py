from src.support.concept_merger import describe_merged_groups, merge_concepts
from src.support.investigation_concepts import ALL_CONCEPTS


def concept(code):
    return next(c for c in ALL_CONCEPTS if c.code == code)


def test_contract_endpoint_concepts_merge_and_preserve_codes():
    merged = merge_concepts([concept("generic.verify_endpoint_and_method"), concept("contract.verify_endpoint")])

    assert len(merged) == 1
    assert merged[0].merge_group == "endpoint_verification"
    assert set(merged[0].concept_codes) == {"generic.verify_endpoint_and_method", "contract.verify_endpoint"}


def test_reproduction_concepts_merge():
    merged = merge_concepts([concept("generic.reproduce_minimal_request"), concept("contract.reproduce_minimal_valid_payload")])

    assert len(merged) == 1
    assert set(merged[0].concept_codes) == {"generic.reproduce_minimal_request", "contract.reproduce_minimal_valid_payload"}


def test_final_state_concepts_merge():
    merged = merge_concepts([concept("generic.verify_final_state"), concept("usage.verify_final_state")])

    assert len(merged) == 1
    assert "usage.verify_final_state" in merged[0].concept_codes


def test_escalation_concepts_merge():
    merged = merge_concepts([concept("generic.prepare_escalation"), concept("contract.prepare_escalation")])

    assert len(merged) == 1
    assert "contract.prepare_escalation" in merged[0].concept_codes


def test_describe_merged_groups_returns_report_metadata():
    merged = merge_concepts([concept("generic.prepare_escalation"), concept("usage.prepare_escalation")])
    groups = describe_merged_groups(merged)

    assert groups[0].merge_group == "engineering_escalation"
    assert "usage.prepare_escalation" in groups[0].concept_codes
