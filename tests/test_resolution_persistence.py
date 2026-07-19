import json

from src.database.repository import DocumentationRepository
from src.support.resolution_service import confirm_ticket_resolution

from tests.phase5_helpers import make_resolution, persisted_analysis


def test_schema_contains_phase5_tables(tmp_path):
    repo = DocumentationRepository(tmp_path / "docs.db")
    repo.initialize_schema()
    conn = repo._get_conn()

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    repo.close()

    assert "support_ticket_resolutions" in tables
    assert "support_resolution_identifiers" in tables
    assert "support_hypothesis_outcomes" in tables
    assert "support_regression_cases" in tables
    assert "support_feedback_items" in tables


def test_resolution_identifiers_are_stored(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    confirmed = confirm_ticket_resolution(
        make_resolution(
            ticket_id=ticket_id,
            analysis_id=analysis_id,
            request_ids=["req_123"],
            contract_ids=["contract_123"],
        ),
        db,
    )

    repo = DocumentationRepository(db)
    try:
        rows = repo._get_conn().execute(
            "SELECT identifier_type, identifier_value FROM support_resolution_identifiers WHERE resolution_id = ?",
            (confirmed.id,),
        ).fetchall()
    finally:
        repo.close()

    pairs = {(row["identifier_type"], row["identifier_value"]) for row in rows}
    assert ("request_id", "req_123") in pairs
    assert ("contract_id", "contract_123") in pairs


def test_hypothesis_outcomes_are_persisted(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    confirmed = confirm_ticket_resolution(make_resolution(ticket_id=ticket_id, analysis_id=analysis_id), db)

    repo = DocumentationRepository(db)
    try:
        rows = repo._get_conn().execute(
            "SELECT hypothesis_code, outcome FROM support_hypothesis_outcomes WHERE resolution_id = ?",
            (confirmed.id,),
        ).fetchall()
    finally:
        repo.close()

    assert ("contract.409.uniqueness", "partially_confirmed") in {
        (row["hypothesis_code"], row["outcome"]) for row in rows
    }


def test_regression_case_is_persisted(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)

    confirmed = confirm_ticket_resolution(make_resolution(ticket_id=ticket_id, analysis_id=analysis_id), db)

    repo = DocumentationRepository(db)
    try:
        row = repo._get_conn().execute(
            "SELECT case_code, expected_behavior_json FROM support_regression_cases WHERE resolution_id = ?",
            (confirmed.id,),
        ).fetchone()
    finally:
        repo.close()

    assert row["case_code"] == "idempotency-previous_operation_succeeded"
    assert json.loads(row["expected_behavior_json"])["response_status"] == 409


def test_feedback_listing_filters_by_status_and_gap_code(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)
    confirmed = confirm_ticket_resolution(make_resolution(ticket_id=ticket_id, analysis_id=analysis_id), db)

    repo = DocumentationRepository(db)
    try:
        rows = repo.list_feedback_items(status="needs_review", gap_code="docs.missing_troubleshooting")
    finally:
        repo.close()

    assert len(rows) == 1
    assert rows[0]["resolution_id"] == confirmed.id


def test_resolution_details_include_related_records(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)
    confirm_ticket_resolution(make_resolution(ticket_id=ticket_id, analysis_id=analysis_id), db)

    repo = DocumentationRepository(db)
    try:
        details = repo.get_resolution_details_for_ticket(ticket_id)
    finally:
        repo.close()

    assert details["resolution"] is not None
    assert details["outcomes"]
    assert details["regression_cases"]
    assert details["feedback_items"]
