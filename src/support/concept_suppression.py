"""Suppress concepts that are already satisfied by ticket evidence."""

from __future__ import annotations

from .investigation_concepts import InvestigationConcept
from .models import (
    ConceptSelectionDecision,
    ExtractedTicketSignals,
    InvestigationObservation,
    SupportTicketInput,
    ValidationFinding,
)


def evaluate_evidence_state(
    ticket: SupportTicketInput,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding] | None = None,
) -> set[str]:
    """Return the set of active evidence-state flags for this ticket."""
    flags: set[str] = set()
    findings = findings or []

    # Request evidence
    if ticket.http_method or signals.http_method:
        flags.add("http_method_present")
    if ticket.endpoint_path or signals.endpoint_path:
        flags.add("endpoint_present")
    if ticket.request_body is not None:
        flags.add("request_body_present")
        if isinstance(ticket.request_body, (dict, list)):
            flags.add("structured_request_body_present")
    if (ticket.http_method or signals.http_method) and (ticket.endpoint_path or signals.endpoint_path):
        flags.add("request_operation_present")

    # Response evidence
    if ticket.response_status is not None:
        flags.add("response_status_present")
    if ticket.response_body is not None:
        flags.add("response_body_present")
        if isinstance(ticket.response_body, (dict, list)):
            flags.add("structured_response_body_present")
    if ticket.response_status is not None and ticket.response_body is not None:
        flags.add("complete_response_present")

    # Headers
    has_req_id = (
        (ticket.request_headers or {}).get("x-request-id")
        or (ticket.response_headers or {}).get("x-request-id")
    )
    if has_req_id:
        flags.add("request_id_present")
    if ticket.created_at or signals.timestamps or "timestamp" in signals.request_fields:
        flags.add("timestamp_present")

    # Behavior
    if ticket.expected_behavior:
        flags.add("expected_behavior_present")
    if ticket.actual_behavior:
        flags.add("actual_behavior_present")

    # Application-level responses (non-auth-error)
    if ticket.response_status is not None and ticket.response_status not in (401, 403):
        if 200 <= ticket.response_status < 500:
            flags.add("application_response_present")

    # 409-specific
    if ticket.response_status == 409:
        flags.add("status_409")
    if ticket.response_status in (400, 422):
        flags.add("status_400")

    # Contract-specific
    if signals.product_area == "contracts":
        if signals.http_method == "POST":
            flags.add("scenario.contract_creation")
        if "starting_at" in signals.request_fields:
            # Basic check: does it look like ISO-8601?
            st = None
            if isinstance(ticket.request_body, dict):
                st = ticket.request_body.get("starting_at")
            if st and isinstance(st, str) and "T" in st and st.endswith("Z"):
                flags.add("starting_at_valid_format")
        if "uniqueness_key" in signals.request_fields:
            flags.add("uniqueness_key_recorded")
        if _response_mentions(ticket, "uniqueness") or _response_mentions(ticket, "duplicate"):
            flags.add("response_mentions_uniqueness")

    # Usage-specific
    if signals.product_area == "usage":
        if signals.http_method == "POST" or signals.probable_operation == "ingest":
            flags.add("scenario.usage_ingestion")
        if "transaction_id" in signals.request_fields:
            flags.add("transaction_id_present")
        accepted_or_successful = ticket.response_status == 200 or _text_contains(
            " ".join([ticket.customer_message, ticket.actual_behavior or ""]),
            ["accepted", "successful", "succeeded", "200"],
        )
        not_billed = (
            _text_contains(ticket.actual_behavior, ["not billed", "invoice", "zero", "not reflected", "no charge"])
            or _text_contains(ticket.customer_message, ["not billed", "invoice", "zero", "not reflected", "no charge"])
        )
        if accepted_or_successful and not_billed:
            flags.add("usage_accepted_not_billed")
        if ticket.response_status == 409 or _response_mentions(ticket, "duplicate"):
            flags.add("usage_duplicate_transaction")

    if signals.product_area == "customers" and signals.http_method == "POST":
        flags.add("scenario.customer_creation")

    for finding in findings:
        flags.add(f"finding.{finding.rule_id}.{finding.status}")

    if _finding_status(findings, "generic-http-method") == "passed":
        flags.add("http_method_documented")
    if _finding_status(findings, "generic-endpoint") == "passed":
        flags.add("endpoint_documented")
    if _finding_status(findings, "contract-required-fields") == "passed":
        flags.add("contract_required_fields_present")
    if _finding_status(findings, "usage-required-fields") == "passed":
        flags.add("usage_required_fields_present")

    return flags


