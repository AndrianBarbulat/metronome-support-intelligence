"""Tests for the high-risk claim checker."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from datetime import datetime, timezone

from src.drafting.claim_checker import check_high_risk_claims
from src.drafting.models import (
    DraftGroundingPackage,
    GroundingFact,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _make_pkg(**overrides):
    kwargs = {
        "ticket_id": 1,
        "analysis_id": 1,
        "resolution_id": None,
        "feedback_id": None,
        "draft_type": "customer_update",
        "audience": "customer",
        "tone": "professional",
        "created_at": _utc_now(),
    }
    kwargs.update(overrides)
    pkg = DraftGroundingPackage(**kwargs)
    pkg.observed_facts.append(GroundingFact(
        fact_code="response.status.present",
        statement="Response returned HTTP 409.",
        fact_type="response_evidence",
        evidence_reference="ticket.1",
        confirmation_status="observed",
    ))
    pkg.hypotheses.append(GroundingFact(
        fact_code="hyp.uniqueness",
        statement="Uniqueness key may have been reused.",
        fact_type="hypothesis",
        evidence_reference="ticket.1",
        confirmation_status="unconfirmed",
    ))
    return pkg


class TestHighRiskClaims:
    """Validate detection of high-risk unsupported claims."""

    def test_confirmed_root_cause_with_unconfirmed_fact(self):
        pkg = _make_pkg()
        body = "The root cause was the uniqueness key reused."
        claim_map = [{
            "claim": "The root cause was the uniqueness key reused.",
            "fact_codes": ["hyp.uniqueness"],
        }]
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) > 0

    def test_hedged_claim_not_flagged(self):
        pkg = _make_pkg()
        body = "One possible explanation is that the root cause was the key reuse."
        claim_map = [{
            "claim": "One possible explanation is that the root cause was the key reuse.",
            "fact_codes": ["hyp.uniqueness"],
        }]
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        # Hedged language should be accepted
        assert len(unsupported) == 0

    def test_no_high_risk_claim_in_body_passes(self):
        pkg = _make_pkg()
        body = "We are investigating your issue."
        claim_map: list = []
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) == 0

    def test_resolved_without_confirmed_root_cause(self):
        pkg = _make_pkg()
        body = "The issue has been resolved."
        claim_map = [{"claim": "The issue has been resolved.", "fact_codes": ["hyp.uniqueness"]}]
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) > 0

    def test_resolved_with_confirmed_root_cause(self):
        pkg = _make_pkg()
        pkg.resolution_facts.append(GroundingFact(
            fact_code="idempotency.key_reused",
            statement="Key was reused.",
            fact_type="confirmed_root_cause",
            evidence_reference="resolution.1",
            confirmation_status="confirmed",
        ))
        body = "The issue has been resolved."
        claim_map = [{"claim": "The issue has been resolved.", "fact_codes": ["idempotency.key_reused"]}]
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) == 0

    def test_guarantee_claim_detected(self):
        pkg = _make_pkg()
        body = "Metronome guarantees the endpoint requires idempotency keys."
        claim_map = [{
            "claim": "Metronome guarantees the endpoint requires idempotency keys.",
            "fact_codes": ["response.status.present"],
        }]
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) >= 1

    def test_definitely_unconfirmed_flagged(self):
        pkg = _make_pkg()
        body = "The uniqueness key was definitely reused."
        claim_map = [{
            "claim": "The uniqueness key was definitely reused.",
            "fact_codes": ["hyp.uniqueness"],
        }]
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) > 0

    def test_empty_claim_map_safe(self):
        pkg = _make_pkg()
        body = "No claims made."
        claim_map: list = []
        unsupported = check_high_risk_claims(body, claim_map, pkg)
        assert len(unsupported) == 0