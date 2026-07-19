"""Build reusable regression-case candidates from confirmed resolutions."""

from __future__ import annotations

from .models import TicketInvestigationReport
from .resolution_models import RegressionCase, TicketResolutionInput
from .sanitizer import sanitize_ticket
from .models import SupportTicketInput


def build_regression_case(
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> RegressionCase | None:
    if resolution.resolution_status in {
        "unresolved",
        "cannot_reproduce",
        "documentation_issue",
        "expected_behavior",
    }:
        return None

    root = resolution.root_cause_code
    scenario = _scenario_for_resolution(root, investigation)
    case_code = root.replace(".", "-")
    title = _title_for_resolution(root)

    preconditions = _sanitize_dict(_preconditions(root, resolution))
    input_payload = _safe_input(root, resolution, investigation)
    expected_behavior = _expected_behavior(root)
    failure_signature = {
        "root_cause_code": root,
        "reason": resolution.root_cause_summary,
    }
    verification = {
        "steps": resolution.verification_steps,
        "results": resolution.verification_results,
    }

    return RegressionCase(
        id=None,
        resolution_id=None,
        case_code=case_code,
        title=title,
        scenario=scenario,
        preconditions=preconditions,
        input=input_payload,
        expected_behavior=_sanitize_dict(expected_behavior),
        failure_signature=_sanitize_dict(failure_signature),
        verification=_sanitize_dict(verification),
        automation_status="candidate",
    )


def _scenario_for_resolution(root: str, investigation: TicketInvestigationReport) -> str:
    if root.startswith("usage."):
        return "usage_ingestion"
    if root.startswith("idempotency.") or root.startswith("contract.") or root.startswith("rate_card."):
        return "contract_creation"
    if "customer" in root or root == "request.duplicate_identifier":
        return "customer_creation"
    return investigation.signals.product_area or "generic"


def _title_for_resolution(root: str) -> str:
    return root.replace(".", " ").replace("_", " ").title()


def _preconditions(root: str, resolution: TicketResolutionInput) -> dict[str, object]:
    if root.startswith("usage."):
        return {
            "customer_has_active_contract": True,
            "rate_card_active": True,
            "affected_configuration": resolution.affected_configuration,
        }
    if root.startswith("idempotency."):
        return {
            "uniqueness_key_previously_used": True,
            "affected_endpoint": resolution.affected_endpoint,
        }
    if root.startswith("request."):
        return {"affected_endpoint": resolution.affected_endpoint}
    return {"affected_component": resolution.affected_component}


def _safe_input(
    root: str,
    resolution: TicketResolutionInput,
    investigation: TicketInvestigationReport,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "affected_endpoint": resolution.affected_endpoint or investigation.signals.endpoint_path,
        "root_cause_code": root,
    }
    if root == "usage.property_filter_mismatch":
        payload.update({
            "event_type": "ai_usage",
            "properties": {"token_cost_usd": 0.12},
            "configured_property": resolution.affected_configuration or "cost_usd",
        })
    elif root == "usage.event_type_mismatch":
        payload.update({"event_type": "unexpected_event_type"})
    elif root == "usage.aggregation_key_missing":
        payload.update({"properties": {"region": "us-east-1"}})
    elif root.startswith("idempotency."):
        payload.update({"uniqueness_key_reused": True})
    elif root == "request.missing_required_field":
        payload.update({"missing_field": "starting_at"})
    elif root == "request.invalid_timestamp":
        payload.update({"starting_at": "next month"})
    elif root == "usage.duplicate_transaction":
        payload.update({"transaction_id_reused": True})
    return _sanitize_dict(payload)


def _expected_behavior(root: str) -> dict[str, object]:
    if root.startswith("usage."):
        return {
            "event_ingestion_status": "accepted",
            "billable_metric_match": root not in {
                "usage.property_filter_mismatch",
                "usage.event_type_mismatch",
                "usage.aggregation_key_missing",
            },
            "invoice_usage": 0,
        }
    if root.startswith("idempotency."):
        return {"response_status": 409, "previous_operation_lookup_required": True}
    if root.startswith("request."):
        return {"response_status": 400, "validation_error": True}
    return {"manual_verification_required": True}


def _sanitize_dict(value: dict[str, object]) -> dict[str, object]:
    ticket = SupportTicketInput(request_body=value)
    sanitized = sanitize_ticket(ticket).sanitized_ticket
    return sanitized.request_body if isinstance(sanitized.request_body, dict) else {}
