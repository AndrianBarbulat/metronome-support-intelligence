from src.support.models import InvestigationHypothesis
from src.support.resolution_comparator import compare_hypotheses_to_resolution

from tests.phase5_helpers import make_resolution


def test_specific_hypothesis_is_confirmed():
    outcomes = compare_hypotheses_to_resolution(
        [InvestigationHypothesis("Event type mismatch", "", hypothesis_code="usage.event_type_mismatch")],
        make_resolution(root_cause_code="usage.event_type_mismatch", root_cause_category="usage"),
    )

    assert outcomes[0].outcome == "confirmed"


def test_broad_usage_hypothesis_is_partially_confirmed():
    outcomes = compare_hypotheses_to_resolution(
        [InvestigationHypothesis("Accepted but not billed", "", hypothesis_code="usage.200.not_billed")],
        make_resolution(root_cause_code="usage.property_filter_mismatch", root_cause_category="usage"),
    )

    assert outcomes[0].outcome == "partially_confirmed"


def test_same_domain_different_root_is_rejected():
    outcomes = compare_hypotheses_to_resolution(
        [InvestigationHypothesis("Event type mismatch", "", hypothesis_code="usage.event_type_mismatch")],
        make_resolution(root_cause_code="usage.property_filter_mismatch", root_cause_category="usage"),
    )

    assert outcomes[0].outcome == "rejected"


def test_unknown_hypothesis_is_not_evaluated():
    outcomes = compare_hypotheses_to_resolution(
        [InvestigationHypothesis("Unknown", "", hypothesis_code="custom.unknown")],
        make_resolution(),
    )

    assert outcomes[0].outcome == "not_evaluated"


def test_historical_hypothesis_object_is_not_rewritten():
    hypothesis = InvestigationHypothesis(
        "The uniqueness key may have been used.",
        "Original explanation",
        hypothesis_code="contract.409.uniqueness",
    )

    compare_hypotheses_to_resolution([hypothesis], make_resolution())

    assert hypothesis.title == "The uniqueness key may have been used."
    assert hypothesis.explanation == "Original explanation"
    assert hypothesis.hypothesis_code == "contract.409.uniqueness"
