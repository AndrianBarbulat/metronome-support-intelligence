"""Tests for grounding package builder and fact construction."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from datetime import datetime, timezone

from src.drafting.models import (
    DraftGroundingPackage,
    GroundingFact,
    AUDIENCE_FOR_DRAFT_TYPE,
)
from src.drafting.grounding_factory import build_grounding_package

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class TestGroundingPackageBasics:
    """Basic grounding package construction and validation."""

    def test_draft_grounding_package_creation(self):
        pkg = DraftGroundingPackage(
            ticket_id=1,
            analysis_id=2,
            resolution_id=None,
            feedback_id=None,
            draft_type="customer_update",
            audience="customer",
            tone="professional",
            created_at=_utc_now(),
        )
        assert pkg.ticket_id == 1
        assert pkg.draft_type == "customer_update"
        assert pkg.audience == "customer"
        assert pkg.package_version == "1.0.0"

    def test_grounding_fact_creation(self):
        fact = GroundingFact(
            fact_code="request.endpoint.present",
            statement="The request hit POST /v1/contracts/create.",
            fact_type="request_evidence",
            evidence_reference="ticket.1",
            confirmation_status="observed",
        )
        assert fact.fact_code == "request.endpoint.present"
        assert fact.confirmation_status == "observed"
        assert fact.customer_safe is True
        assert fact.internal_only is False

    def test_grounding_fact_internal_only(self):
        fact = GroundingFact(
            fact_code="regression.case.1",
            statement="Regression case details.",
            fact_type="regression_fact",
            evidence_reference="resolution.1",
            confirmation_status="confirmed",
            internal_only=True,
            customer_safe=False,
        )
        assert fact.internal_only is True
        assert fact.customer_safe is False

    def test_hypothesis_unconfirmed_status(self):
        fact = GroundingFact(
            fact_code="hyp.contract.409.uniqueness",
            statement="Possible uniqueness key reuse.",
            fact_type="hypothesis",
            evidence_reference="ticket.1",
            confirmation_status="unconfirmed",
        )
        assert fact.confirmation_status == "unconfirmed"

    def test_missing_evidence_fact(self):
        fact = GroundingFact(
            fact_code="missing.prev_request",
            statement="Previous request result for the same key.",
            fact_type="missing_evidence",
            evidence_reference="ticket.1",
            confirmation_status="missing",
        )
        assert fact.fact_type == "missing_evidence"
        assert fact.confirmation_status == "missing"

    def test_all_fact_lists_empty_by_default(self):
        pkg = DraftGroundingPackage(
            ticket_id=None,
            analysis_id=None,
            resolution_id=None,
            feedback_id=None,
            draft_type="engineering_escalation",
            audience="engineering",
            tone="professional",
        )
        assert pkg.confirmed_facts == []
        assert pkg.observed_facts == []
        assert pkg.hypotheses == []
        assert pkg.missing_evidence == []
        assert pkg.resolution_facts == []
        assert pkg.feedback_facts == []

    def test_allowed_identifiers_serialized(self):
        pkg = DraftGroundingPackage(
            ticket_id=1,
            analysis_id=None,
            resolution_id=None,
            feedback_id=None,
            draft_type="customer_update",
            audience="customer",
            tone="professional",
            allowed_identifiers={"request_id": ["req-123"], "customer_id": ["cust-456"]},
        )
        assert "req-123" in pkg.allowed_identifiers["request_id"]


class TestAudienceAssignment:
    """Audience derivation from draft type."""

    def test_customer_update_is_customer_audience(self):
        assert AUDIENCE_FOR_DRAFT_TYPE["customer_update"] == "customer"

    def test_customer_resolution_is_customer_audience(self):
        assert AUDIENCE_FOR_DRAFT_TYPE["customer_resolution"] == "customer"

    def test_engineering_escalation_is_engineering_audience(self):
        assert AUDIENCE_FOR_DRAFT_TYPE["engineering_escalation"] == "engineering"

    def test_internal_case_summary_is_internal_audience(self):
        assert AUDIENCE_FOR_DRAFT_TYPE["internal_case_summary"] == "internal"

    def test_executive_summary_is_executive_audience(self):
        assert AUDIENCE_FOR_DRAFT_TYPE["executive_summary"] == "executive"


class TestGroundingPackageRejectsInvalidType:
    """The builder must reject unsupported draft types."""

    def test_invalid_draft_type(self):
        with pytest.raises(ValueError, match="Unsupported draft type"):
            build_grounding_package(
                draft_type="nonexistent_draft",
                database_path=DB_PATH,
            )


class TestRequiredSectionsPerType:
    """Each draft type must have required sections."""

    def test_customer_update_has_required_sections(self):
        pkg = DraftGroundingPackage(
            ticket_id=1,
            analysis_id=None,
            resolution_id=None,
            feedback_id=None,
            draft_type="customer_update",
            audience="customer",
            tone="professional",
            required_sections=["Acknowledgement", "Confirmed findings"],
        )
        assert len(pkg.required_sections) >= 2

    def test_engineering_escalation_has_many_sections(self):
        pkg = DraftGroundingPackage(
            ticket_id=1,
            analysis_id=None,
            resolution_id=None,
            feedback_id=None,
            draft_type="engineering_escalation",
            audience="engineering",
            tone="professional",
            required_sections=["Issue summary", "Customer impact", "Specific engineering questions"],
        )
        assert len(pkg.required_sections) >= 3