"""Deterministic evidence validation and rule providers."""

from __future__ import annotations

from typing import Protocol

from src.documentation.reranker import SearchResult

from .models import (
    ExtractedTicketSignals,
    InvestigationStep,
    SupportTicketInput,
    ValidationFinding,
)


class InvestigationRuleProvider(Protocol):
    def supports(self, signals: ExtractedTicketSignals) -> bool: ...
    def evaluate(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        documentation_results: list[SearchResult],
    ) -> list[ValidationFinding]: ...
    def build_checks(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
    ) -> list[InvestigationStep]: ...


# ── Generic provider ────────────────────────────────────────────────
class GenericApiRuleProvider:
    def supports(self, signals: ExtractedTicketSignals) -> bool:
        return True

    def evaluate(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        documentation_results: list[SearchResult],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        # HTTP method validation
        if signals.http_method:
            matched_doc = any(
                signals.http_method.upper() == (r.http_method or "").upper()
                for r in documentation_results
            )
            findings.append(ValidationFinding(
                rule_id="generic-http-method",
                status="passed" if matched_doc else "unknown",
                statement=f"HTTP method {signals.http_method} appears in documentation.",
                evidence=signals.http_method,
            ))
        else:
            findings.append(ValidationFinding(
                rule_id="generic-http-method",
                status="unknown",
                statement="HTTP method not provided in ticket.",
            ))

        # Endpoint validation
        if signals.endpoint_path:
            matched = any(
                signals.endpoint_path in (r.endpoint_path or "")
                for r in documentation_results
            )
            findings.append(ValidationFinding(
                rule_id="generic-endpoint",
                status="passed" if matched else "unknown",
                statement=f"Endpoint path {signals.endpoint_path} found in documentation.",
                evidence=signals.endpoint_path,
            ))
        else:
            findings.append(ValidationFinding(
                rule_id="generic-endpoint",
                status="warning",
                statement="Endpoint path missing from ticket.",
            ))

        # Response status documented
        if signals.status_code:
            findings.append(ValidationFinding(
                rule_id="generic-status-documented",
                status="unknown",
                statement=f"Response status {signals.status_code} requires documentation review.",
                evidence=str(signals.status_code),
            ))

        # Request fields present
        if signals.request_fields:
            findings.append(ValidationFinding(
                rule_id="generic-request-fields",
                status="passed",
                statement=f"Request contains {len(signals.request_fields)} structured fields.",
            ))
        elif ticket.request_body:
            findings.append(ValidationFinding(
                rule_id="generic-request-fields",
                status="warning",
                statement="Request body present but unstructured.",
            ))
        else:
            findings.append(ValidationFinding(
                rule_id="generic-request-fields",
                status="warning",
                statement="No request body provided.",
            ))

        return findings

    def build_checks(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
    ) -> list[InvestigationStep]:
        return []


# ── Contract creation provider ───────────────────────────────────────
class ContractCreationRuleProvider:
    def supports(self, signals: ExtractedTicketSignals) -> bool:
        return bool(
            signals.product_area == "contracts"
            and signals.http_method == "POST"
            and signals.endpoint_path
            and "create" in signals.endpoint_path.lower()
        )

    def evaluate(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        documentation_results: list[SearchResult],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        # Required fields check
        required = {"customer_id", "starting_at"}
        missing_req = required - set(signals.request_fields)
        if missing_req:
            findings.append(ValidationFinding(
                rule_id="contract-required-fields",
                status="failed",
                statement=f"Missing required fields: {', '.join(missing_req)}",
                evidence=str(list(missing_req)),
            ))
        else:
            findings.append(ValidationFinding(
                rule_id="contract-required-fields",
                status="passed",
                statement="Required fields customer_id and starting_at are present.",
            ))

        # 409 uniqueness check
        if signals.status_code == 409:
            findings.append(ValidationFinding(
                rule_id="contract-409-uniqueness",
                status="warning",
                statement="HTTP 409 may indicate a uniqueness-key conflict. "
                          "Verify whether an earlier request used the same uniqueness_key.",
                evidence="409 Conflict",
            ))

            has_uniqueness = "uniqueness_key" in signals.request_fields or \
                "uniqueness_key" in signals.technical_tokens
            findings.append(ValidationFinding(
                rule_id="contract-uniqueness-key-present",
                status="passed" if has_uniqueness else "unknown",
                statement="uniqueness_key may be involved in this conflict.",
            ))

        return findings

    def build_checks(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
    ) -> list[InvestigationStep]:
        steps: list[InvestigationStep] = []
        order = 100

        if signals.status_code == 409:
            steps.append(InvestigationStep(
                order=order,
                action="Check whether a previous request used the same uniqueness_key and succeeded.",
                reason="HTTP 409 with uniqueness_key typically means the key was already consumed.",
                expected_evidence="Original request ID and result from server logs.",
                source_url=None,
            ))
            order += 1
            steps.append(InvestigationStep(
                order=order,
                action="If the original operation created a contract, verify its customer_id, starting_at, and rate-card assignment.",
                reason="The existing contract may already satisfy the intended outcome.",
                expected_evidence="Existing contract details from the API.",
                source_url=None,
            ))
            order += 1
            steps.append(InvestigationStep(
                order=order,
                action="Use a new uniqueness_key only if this is a genuinely different logical operation.",
                reason="Uniqueness keys prevent accidental duplicate contract creation.",
                expected_evidence=None,
                source_url=None,
            ))

        return steps


# ── Customer creation provider ───────────────────────────────────────
class CustomerCreationRuleProvider:
    def supports(self, signals: ExtractedTicketSignals) -> bool:
        return bool(
            signals.product_area == "customers"
            and signals.http_method == "POST"
        )

    def evaluate(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        documentation_results: list[SearchResult],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        required = {"name"}
        missing_req = required - set(signals.request_fields)
        if missing_req:
            findings.append(ValidationFinding(
                rule_id="customer-required-fields",
                status="failed",
                statement=f"Missing required field: {', '.join(missing_req)}",
            ))
        else:
            findings.append(ValidationFinding(
                rule_id="customer-required-fields",
                status="passed",
                statement="Required name field present.",
            ))

        # Ingest alias
        has_alias = any("ingest" in f or "alias" in f for f in signals.request_fields)
        if has_alias:
            findings.append(ValidationFinding(
                rule_id="customer-ingest-alias",
                status="passed",
                statement="Ingest alias or external ID configuration present.",
            ))

        # Duplicate check
        if signals.status_code in (400, 409):
            findings.append(ValidationFinding(
                rule_id="customer-duplicate-check",
                status="warning",
                statement="Customer already exists or duplicate identifier conflict.",
            ))

        return findings

    def build_checks(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
    ) -> list[InvestigationStep]:
        steps: list[InvestigationStep] = []
        order = 100

        if signals.status_code in (400, 409):
            steps.append(InvestigationStep(
                order=order,
                action="Check whether a customer with the same external_id or ingest alias already exists.",
                reason="Duplicate identifiers are a common cause of customer creation failures.",
                expected_evidence="Customer list filtered by ingest alias.",
            ))
            order += 1

        return steps


# ── Usage ingestion provider ─────────────────────────────────────────
class UsageIngestionRuleProvider:
    def supports(self, signals: ExtractedTicketSignals) -> bool:
        return bool(
            signals.product_area == "usage"
            and signals.endpoint_path
            and ("ingest" in signals.endpoint_path.lower() or "event" in signals.endpoint_path.lower())
        )

    def evaluate(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        documentation_results: list[SearchResult],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        required = {"transaction_id"}
        missing_req = required - set(signals.request_fields)
        if missing_req:
            findings.append(ValidationFinding(
                rule_id="usage-required-fields",
                status="failed",
                statement=f"Missing required field: {', '.join(missing_req)}",
            ))
        else:
            findings.append(ValidationFinding(
                rule_id="usage-required-fields",
                status="passed",
                statement="Required transaction_id is present.",
            ))

        # Event type
        has_event_type = "event_type" in signals.request_fields
        findings.append(ValidationFinding(
            rule_id="usage-event-type",
            status="passed" if has_event_type else "warning",
            statement="event_type should be present in the event payload.",
        ))

        # Properties
        has_properties = "properties" in signals.request_fields
        findings.append(ValidationFinding(
            rule_id="usage-properties",
            status="passed" if has_properties else "warning",
            statement="properties object should contain billable metric fields.",
        ))

        # Accepted but not billed signal
        if ticket.actual_behavior and ("not billed" in ticket.actual_behavior.lower() or
                                         "invoice" in ticket.actual_behavior.lower() or
                                         "zero" in ticket.actual_behavior.lower()):
            findings.append(ValidationFinding(
                rule_id="usage-accepted-not-billed",
                status="warning",
                statement="Event accepted but usage not reflected in invoice. "
                          "Check billable metric filters, aggregation property, and contract activation.",
            ))

        return findings

    def build_checks(
        self, ticket: SupportTicketInput, signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
    ) -> list[InvestigationStep]:
        steps: list[InvestigationStep] = []
        order = 100

        steps.append(InvestigationStep(
            order=order,
            action="Verify the event was ingested successfully using the Event Search API with the transaction_id.",
            reason="Event Search confirms whether ingestion succeeded and what was stored.",
            expected_evidence="Event Search API response showing the ingested event.",
        ))
        order += 1

        steps.append(InvestigationStep(
            order=order,
            action="Compare event_type and property names against the customer's billable metric configuration.",
            reason="Mismatches between event fields and billable metric filters prevent usage from being counted.",
            expected_evidence="Billable metric definition and event payload comparison.",
        ))
        order += 1

        steps.append(InvestigationStep(
            order=order,
            action="Verify that the customer has an active contract with a rate card that covers the relevant product.",
            reason="Usage is only billed when it matches an active rate card.",
            expected_evidence="Customer contract and rate card details.",
        ))

        return steps


# ── Provider registry ────────────────────────────────────────────────
ALL_PROVIDERS: list[InvestigationRuleProvider] = [
    GenericApiRuleProvider(),
    ContractCreationRuleProvider(),
    CustomerCreationRuleProvider(),
    UsageIngestionRuleProvider(),
]