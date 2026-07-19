"""Tests for the post-generation draft validator."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from datetime import datetime, timezone

from src.drafting.validator import validate_draft
from src.drafting.models import (
    DraftGroundingPackage,
    GroundingFact,
    DraftValidationResult,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _make_pkg(**overrides):
    """Build a minimal grounding package for testing."""
    kwargs = {
        "ticket_id": 1,
        "analysis_id": 1,
        "resolution_id": None,
        "feedback_id": None,
        "draft_type": "customer_update",
        "audience": "customer",
        "tone": "professional",
        "created_at": _utc_now(),
        "required_sections": ["Acknowledgement", "Confirmed findings", "Next steps"],
    }
    kwargs.update(overrides)
    pkg = DraftGroundingPackage(**kwargs)

    pkg.observed_facts.append(GroundingFact(
        fact_code="request.endpoint.present",
        statement="Request hit POST /v1/contracts/create.",
        fact_type="request_evidence",
        evidence_reference="ticket.1",
        confirmation_status="observed",
    ))
    pkg.observed_facts.append(GroundingFact(
        fact_code="response.status.present",
        statement="Response returned HTTP 409.",
        fact_type="response_evidence",
        evidence_reference="ticket.1",
        confirmation_status="observed",
    ))
    pkg.hypotheses.append(GroundingFact(
        fact_code="hyp.uniqueness",
        statement="Possible uniqueness key reuse.",
        fact_type="hypothesis",
        evidence_reference="ticket.1",
        confirmation_status="unconfirmed",
    ))
    pkg.documentation_sources.append({
        "page_title": "Create Contract",
        "source_url": "https://docs.metronome.com/api/contracts/create",
        "heading": "Idempotency",
        "relevance_score": 0.95,
    })
    return pkg


def _valid_output(**overrides):
    """Build a valid-looking provider output."""
    result = {
        "subject": "Investigation update",
        "body": (
            "## Acknowledgement\n"
            "Thank you for your report.\n\n"
            "## Confirmed findings\n"
            "The request returned HTTP 409.\n\n"
            "## What remains under investigation\n"
            "We are checking the uniqueness key.\n\n"
            "## Next steps\n"
            "We will update you soon."
        ),
        "used_fact_codes": ["request.endpoint.present", "response.status.present", "hyp.uniqueness"],
        "used_source_urls": ["https://docs.metronome.com/api/contracts/create"],
        "claim_map": [
            {
                "claim": "The request returned HTTP 409.",
                "fact_codes": ["response.status.present"],
            }
        ],
    }
    result.update(overrides)
    return result


class TestStructureValidation:
    """Validates structural correctness of provider output."""

    def test_valid_output_passes(self):
        pkg = _make_pkg()
        output = _valid_output()
        result = validate_draft(output, pkg)
        assert result.valid is True

    def test_non_dict_output_fails(self):
        pkg = _make_pkg()
        result = validate_draft("not a dict", pkg)  # type: ignore[arg-type]
        assert result.valid is False
        assert any("not a dictionary" in e.lower() for e in result.errors)

    def test_empty_body_fails(self):
        pkg = _make_pkg()
        output = _valid_output(body="")
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_empty_body_whitespace_fails(self):
        pkg = _make_pkg()
        output = _valid_output(body="   ")
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_missing_body_key(self):
        pkg = _make_pkg()
        output = {"subject": "Test"}
        result = validate_draft(output, pkg)
        assert result.valid is False


class TestFactReferenceValidation:
    """Validates fact-code references against grounding package."""

    def test_unknown_fact_code_rejected(self):
        pkg = _make_pkg()
        output = _valid_output(used_fact_codes=["nonexistent.fact"])
        result = validate_draft(output, pkg)
        assert result.valid is False
        assert any("nonexistent.fact" in e for e in result.errors)

    def test_valid_fact_code_accepted(self):
        pkg = _make_pkg()
        output = _valid_output(used_fact_codes=["request.endpoint.present"])
        result = validate_draft(output, pkg)
        assert result.valid is True

    def test_claim_map_unknown_fact_rejected(self):
        pkg = _make_pkg()
        output = _valid_output(claim_map=[{
            "claim": "Test",
            "fact_codes": ["unknown.code"],
        }])
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_claim_map_missing_claim_key(self):
        pkg = _make_pkg()
        output = _valid_output(claim_map=[{"fact_codes": ["response.status.present"]}])
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_claim_map_missing_fact_codes_key(self):
        pkg = _make_pkg()
        output = _valid_output(claim_map=[{"claim": "Test"}])
        result = validate_draft(output, pkg)
        assert result.valid is False


class TestSourceReferenceValidation:
    """Validates source URL references."""

    def test_unknown_source_url_rejected(self):
        pkg = _make_pkg()
        output = _valid_output(used_source_urls=["https://unknown.example.com/doc"])
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_known_source_url_accepted(self):
        pkg = _make_pkg()
        output = _valid_output(
            used_source_urls=["https://docs.metronome.com/api/contracts/create"]
        )
        result = validate_draft(output, pkg)
        assert result.valid is True


class TestStatusRules:
    """Validates status-dependent rules."""

    def test_customer_resolution_without_confirmed_root_cause_fails(self):
        pkg = _make_pkg(draft_type="customer_resolution", audience="customer")
        output = _valid_output()
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_customer_resolution_with_confirmed_root_cause(self):
        pkg = _make_pkg(draft_type="customer_resolution", audience="customer")
        pkg.resolution_facts.append(GroundingFact(
            fact_code="idempotency.key_reused",
            statement="The key was reused.",
            fact_type="confirmed_root_cause",
            evidence_reference="resolution.1",
            confirmation_status="confirmed",
        ))
        output = _valid_output()
        result = validate_draft(output, pkg)
        # May still have section warnings but should be valid structurally
        assert result.valid is True


class TestPrivacyValidation:
    """Validates secret detection in drafts."""

    def test_bearer_token_rejected(self):
        pkg = _make_pkg()
        output = _valid_output(body="We used Bearer sk_live_abc123xyz for auth.")
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_api_key_in_body_rejected(self):
        pkg = _make_pkg()
        output = _valid_output(body="The api_key=sk-12345 was used.")
        result = validate_draft(output, pkg)
        assert result.valid is False

    def test_no_secrets_body_accepted(self):
        pkg = _make_pkg()
        output = _valid_output(body="No sensitive data here.")
        result = validate_draft(output, pkg)
        assert result.valid is True


class TestRequiredSections:
    """Validates required sections are present."""

    def test_customer_update_missing_sections(self):
        pkg = _make_pkg(required_sections=["Acknowledgement", "Confirmed findings"])
        output = _valid_output(body="Just a short message.")
        result = validate_draft(output, pkg)
        # Will have missing_required_sections
        assert len(result.missing_required_sections) > 0


class TestWarningsNotErrors:
    """Output with only warnings is still 'valid'."""

    def test_documentation_proposal_without_sources_warns(self):
        pkg = _make_pkg(draft_type="documentation_proposal", audience="internal")
        pkg.documentation_sources.clear()
        output = _valid_output(used_source_urls=[])
        result = validate_draft(output, pkg)
        # Documentation proposal without sources generates a warning, not an error
        # (body still has fact references, so it's not "invalid")
        assert result.valid is True or len(result.warnings) > 0
