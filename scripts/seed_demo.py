#!/usr/bin/env python3
"""Seed the database with three complete demo scenarios for the interview demo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database.repository import DocumentationRepository

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"
EXAMPLES_DIR = _PROJECT_ROOT / "data" / "examples"


def main() -> None:
    print("Seeding demo scenarios...")
    print(f"Database: {DB_PATH}")
    print()

    if not DB_PATH.exists():
        print("Database does not exist. Run scripts/sync_documentation.py first.")
        sys.exit(1)

    repo = DocumentationRepository(DB_PATH)
    repo.initialize_schema()

    # Check if already seeded
    existing = repo.list_generated_drafts()
    if existing:
        print("Demo data already exists. Run scripts/reset_demo.py first.")
        repo.close()
        sys.exit(0)

    try:
        _seed_scenario_1(repo)
        _seed_scenario_2(repo)
        _seed_scenario_3(repo)
        print("Demo scenarios seeded successfully.")
    finally:
        repo.close()


def _seed_scenario_1(repo: DocumentationRepository) -> None:
    """Scenario 1: Contract uniqueness conflict (409)."""
    print("Seeding Scenario 1: Contract uniqueness conflict")

    # Load example ticket
    example_path = EXAMPLES_DIR / "contract_409.json"
    if not example_path.exists():
        print(f"  SKIP: Example not found: {example_path}")
        return

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ticket = data.get("ticket", data)
    from src.support.models import SupportTicketInput
    from src.support.sanitizer import sanitize_ticket
    from src.support.ticket_parser import build_investigation_report

    si = SupportTicketInput(
        external_ticket_id=ticket.get("external_ticket_id", "DEMO-001"),
        subject=ticket.get("subject", "Contract creation returns 409"),
        customer_message=ticket.get("customer_message", ""),
        http_method=ticket.get("http_method"),
        endpoint_path=ticket.get("endpoint_path"),
        request_headers=ticket.get("request_headers"),
        request_body=ticket.get("request_body"),
        response_status=ticket.get("response_status"),
        response_headers=ticket.get("response_headers"),
        response_body=ticket.get("response_body"),
        logs=ticket.get("logs"),
        expected_behavior=ticket.get("expected_behavior"),
        actual_behavior=ticket.get("actual_behavior"),
    )

    try:
        sanitized = sanitize_ticket(si)
        report = build_investigation_report(sanitized.sanitized_ticket, DB_PATH)
        ticket_id = repo.persist_ticket_analysis(sanitized.sanitized_ticket, report, "1.0.0")
        print(f"  Ticket ID: {ticket_id}")
    except Exception as exc:
        print(f"  Warning: Could not create ticket: {exc}")


def _seed_scenario_2(repo: DocumentationRepository) -> None:
    """Scenario 2: Usage accepted but not billed."""
    print("Seeding Scenario 2: Usage accepted but not billed")

    example_path = EXAMPLES_DIR / "usage_accepted_not_billed.json"
    if not example_path.exists():
        print(f"  SKIP: Example not found: {example_path}")
        return

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ticket = data.get("ticket", data)
    from src.support.models import SupportTicketInput
    from src.support.sanitizer import sanitize_ticket
    from src.support.ticket_parser import build_investigation_report

    si = SupportTicketInput(
        external_ticket_id=ticket.get("external_ticket_id", "DEMO-002"),
        subject=ticket.get("subject", "Usage accepted but invoice shows zero"),
        customer_message=ticket.get("customer_message", ""),
        http_method=ticket.get("http_method"),
        endpoint_path=ticket.get("endpoint_path"),
        request_headers=ticket.get("request_headers"),
        request_body=ticket.get("request_body"),
        response_status=ticket.get("response_status"),
        response_headers=ticket.get("response_headers"),
        response_body=ticket.get("response_body"),
        logs=ticket.get("logs"),
        expected_behavior=ticket.get("expected_behavior"),
        actual_behavior=ticket.get("actual_behavior"),
    )

    try:
        sanitized = sanitize_ticket(si)
        report = build_investigation_report(sanitized.sanitized_ticket, DB_PATH)
        ticket_id = repo.persist_ticket_analysis(sanitized.sanitized_ticket, report, "1.0.0")
        print(f"  Ticket ID: {ticket_id}")
    except Exception as exc:
        print(f"  Warning: Could not create ticket: {exc}")


def _seed_scenario_3(repo: DocumentationRepository) -> None:
    """Scenario 3: Contract missing required field."""
    print("Seeding Scenario 3: Contract missing required field")

    example_path = EXAMPLES_DIR / "contract_missing_field.json"
    if not example_path.exists():
        print(f"  SKIP: Example not found: {example_path}")
        return

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ticket = data.get("ticket", data)
    from src.support.models import SupportTicketInput
    from src.support.sanitizer import sanitize_ticket
    from src.support.ticket_parser import build_investigation_report

    si = SupportTicketInput(
        external_ticket_id=ticket.get("external_ticket_id", "DEMO-003"),
        subject=ticket.get("subject", "Contract creation fails with 400"),
        customer_message=ticket.get("customer_message", ""),
        http_method=ticket.get("http_method"),
        endpoint_path=ticket.get("endpoint_path"),
        request_headers=ticket.get("request_headers"),
        request_body=ticket.get("request_body"),
        response_status=ticket.get("response_status"),
        response_headers=ticket.get("response_headers"),
        response_body=ticket.get("response_body"),
        logs=ticket.get("logs"),
        expected_behavior=ticket.get("expected_behavior"),
        actual_behavior=ticket.get("actual_behavior"),
    )

    try:
        sanitized = sanitize_ticket(si)
        report = build_investigation_report(sanitized.sanitized_ticket, DB_PATH)
        ticket_id = repo.persist_ticket_analysis(sanitized.sanitized_ticket, report, "1.0.0")
        print(f"  Ticket ID: {ticket_id}")
    except Exception as exc:
        print(f"  Warning: Could not create ticket: {exc}")


if __name__ == "__main__":
    main()