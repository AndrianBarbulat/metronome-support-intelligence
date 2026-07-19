from __future__ import annotations

from pathlib import Path

import pytest

from src.assistant.service import answer_metronome_question
from src.drafting.providers.mock import MockDraftingProvider
from src.support.models import (
    ExtractedTicketSignals,
    InvestigationHypothesis,
    InvestigationObservation,
    InvestigationStep,
    MissingEvidence,
    TicketInvestigationReport,
)


def _report() -> TicketInvestigationReport:
    return TicketInvestigationReport(
        ticket_id=None,
        summary="Usage was accepted but billing is not confirmed.",
        sanitized=False,
        signals=ExtractedTicketSignals(
            product_area="usage",
            request_fields=["token_cost_usd"],
            technical_tokens=["ai_usage", "token_cost_usd", "cost_usd"],
            actual_behavior="No charge appeared.",
        ),
        observations=[
            InvestigationObservation(
                statement="The submitted event uses event type ai_usage.",
                evidence_type="ticket_field",
                observation_code="usage.event_type.observed",
            )
        ],
        hypotheses=[
            InvestigationHypothesis(
                title="The event may not match the billable metric property configuration.",
                explanation="The submitted property differs from the expected property.",
                hypothesis_code="usage.property_filter_mismatch",
            )
        ],
        missing_evidence=[
            MissingEvidence(
                field="billable metric configuration",
                priority="high",
                reason="The configured property filters must be compared with the event.",
            )
        ],
        investigation_steps=[
            InvestigationStep(
                order=1,
                concept_codes=["usage.compare_metric_properties"],
                action="Compare the event properties with the billable metric configuration.",
                reason="Exact property matching determines whether accepted usage is billable.",
            )
        ],
        selected_concept_codes=["usage.compare_metric_properties"],
    )


def test_answer_metronome_question_connects_analysis_and_grounded_drafting(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("src.assistant.service.analyze_support_ticket", lambda **kwargs: _report())

    result = answer_metronome_question(
        "Our ai_usage event was accepted, but no charge appeared.",
        tmp_path / "unused.db",
        provider=MockDraftingProvider(mode="valid"),
        persist=False,
    )

    assert result.mapped_concepts == ["usage.compare_metric_properties"]
    assert result.answer.draft_type == "support_answer"
    assert "## Direct Answer" in result.answer.body
    assert "## Customer Communication" in result.answer.body
    assert "## Internal Escalation" in result.answer.body
    assert result.answer.validation_status in {"valid", "warning"}
    assert not result.answer.validation_errors


def test_answer_metronome_question_rejects_empty_input(tmp_path: Path):
    with pytest.raises(ValueError, match="must not be empty"):
        answer_metronome_question(
            "   ",
            tmp_path / "unused.db",
            provider=MockDraftingProvider(mode="valid"),
            persist=False,
        )
