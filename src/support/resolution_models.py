"""Models and stable codes for human-confirmed ticket resolutions."""

from __future__ import annotations

from dataclasses import dataclass, field


SUPPORTED_RESOLUTION_STATUSES = {
    "confirmed",
    "partially_confirmed",
    "unresolved",
    "cannot_reproduce",
    "customer_configuration",
    "product_defect",
    "documentation_issue",
    "expected_behavior",
}

CONFIRMED_RESOLUTION_STATUSES = {
    "confirmed",
    "customer_configuration",
    "product_defect",
    "documentation_issue",
    "expected_behavior",
}

ROOT_CAUSE_CODES = {
    "request.invalid_field",
    "request.missing_required_field",
    "request.invalid_timestamp",
    "request.duplicate_identifier",
    "idempotency.key_reused",
    "idempotency.previous_operation_succeeded",
    "usage.customer_not_matched",
    "usage.event_type_mismatch",
    "usage.property_filter_mismatch",
    "usage.aggregation_key_missing",
    "usage.aggregation_value_invalid",
    "usage.timestamp_outside_period",
    "usage.duplicate_transaction",
    "contract.inactive",
    "contract.wrong_customer",
    "rate_card.inactive",
    "rate_card.wrong_pricing",
    "documentation.missing",
    "documentation.ambiguous",
    "documentation.outdated",
    "documentation.incorrect",
    "product.validation_gap",
    "product.error_message_gap",
    "product.observability_gap",
    "product.defect",
    "expected_behavior",
    "insufficient_evidence",
    "cannot_reproduce",
}

ROOT_CAUSE_CATEGORIES = {
    "request",
    "idempotency",
    "usage",
    "contract",
    "rate_card",
    "documentation",
    "product",
    "expected_behavior",
    "insufficient_evidence",
    "cannot_reproduce",
}

AUTOMATION_STATUSES = {"manual", "candidate", "automated", "not_automatable"}

IDENTIFIER_TYPES = {
    "request_id",
    "transaction_id",
    "customer_id",
    "contract_id",
    "billable_metric_id",
    "invoice_id",
    "rate_card_id",
}


@dataclass
class TicketResolutionInput:
    ticket_id: int
    analysis_id: int
    resolution_status: str
    root_cause_code: str
    root_cause_category: str
    root_cause_summary: str
    root_cause_details: str
    resolution_summary: str
    resolution_steps: list[str]
    verification_steps: list[str]
    verification_results: list[str]
    confirmed_by: str
    confirmed_at: str
    affected_component: str | None = None
    affected_endpoint: str | None = None
    affected_configuration: str | None = None
    request_ids: list[str] = field(default_factory=list)
    transaction_ids: list[str] = field(default_factory=list)
    customer_ids: list[str] = field(default_factory=list)
    contract_ids: list[str] = field(default_factory=list)
    billable_metric_ids: list[str] = field(default_factory=list)
    invoice_ids: list[str] = field(default_factory=list)
    rate_card_ids: list[str] = field(default_factory=list)
    affected_sources: list[str] = field(default_factory=list)
    internal_notes: str | None = None


@dataclass
class ResolutionValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    matched_observation_codes: list[str] = field(default_factory=list)
    matched_hypothesis_codes: list[str] = field(default_factory=list)
    new_confirmed_facts: list[str] = field(default_factory=list)


@dataclass
class HypothesisOutcome:
    hypothesis_code: str
    outcome: str
    explanation: str


@dataclass
class RegressionCase:
    id: int | None
    resolution_id: int | None
    case_code: str
    title: str
    scenario: str
    preconditions: dict[str, object]
    input: dict[str, object]
    expected_behavior: dict[str, object]
    failure_signature: dict[str, object]
    verification: dict[str, object]
    automation_status: str = "candidate"


@dataclass
class ConfirmedResolution:
    id: int
    ticket_id: int
    analysis_id: int
    resolution_status: str
    root_cause_code: str
    root_cause_category: str
    root_cause_summary: str
    root_cause_details: str
    resolution_summary: str
    resolution_steps: list[str]
    verification_steps: list[str]
    verification_results: list[str]
    confirmed_by: str
    confirmed_at: str
    hypothesis_outcomes: list[HypothesisOutcome] = field(default_factory=list)
    regression_case: RegressionCase | None = None
    feedback_items: list[object] = field(default_factory=list)


def category_for_root_cause(root_cause_code: str) -> str:
    if root_cause_code in {"expected_behavior", "insufficient_evidence", "cannot_reproduce"}:
        return root_cause_code
    return root_cause_code.split(".", 1)[0]