def suppress_redundant_concepts(
    concepts: list[InvestigationConcept],
    ticket: SupportTicketInput,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    observations: list[InvestigationObservation] | None = None,
) -> tuple[list[InvestigationConcept], list[ConceptSelectionDecision]]:
    """Return (selected_concepts, all_decisions) after evidence-state evaluation."""
    flags = evaluate_evidence_state(ticket, signals, findings)
    selected: list[InvestigationConcept] = []
    decisions: list[ConceptSelectionDecision] = []

    for c in concepts:
        decision = _evaluate_concept(c, flags, signals, findings)
        decisions.append(decision)
        if decision.status == "selected":
            selected.append(c)

    return selected, decisions


def _evaluate_concept(
    concept: InvestigationConcept,
    flags: set[str],
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
) -> ConceptSelectionDecision:
    specific = _specific_decision(concept, flags, signals, findings)
    if specific:
        return specific

    # Check skip conditions
    for skip_cond in concept.skip_when:
        if skip_cond in flags:
            return ConceptSelectionDecision(
                concept_code=concept.code,
                status="suppressed",
                reasons=[f"Skip condition met: {skip_cond}"],
            )

    # Check complete conditions
    satisfied = [c for c in concept.complete_when if c in flags]
    if concept.complete_when and len(satisfied) == len(concept.complete_when):
        return ConceptSelectionDecision(
            concept_code=concept.code,
            status="already_complete",
            reasons=[f"Evidence present: {', '.join(satisfied)}"],
            satisfied_by=satisfied,
        )

    # Check triggered_by — if triggers exist, none match → not applicable
    if concept.triggered_by:
        trigger_matched = False
        for trigger in concept.triggered_by:
            # Simple rule: trigger must be a flag in the evidence state
            for flag_val in flags:
                if trigger in flag_val or flag_val in trigger:
                    trigger_matched = True
                    break
            if trigger_matched:
                break

        if not trigger_matched:
            return ConceptSelectionDecision(
                concept_code=concept.code,
                status="not_applicable",
                reasons=[f"No trigger matched: {concept.triggered_by}"],
            )

    return ConceptSelectionDecision(
        concept_code=concept.code,
        status="selected",
    )


