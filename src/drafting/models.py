"""Drafting-domain models for grounded Gemini generation."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Stable draft types
# ---------------------------------------------------------------------------
SUPPORTED_DRAFT_TYPES = {
    "customer_update",
    "customer_resolution",
    "engineering_escalation",
    "internal_case_summary",
    "documentation_proposal",
    "product_feedback",
    "executive_summary",
}

# ---------------------------------------------------------------------------
# Draft audiences
# ---------------------------------------------------------------------------
DRAFT_AUDIENCES = {
    "customer",
    "engineering",
    "internal",
    "product",
    "executive",
}

AUDIENCE_FOR_DRAFT_TYPE: dict[str, str] = {
    "customer_update": "customer",
    "customer_resolution": "customer",
    "engineering_escalation": "engineering",
    "internal_case_summary": "internal",
    "documentation_proposal": "internal",
    "product_feedback": "product",
    "executive_summary": "executive",
}

# ---------------------------------------------------------------------------
# Draft workflow statuses
# ---------------------------------------------------------------------------
DRAFT_WORKFLOW_STATUSES = {
    "generated",
    "validation_failed",
    "needs_review",
    "approved",
    "rejected",
    "used",
}

DRAFT_VALIDATION_STATUSES = {
    "valid",
    "invalid",
    "warning",
}

DRAFT_DECISIONS = {
    "approve",
    "reject",
    "mark_used",
}

# ---------------------------------------------------------------------------
# Grounding fact types
# ---------------------------------------------------------------------------
GROUNDING_FACT_TYPES = {
    "ticket_observation",
    "request_evidence",
    "response_evidence",
    "validation_finding",
    "documentation_fact",
    "missing_evidence",
    "hypothesis",
    "confirmed_root_cause",
    "resolution_step",
    "verification_result",
    "feedback_gap",
    "regression_fact",
}

GROUNDING_CONFIRMATION_STATUSES = {
    "confirmed",
    "observed",
    "documentation_supported",
    "unconfirmed",
    "missing",
}

# ---------------------------------------------------------------------------
# Draft evaluation metrics
# ---------------------------------------------------------------------------
DRAFT_EVALUATION_METRICS = [
    "structured_output_validity",
    "fact_reference_validity",
    "claim_map_validity",
    "source_reference_validity",
    "unsupported_claim_rejection",
    "hypothesis_labelling_accuracy",
    "resolution_status_compliance",
    "secret_redaction_accuracy",
    "required_section_coverage",
    "customer_safety_accuracy",
    "human_review_transition_accuracy",
    "holdout_pass_rate",
]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class GroundingFact:
    """A single sanitized fact linking to its source evidence."""

    fact_code: str
    statement: str
    fact_type: str
    evidence_reference: str
    confirmation_status: str

    source_url: str | None = None
    internal_only: bool = False
    customer_safe: bool = True


@dataclass
class DraftGroundingPackage:
    """Closed, sanitized grounding payload for a single draft type.

    Every fact that Gemini is allowed to use must be present in this
    package.  No fact may be present that is not explicitly listed.
    """

    ticket_id: int | None
    analysis_id: int | None
    resolution_id: int | None
    feedback_id: int | None

    draft_type: str
    audience: str
    tone: str

    confirmed_facts: list[GroundingFact] = field(default_factory=list)
    observed_facts: list[GroundingFact] = field(default_factory=list)
    documentation_facts: list[GroundingFact] = field(default_factory=list)
    hypotheses: list[GroundingFact] = field(default_factory=list)
    missing_evidence: list[GroundingFact] = field(default_factory=list)
    resolution_facts: list[GroundingFact] = field(default_factory=list)
    feedback_facts: list[GroundingFact] = field(default_factory=list)

    documentation_sources: list[dict[str, object]] = field(default_factory=list)
    allowed_identifiers: dict[str, list[str]] = field(default_factory=dict)

    prohibited_claims: list[str] = field(default_factory=list)
    required_sections: list[str] = field(default_factory=list)

    package_version: str = "1.0.0"
    created_at: str = ""


@dataclass
class GeneratedDraft:
    """Result of a single grounded generation attempt."""

    id: int | None
    draft_type: str
    subject: str | None
    body: str

    used_fact_codes: list[str] = field(default_factory=list)
    used_source_urls: list[str] = field(default_factory=list)

    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    grounding_package_version: str = ""

    validation_status: str = ""
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)

    status: str = "generated"
    generated_at: str = ""


@dataclass
class DraftValidationResult:
    """Output of the post-generation validator."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    missing_required_sections: list[str] = field(default_factory=list)


@dataclass
class DraftEvaluationCase:
    """A single evaluation case for drafting."""

    case_id: str
    case_label: str
    draft_type: str
    expected_valid: bool
    expected_errors: list[str] = field(default_factory=list)
    expected_warnings: list[str] = field(default_factory=list)
    split: str = "tuning"
    mock_mode: str | None = None
    resolution_status: str | None = None
    description: str = ""


@dataclass
class DraftEvaluationReport:
    """Aggregated evaluation results for drafting."""

    total_cases: int = 0
    tuning_cases: int = 0
    holdout_cases: int = 0
    passed_tuning: int = 0
    passed_holdout: int = 0

    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    failures: list[dict[str, object]] = field(default_factory=list)