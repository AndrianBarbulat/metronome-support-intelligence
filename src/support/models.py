"""Support ticket investigation models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SupportTicketInput:
    external_ticket_id: str | None = None
    subject: str = ""
    customer_message: str = ""

    http_method: str | None = None
    endpoint_path: str | None = None

    request_headers: dict[str, object] | None = None
    request_body: dict[str, object] | list[object] | str | None = None

    response_status: int | None = None
    response_headers: dict[str, object] | None = None
    response_body: dict[str, object] | list[object] | str | None = None

    logs: str | None = None
    expected_behavior: str | None = None
    actual_behavior: str | None = None

    created_at: str | None = None


@dataclass
class SanitizationResult:
    sanitized_ticket: SupportTicketInput
    redaction_count: int = 0
    redacted_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractedTicketSignals:
    product_area: str | None = None
    probable_operation: str | None = None

    http_method: str | None = None
    endpoint_path: str | None = None
    status_code: int | None = None

    request_fields: list[str] = field(default_factory=list)
    response_fields: list[str] = field(default_factory=list)

    technical_tokens: list[str] = field(default_factory=list)
    error_terms: list[str] = field(default_factory=list)

    identifiers: dict[str, list[str]] = field(default_factory=dict)
    timestamps: list[str] = field(default_factory=list)

    expected_behavior: str | None = None
    actual_behavior: str | None = None


@dataclass
class RetrievalQuery:
    query: str
    included_signals: list[str] = field(default_factory=list)
    excluded_signals: list[str] = field(default_factory=list)


@dataclass
class InvestigationObservation:
    statement: str
    evidence_type: str  # ticket_field, request, response, log, documentation, validation, analysis
    evidence_reference: str | None = None
    confidence: float = 1.0
    observation_code: str | None = None


@dataclass
class ValidationFinding:
    rule_id: str
    status: str  # passed, failed, unknown, warning
    statement: str
    evidence: str | None = None
    source_url: str | None = None


@dataclass
class InvestigationHypothesis:
    title: str
    explanation: str
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    verification_steps: list[str] = field(default_factory=list)
    confidence: float = 0.0
    hypothesis_code: str | None = None
    supporting_observation_codes: list[str] = field(default_factory=list)
    contradicting_observation_codes: list[str] = field(default_factory=list)
    missing_evidence_codes: list[str] = field(default_factory=list)


@dataclass
class InvestigationStep:
    order: int
    action: str
    reason: str
    expected_evidence: str | None = None
    source_url: str | None = None
    priority: str = "medium"
    blocking: bool = False
    status: str = "pending"


@dataclass
class MissingEvidence:
    field: str
    priority: str
    reason: str


@dataclass
class TicketDocumentationSource:
    page_title: str
    source_url: str
    heading: str | None
    relevance_score: float
    matched_tokens: list[str] = field(default_factory=list)
    ranking_reasons: list[str] = field(default_factory=list)
    usage_type: str = "diagnosis"


@dataclass
class TicketInvestigationReport:
    ticket_id: int | None
    summary: str
    sanitized: bool

    signals: ExtractedTicketSignals
    observations: list[InvestigationObservation] = field(default_factory=list)
    validation_findings: list[ValidationFinding] = field(default_factory=list)
    hypotheses: list[InvestigationHypothesis] = field(default_factory=list)
    missing_evidence: list[MissingEvidence] = field(default_factory=list)
    investigation_steps: list[InvestigationStep] = field(default_factory=list)
    documentation_sources: list[TicketDocumentationSource] = field(default_factory=list)
    discarded_sources: list[TicketDocumentationSource] = field(default_factory=list)

    retrieval_query: str = ""
    retrieval_confidence: float = 0.0
    signal_confidence: float = 0.0
    documentation_confidence: float = 0.0
    evidence_completeness: float = 0.0
    investigation_confidence: float = 0.0
    generated_at: str = ""
    analyzer_version: str = "1.0.0"