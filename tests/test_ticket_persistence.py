import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.database.repository import DocumentationRepository
from src.support.analyzer import analyze_support_ticket
from src.support.models import SupportTicketInput
from src.support.ticket_parser import load_ticket_from_json


def test_persistence_stores_concept_decisions_and_source_capabilities(tmp_path):
    db = tmp_path / "docs.db"
    shutil.copyfile(Path("data/metronome_docs.db"), db)
    ticket = load_ticket_from_json(Path("data/examples/contract_409.json"))

    analyze_support_ticket(ticket, db, persist=True)

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT concept_decisions_json, merged_concept_groups_json FROM support_ticket_analyses").fetchone()
    link = conn.execute("SELECT source_capabilities_json FROM support_ticket_document_links").fetchone()
    conn.close()

    assert "generic.capture_complete_request" in row[0]
    assert "engineering_escalation" in row[1]
    assert json.loads(link[0]) is not None


def test_original_secrets_never_persist(tmp_path):
    db = tmp_path / "docs.db"
    shutil.copyfile(Path("data/metronome_docs.db"), db)
    ticket = SupportTicketInput(
        external_ticket_id="secret",
        subject="Auth",
        customer_message="token sk_test_secret should be hidden",
        http_method="POST",
        endpoint_path="/v1/contracts/create",
        request_headers={"Authorization": "Bearer raw-secret-token"},
        response_status=401,
        response_body={"message": "Unauthorized"},
    )

    analyze_support_ticket(ticket, db, persist=True)

    raw = db.read_bytes()
    assert b"raw-secret-token" not in raw
    assert b"sk_test_secret" not in raw


def test_atomic_persistence_rolls_back_on_failure(tmp_path):
    db = tmp_path / "docs.db"
    repo = DocumentationRepository(db)
    repo.initialize_schema()
    ticket = SupportTicketInput(subject="x")
    report = analyze_support_ticket(ticket, Path("data/metronome_docs.db"), persist=False)
    report.documentation_sources[0].page_title = None

    with pytest.raises(sqlite3.IntegrityError):
        repo.persist_ticket_analysis(ticket, report, "test")

    count = repo._get_conn().execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0]
    repo.close()
    assert count == 0


def test_schema_migration_adds_phase44_columns(tmp_path):
    repo = DocumentationRepository(tmp_path / "docs.db")
    repo.initialize_schema()
    conn = repo._get_conn()

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(support_ticket_analyses)").fetchall()}
    repo.close()

    assert "concept_decisions_json" in columns
    assert "merged_concept_groups_json" in columns
