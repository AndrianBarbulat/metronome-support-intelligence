import sqlite3
from pathlib import Path

import pytest

from src.database.repository import DocumentationRepository
from src.support.analyzer import analyze_support_ticket
from src.support.resolution_service import ResolutionServiceError, confirm_ticket_resolution
from src.support.ticket_parser import load_ticket_from_json

from tests.phase5_helpers import make_resolution, persisted_analysis


def test_confirm_ticket_resolution_returns_complete_result(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    confirmed = confirm_ticket_resolution(
        make_resolution(ticket_id=ticket_id, analysis_id=analysis_id),
        db,
    )

    assert confirmed.id > 0
    assert confirmed.root_cause_code == "idempotency.previous_operation_succeeded"
    assert confirmed.hypothesis_outcomes
    assert confirmed.regression_case is not None
    assert confirmed.feedback_items


def test_ticket_secret_is_not_persisted_during_confirmation(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(
        tmp_path,
        "data/examples/contract_missing_field.json",
    )

    confirm_ticket_resolution(
        make_resolution(
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            root_cause_code="request.missing_required_field",
            root_cause_category="request",
        ),
        db,
    )

    assert b"secret-token-abc123" not in db.read_bytes()


def test_analysis_for_another_ticket_is_rejected(tmp_path):
    db, ticket_id, _analysis_id = persisted_analysis(tmp_path)
    analyze_support_ticket(
        load_ticket_from_json(Path("data/examples/contract_missing_field.json")),
        db,
        persist=True,
    )
    repo = DocumentationRepository(db)
    try:
        other_ticket = repo._get_conn().execute(
            "SELECT id FROM support_tickets WHERE id != ? ORDER BY id DESC LIMIT 1",
            (ticket_id,),
        ).fetchone()
        other_ticket_id = other_ticket["id"]
        other_analysis = repo.get_latest_analysis_for_ticket(other_ticket_id)
        other_analysis_id = other_analysis["id"]
    finally:
        repo.close()

    with pytest.raises(ResolutionServiceError) as excinfo:
        confirm_ticket_resolution(
            make_resolution(ticket_id=ticket_id, analysis_id=other_analysis_id),
            db,
        )

    assert other_ticket_id != ticket_id
    assert "analysis does not belong to the ticket" in str(excinfo.value)


def test_unresolved_resolution_does_not_create_regression_or_feedback(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    confirmed = confirm_ticket_resolution(
        make_resolution(
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            resolution_status="unresolved",
            root_cause_code="insufficient_evidence",
            root_cause_category="insufficient_evidence",
        ),
        db,
    )

    assert confirmed.regression_case is None
    assert confirmed.feedback_items == []


def test_historical_hypothesis_remains_stored_after_resolution(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    confirm_ticket_resolution(make_resolution(ticket_id=ticket_id, analysis_id=analysis_id), db)

    repo = DocumentationRepository(db)
    try:
        analysis = repo.get_latest_analysis_for_ticket(ticket_id)
    finally:
        repo.close()

    assert "contract.409.uniqueness" in analysis["hypotheses_json"]
    assert "idempotency.previous_operation_succeeded" not in analysis["hypotheses_json"]


def test_resolution_persistence_rolls_back_when_feedback_generation_fails(tmp_path, monkeypatch):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    def fail_feedback(*_args, **_kwargs):
        raise RuntimeError("proposal failure")

    monkeypatch.setattr("src.support.resolution_service.build_feedback_items", fail_feedback)

    with pytest.raises(RuntimeError):
        confirm_ticket_resolution(make_resolution(ticket_id=ticket_id, analysis_id=analysis_id), db)

    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM support_ticket_resolutions").fetchone()[0]
    finally:
        conn.close()

    assert count == 0
