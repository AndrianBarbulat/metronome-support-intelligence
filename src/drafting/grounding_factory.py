"""Construct a sanitized DraftGroundingPackage from existing Phase 4/5 data."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from src.database.repository import DocumentationRepository
from src.drafting.models import (
    DraftGroundingPackage,
    GroundingFact,
    SUPPORTED_DRAFT_TYPES,
    AUDIENCE_FOR_DRAFT_TYPE,
)


# ---------------------------------------------------------------------------
# Required sections per draft type
# ---------------------------------------------------------------------------
_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "customer_update": [
        "Acknowledgement",
        "Confirmed findings",
        "What remains under investigation",
        "Information required",
        "Next steps",
    ],
    "customer_resolution": [
        "Acknowledgement",
        "Confirmed root cause",
        "Resolution",
        "Verification",
        "Prevention",
    ],
    "engineering_escalation": [
        "Issue summary",
        "Customer impact",
        "Environment context",
        "Endpoint and response",
        "Relevant identifiers",
        "Sanitized request evidence",
        "Sanitized response evidence",
        "Confirmed observations",
        "Current hypotheses",
        "Documentation consulted",
        "Investigation completed",
        "Reproduction status",
        "Missing evidence",
        "Specific engineering questions",
    ],
    "internal_case_summary": [
        "Issue summary",
        "Evidence collected",
        "Investigation steps",
        "Resolution status",
        "Hypothesis outcomes",
        "Documentation feedback",
    ],
    "documentation_proposal": [
        "Affected documentation",
        "Observed support problem",
        "Confirmed resolved behavior",
        "Identified gap",
        "Proposed location",
        "Proposed section outline",
        "Draft content",
        "Verification requirements",
        "Related regression case",
    ],
    "product_feedback": [
        "Customer problem",
        "Confirmed technical context",
        "Current product behavior",
        "Support investigation burden",
        "Current workaround",
        "Identified gap",
        "Proposed improvement",
        "Expected customer impact",
        "Expected support impact",
        "Verification criteria",
    ],
    "executive_summary": [
        "Customer problem",
        "Technical evidence",
        "Investigation approach",
        "Confirmed root cause",
        "Resolution",
        "Reusable regression learning",
        "Documentation feedback",
        "Business impact",
    ],
}

# ---------------------------------------------------------------------------
# Prohibited claims per audience
# ---------------------------------------------------------------------------
_PROHIBITED_CUSTOMER_CLAIMS = [
    "internal confidence",
    "product gap classification",
    "engineering-only",
    "internal notes",
    "exact completion time",
    "not yet fixed",
    "guarantee",
]

_PROHIBITED_ALL = [
    "api key",
    "secret",
    "password",
    "token",
    "authorization header",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ====================================================================
# Public API
# ====================================================================


def build_grounding_package(
    *,
    draft_type: str,
    database_path: Path,
    ticket_id: int | None = None,
    analysis_id: int | None = None,
    resolution_id: int | None = None,
    feedback_id: int | None = None,
    tone: str = "professional",
) -> DraftGroundingPackage:
    """Build a sanitized, closed grounding package for a specific draft type.

    Loads existing Phase 4 (ticket / analysis) and Phase 5 (resolution /
    feedback) data from the database.  Does not duplicate investigation
    or resolution logic.
    """
    if draft_type not in SUPPORTED_DRAFT_TYPES:
        raise ValueError(f"Unsupported draft type: {draft_type}")

    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        audience = AUDIENCE_FOR_DRAFT_TYPE.get(draft_type, "internal")
        pkg = DraftGroundingPackage(
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            resolution_id=resolution_id,
            feedback_id=feedback_id,
            draft_type=draft_type,
            audience=audience,
            tone=tone,
            required_sections=_REQUIRED_SECTIONS.get(draft_type, []),
            prohibited_claims=_build_prohibited(audience),
            created_at=_utc_now(),
        )

        # --- Load ticket + analysis ---
        if ticket_id is not None:
            _load_ticket_context(repo, ticket_id, analysis_id, pkg)

        # --- Load resolution ---
        if resolution_id is not None:
            _load_resolution_context(repo, resolution_id, pkg)

        # --- Load feedback ---
        if feedback_id is not None:
            _load_feedback_context(repo, feedback_id, pkg)

        # --- Audience filtering ---
        if audience == "customer":
            _filter_internal_facts(pkg)

        return pkg
    finally:
        repo.close()


# ====================================================================
# Internal helpers
# ====================================================================


def _load_ticket_context(
    repo: DocumentationRepository,
    ticket_id: int,
    analysis_id: int | None,
    pkg: DraftGroundingPackage,
) -> None:
    """Load ticket + evidence + analysis and populate grounding facts."""
    from src.database.repository import DocumentationRepository as DR
    import json as _json

    # Determine analysis
    if analysis_id is not None:
        ticket_row, analysis_row = repo.get_ticket_analysis_pair(ticket_id, analysis_id)
    else:
        analysis_row = repo.get_latest_analysis_for_ticket(ticket_id)
        ticket_row, _ = repo.get_ticket_analysis_pair(ticket_id, analysis_row["id"] if analysis_row else 0)

    if ticket_row is None:
        raise ValueError(f"Ticket {ticket_id} not found.")
    if analysis_row is None:
        raise ValueError(f"No analysis found for ticket {ticket_id}.")

    # --- Evidence ---
    conn = repo._get_conn()
    evidence_row = conn.execute(
        "SELECT * FROM support_ticket_evidence WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()

    # --- Observations ---
    observations_json = analysis_row["observations_json"]
    observations = _json.loads(observations_json) if observations_json else []

    for i, obs in enumerate(observations):
        code = obs.get("observation_code") or f"obs.{ticket_id}.{i}"
        pkg.observed_facts.append(GroundingFact(
            fact_code=code,
            statement=obs.get("statement", ""),
            fact_type="ticket_observation",
            evidence_reference=obs.get("evidence_reference", f"ticket.{ticket_id}"),
            confirmation_status="observed",
            internal_only=False,
            customer_safe=True,
        ))

    # --- Validation findings ---
    vf_json = analysis_row["validation_findings_json"]
    vfs = _json.loads(vf_json) if vf_json else []
    for i, vf in enumerate(vfs):
        code = vf.get("rule_id") or f"vf.{ticket_id}.{i}"
        pkg.confirmed_facts.append(GroundingFact(
            fact_code=code,
            statement=vf.get("statement", ""),
            fact_type="validation_finding",
            evidence_reference=f"ticket.{ticket_id}",
            confirmation_status="documentation_supported",
            source_url=vf.get("source_url"),
            internal_only=False,
            customer_safe=True,
        ))

    # --- Hypotheses ---
    hyps_json = analysis_row["hypotheses_json"]
    hyps = _json.loads(hyps_json) if hyps_json else []
    for i, hyp in enumerate(hyps):
        code = hyp.get("hypothesis_code") or f"hyp.{ticket_id}.{i}"
        pkg.hypotheses.append(GroundingFact(
            fact_code=code,
            statement=hyp.get("title", "") or hyp.get("explanation", ""),
            fact_type="hypothesis",
            evidence_reference=f"ticket.{ticket_id}",
            confirmation_status="unconfirmed",
            internal_only=False,
            customer_safe=True,
        ))

    # --- Missing evidence ---
    me_json = analysis_row["missing_evidence_json"]
    mes = _json.loads(me_json) if me_json else []
    for i, me in enumerate(mes):
        code = f"missing.{ticket_id}.{i}"
        pkg.missing_evidence.append(GroundingFact(
            fact_code=code,
            statement=me.get("reason", me.get("field", "")),
            fact_type="missing_evidence",
            evidence_reference=f"ticket.{ticket_id}",
            confirmation_status="missing",
            internal_only=False,
            customer_safe=True,
        ))

    # --- Documentation links ---
    doc_links = conn.execute(
        "SELECT * FROM support_ticket_document_links WHERE ticket_id = ? AND analysis_id = ?",
        (ticket_id, analysis_row["id"]),
    ).fetchall()

    existing_urls = set()
    for dl in doc_links:
        url = dl["source_url"]
        if url not in existing_urls:
            existing_urls.add(url)
            pkg.documentation_sources.append({
                "page_title": dl["page_title"],
                "source_url": url,
                "heading": dl["heading"],
                "relevance_score": dl["relevance_score"],
            })

    # --- Identifiers ---
    if evidence_row:
        req_body = _json.loads(evidence_row["request_body_json"]) if evidence_row["request_body_json"] else {}
        if isinstance(req_body, dict):
            for field in ("request_id", "transaction_id", "customer_id"):
                val = req_body.get(field)
                if val and isinstance(val, str):
                    pkg.allowed_identifiers.setdefault(field, []).append(val)
        resp_body = _json.loads(evidence_row["response_body_json"]) if evidence_row["response_body_json"] else {}
        if isinstance(resp_body, dict):
            for field in ("request_id", "transaction_id"):
                val = resp_body.get(field)
                if val and isinstance(val, str):
                    pkg.allowed_identifiers.setdefault(field, []).append(val)


def _load_resolution_context(
    repo: DocumentationRepository,
    resolution_id: int,
    pkg: DraftGroundingPackage,
) -> None:
    """Load confirmed resolution data into the grounding package."""
    import json as _json

    resolution = repo.get_resolution(resolution_id)
    if resolution is None:
        raise ValueError(f"Resolution {resolution_id} not found.")

    pkg.resolution_id = resolution_id
    pkg.ticket_id = resolution["ticket_id"]
    pkg.analysis_id = resolution["analysis_id"]

    # Root cause
    pkg.resolution_facts.append(GroundingFact(
        fact_code=resolution["root_cause_code"],
        statement=f"{resolution['root_cause_summary']} — {resolution['root_cause_details']}",
        fact_type="confirmed_root_cause",
        evidence_reference=f"resolution.{resolution_id}",
        confirmation_status="confirmed",
        internal_only=False,
        customer_safe=True,
    ))

    # Resolution steps
    steps = _json.loads(resolution["resolution_steps_json"])
    for i, step in enumerate(steps):
        pkg.resolution_facts.append(GroundingFact(
            fact_code=f"resolution.step.{resolution_id}.{i}",
            statement=step,
            fact_type="resolution_step",
            evidence_reference=f"resolution.{resolution_id}",
            confirmation_status="confirmed",
            internal_only=False,
            customer_safe=True,
        ))

    # Verification
    verifications = _json.loads(resolution["verification_results_json"])
    for i, v in enumerate(verifications):
        pkg.resolution_facts.append(GroundingFact(
            fact_code=f"verification.{resolution_id}.{i}",
            statement=v,
            fact_type="verification_result",
            evidence_reference=f"resolution.{resolution_id}",
            confirmation_status="confirmed",
            internal_only=False,
            customer_safe=True,
        ))

    # Identifiers
    conn = repo._get_conn()
    id_rows = conn.execute(
        "SELECT * FROM support_resolution_identifiers WHERE resolution_id = ?",
        (resolution_id,),
    ).fetchall()
    for row in id_rows:
        pkg.allowed_identifiers.setdefault(row["identifier_type"], []).append(
            row["identifier_value"]
        )

    # Hypothesis outcomes
    outcomes = conn.execute(
        "SELECT * FROM support_hypothesis_outcomes WHERE resolution_id = ?",
        (resolution_id,),
    ).fetchall()
    for outcome in outcomes:
        pkg.hypotheses.append(GroundingFact(
            fact_code=outcome["hypothesis_code"],
            statement=f"{outcome['outcome']}: {outcome['explanation']}",
            fact_type="hypothesis",
            evidence_reference=f"resolution.{resolution_id}",
            confirmation_status="confirmed"
            if outcome["outcome"] in ("confirmed", "supported")
            else "unconfirmed",
            internal_only=outcome["outcome"] == "rejected",
            customer_safe=outcome["outcome"] != "rejected",
        ))

    # Regression cases
    reg_cases = conn.execute(
        "SELECT * FROM support_regression_cases WHERE resolution_id = ?",
        (resolution_id,),
    ).fetchall()
    for rc in reg_cases:
        pkg.confirmed_facts.append(GroundingFact(
            fact_code=rc["case_code"],
            statement=f"Regression case: {rc['title']} — {rc['scenario']}",
            fact_type="regression_fact",
            evidence_reference=f"resolution.{resolution_id}",
            confirmation_status="confirmed",
            internal_only=True,
            customer_safe=False,
        ))


def _load_feedback_context(
    repo: DocumentationRepository,
    feedback_id: int,
    pkg: DraftGroundingPackage,
) -> None:
    """Load a specific feedback item into the grounding package."""
    import json as _json

    fb = repo.get_feedback_item(feedback_id)
    if fb is None:
        raise ValueError(f"Feedback item {feedback_id} not found.")

    pkg.feedback_id = feedback_id
    pkg.resolution_id = fb["resolution_id"]

    pkg.feedback_facts.append(GroundingFact(
        fact_code=fb["gap_code"],
        statement=f"{fb['title']}: {fb['summary']}",
        fact_type="feedback_gap",
        evidence_reference=f"feedback.{feedback_id}",
        confirmation_status="confirmed"
        if fb["status"] in ("approved", "implemented", "verified")
        else "observed",
        internal_only=fb["feedback_type"] in ("product", "observability"),
        customer_safe=fb["feedback_type"] not in ("product", "observability"),
    ))

    # Affected sources from feedback
    affected = _json.loads(fb["affected_sources_json"])
    for src_url in affected:
        if isinstance(src_url, str) and src_url not in {
            s["source_url"]
            for s in pkg.documentation_sources
            if isinstance(s, dict)
        }:
            pkg.documentation_sources.append({"page_title": "", "source_url": src_url,
                                              "heading": None, "relevance_score": 0.0})


def _build_prohibited(audience: str) -> list[str]:
    prohibited = list(_PROHIBITED_ALL)
    if audience == "customer":
        prohibited.extend(_PROHIBITED_CUSTOMER_CLAIMS)
    return prohibited


def _filter_internal_facts(pkg: DraftGroundingPackage) -> None:
    """Remove internal-only facts for customer-facing drafts."""
    pkg.confirmed_facts = [f for f in pkg.confirmed_facts if f.customer_safe]
    pkg.observed_facts = [f for f in pkg.observed_facts if f.customer_safe]
    pkg.documentation_facts = [f for f in pkg.documentation_facts if f.customer_safe]
    pkg.hypotheses = [f for f in pkg.hypotheses if f.customer_safe]
    pkg.missing_evidence = [f for f in pkg.missing_evidence if f.customer_safe]
    pkg.resolution_facts = [f for f in pkg.resolution_facts if f.customer_safe]
    pkg.feedback_facts = [f for f in pkg.feedback_facts if f.customer_safe]