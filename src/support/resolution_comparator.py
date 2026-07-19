"""Compare confirmed root causes with earlier unconfirmed hypotheses."""

from __future__ import annotations

from .models import InvestigationHypothesis
from .resolution_models import HypothesisOutcome, TicketResolutionInput


HYPOTHESIS_TO_ROOT_CAUSES = {
    "contract.409.uniqueness": {
        "idempotency.key_reused",
        "idempotency.previous_operation_succeeded",
    },
    "contract.400.missing_field": {
        "request.missing_required_field",
        "request.invalid_timestamp",
        "request.invalid_field",
    },
    "usage.200.not_billed": {
        "usage.customer_not_matched",
        "usage.event_type_mismatch",
        "usage.property_filter_mismatch",
        "usage.aggregation_key_missing",
        "usage.aggregation_value_invalid",
        "usage.timestamp_outside_period",
        "contract.inactive",
        "rate_card.inactive",
        "rate_card.wrong_pricing",
    },
    "usage.event_type_mismatch": {"usage.event_type_mismatch"},
    "usage.property_filter_mismatch": {"usage.property_filter_mismatch"},
    "usage.aggregation_key_missing": {"usage.aggregation_key_missing"},
    "usage.duplicate_transaction": {"usage.duplicate_transaction"},
    "customer.duplicate_identifier": {"request.duplicate_identifier"},
}


def compare_hypotheses_to_resolution(
    hypotheses: list[InvestigationHypothesis],
    resolution: TicketResolutionInput,
) -> list[HypothesisOutcome]:
    outcomes: list[HypothesisOutcome] = []
    for hypothesis in hypotheses:
        code = hypothesis.hypothesis_code
        if not code:
            continue
        outcomes.append(_compare_one(code, resolution.root_cause_code))
    return outcomes


def _compare_one(hypothesis_code: str, root_cause_code: str) -> HypothesisOutcome:
    mapped = HYPOTHESIS_TO_ROOT_CAUSES.get(hypothesis_code)
    if mapped is None:
        return HypothesisOutcome(
            hypothesis_code=hypothesis_code,
            outcome="not_evaluated",
            explanation="No deterministic comparison rule exists for this hypothesis.",
        )
    if root_cause_code in mapped:
        exact = hypothesis_code.endswith(root_cause_code) or hypothesis_code == root_cause_code
        return HypothesisOutcome(
            hypothesis_code=hypothesis_code,
            outcome="confirmed" if exact or len(mapped) == 1 else "partially_confirmed",
            explanation="Confirmed root cause is compatible with the earlier hypothesis.",
        )
    if _same_domain(hypothesis_code, root_cause_code):
        return HypothesisOutcome(
            hypothesis_code=hypothesis_code,
            outcome="rejected",
            explanation="Confirmed root cause is in the same area but points to different evidence.",
        )
    return HypothesisOutcome(
        hypothesis_code=hypothesis_code,
        outcome="rejected",
        explanation="Confirmed root cause does not support the earlier hypothesis.",
    )


def _same_domain(hypothesis_code: str, root_cause_code: str) -> bool:
    return hypothesis_code.split(".", 1)[0] == root_cause_code.split(".", 1)[0]