def _specific_decision(
    concept: InvestigationConcept,
    flags: set[str],
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
) -> ConceptSelectionDecision | None:
    code = concept.code

    if signals.status_code in (401, 403) and code.startswith("contract."):
        return _not_applicable(code, "authentication failure must be resolved before contract-specific validation")

    if code == "generic.capture_timestamp" and "timestamp_present" in flags:
        return _complete(code, "request timestamp is already present", ["timestamp_present"])

    if code == "generic.capture_complete_request" and {
        "http_method_present", "endpoint_present", "structured_request_body_present",
    }.issubset(flags):
        return _complete(
            code,
            "structured request body, HTTP method, and endpoint are already present",
            ["http_method_present", "endpoint_present", "structured_request_body_present"],
        )

    if code == "generic.capture_complete_response" and "complete_response_present" in flags:
        return _complete(
            code,
            "response status and body are already present",
            ["response_status_present", "response_body_present"],
        )

    if code == "generic.verify_authentication" and "application_response_present" in flags:
        return _suppressed(code, "application-level response indicates authentication and routing were accepted")

    if code == "generic.verify_authentication" and signals.status_code not in (401, 403):
        return _not_applicable(code, "no authentication failure evidence is present")

    if code == "generic.verify_endpoint_and_method" and {
        "http_method_documented", "endpoint_documented",
    }.issubset(flags):
        return _suppressed(code, "HTTP method and endpoint already matched documentation")

    if code == "generic.confirm_expected_behavior" and signals.product_area in {"contracts", "usage", "customers"}:
        if "expected_behavior_present" in flags:
            return _complete(code, "expected behavior is already present", ["expected_behavior_present"])
        if signals.product_area == "contracts" and signals.status_code == 409:
            return _suppressed(code, "contract retry-intent check collects the relevant expected behavior")

    if code == "generic.confirm_actual_behavior" and signals.product_area in {"contracts", "usage", "customers"}:
        if "actual_behavior_present" in flags:
            return _complete(code, "actual behavior is already present", ["actual_behavior_present"])
        if signals.status_code is not None and "response_body_present" in flags:
            return _suppressed(code, "response evidence already captures the observed API behavior")

    if code == "generic.reproduce_minimal_request":
        if signals.product_area == "contracts" and signals.status_code == 409:
            return _suppressed(code, "uniqueness conflict is already reproducible and needs previous-operation evidence")
        if signals.product_area == "usage" and "usage_accepted_not_billed" in flags:
            return _suppressed(code, "accepted usage requires matching and billing verification, not reproduction first")

    if code == "generic.verify_final_state" and signals.product_area is None:
        return _not_applicable(code, "no affected resource is identified yet")

    if code == "generic.prepare_escalation" and signals.product_area is None:
        return _not_applicable(code, "unsupported or vague tickets should gather evidence before escalation")

    if code == "contract.verify_endpoint" and {
        "http_method_documented", "endpoint_documented",
    }.issubset(flags):
        return _suppressed(code, "contract creation endpoint already matched documentation")

    if code == "contract.validate_required_fields":
        if signals.status_code == 409:
            return _not_applicable(code, "409 uniqueness conflict is not a required-field validation failure")
        if "contract_required_fields_present" in flags and signals.status_code in (400, 422):
            msg = "required contract fields are present"
            if "starting_at_valid_format" in flags:
                msg += " and starting_at format validation passed"
            return _suppressed(code, msg)

    if code == "contract.validate_starting_at":
        if signals.status_code == 409 and "starting_at_valid_format" in flags:
            return _suppressed(code, "starting_at is present and format validation passed")
        if "starting_at_valid_format" in flags and not _response_mentions_validation(findings):
            return _suppressed(code, "starting_at is present and format validation passed")

    if code == "contract.reproduce_minimal_valid_payload" and signals.status_code == 409:
        return _suppressed(code, "previous-operation lookup is more relevant than reproducing a valid payload")

    if code == "contract.verify_customer_reference" and signals.status_code == 409:
        return _suppressed(code, "existing-contract comparison covers customer verification for uniqueness conflicts")

    if code == "contract.verify_rate_card_reference" and signals.status_code == 409:
        return _suppressed(code, "existing-contract comparison covers pricing verification for uniqueness conflicts")

    if code == "contract.capture_uniqueness_key" and "uniqueness_key_recorded" in flags:
        return _complete(code, "uniqueness_key is already present in the request body", ["uniqueness_key_recorded"])

    if code == "usage.capture_transaction_id" and "transaction_id_present" in flags:
        if "usage_accepted_not_billed" in flags:
            return ConceptSelectionDecision(
                concept_code=code,
                status="selected",
                reasons=["transaction_id is present and should be recorded with the successful ingestion response"],
                satisfied_by=["transaction_id_present"],
            )
        return _complete(code, "transaction_id is already present in the request body", ["transaction_id_present"])

    if code in {
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
    }:
        if "usage_duplicate_transaction" in flags and "usage_accepted_not_billed" not in flags:
            return _not_applicable(code, "duplicate transaction evidence does not require invoice-zero workflow")

    if code in {
        "usage.locate_original_transaction",
        "usage.compare_original_and_retry",
        "usage.determine_same_logical_event",
    }:
        if "usage_duplicate_transaction" not in flags:
            return _not_applicable(code, "no duplicate transaction evidence is present")

    return None


def _complete(code: str, reason: str, satisfied_by: list[str]) -> ConceptSelectionDecision:
    return ConceptSelectionDecision(
        concept_code=code,
        status="already_complete",
        reasons=[reason],
        satisfied_by=satisfied_by,
    )


def _suppressed(code: str, reason: str) -> ConceptSelectionDecision:
    return ConceptSelectionDecision(concept_code=code, status="suppressed", reasons=[reason])


def _not_applicable(code: str, reason: str) -> ConceptSelectionDecision:
    return ConceptSelectionDecision(concept_code=code, status="not_applicable", reasons=[reason])


def _finding_status(findings: list[ValidationFinding], rule_id: str) -> str | None:
    for finding in findings:
        if finding.rule_id == rule_id:
            return finding.status
    return None


def _response_mentions(ticket: SupportTicketInput | None, term: str) -> bool:
    if ticket is None:
        return False
    if isinstance(ticket.response_body, dict):
        text = " ".join(str(v) for v in ticket.response_body.values())
    else:
        text = str(ticket.response_body or "")
    return term.lower() in text.lower()


def _text_contains(value: str | None, terms: list[str]) -> bool:
    text = (value or "").lower()
    return any(term in text for term in terms)


def _response_mentions_validation(findings: list[ValidationFinding]) -> bool:
    return any(
        finding.status == "failed" and (
            "starting_at" in (finding.statement or "").lower()
            or "timestamp" in (finding.statement or "").lower()
        )
        for finding in findings
    )
