import json

import pytest

from src.support.models import SupportTicketInput
from src.support.ticket_parser import TicketParseError, load_ticket_from_json


def test_load_ticket_from_json_maps_all_supported_fields(tmp_path):
    path = tmp_path / "ticket.json"
    path.write_text(json.dumps({
        "external_ticket_id": "T-1",
        "subject": "Subject",
        "customer_message": "Message",
        "http_method": "POST",
        "endpoint_path": "/v1/ingest",
        "request_headers": {"Authorization": "Bearer token"},
        "request_body": {"transaction_id": "tx_1"},
        "response_status": 200,
        "response_headers": {"x-request-id": "req_1"},
        "response_body": {"status": "accepted"},
        "logs": "log",
        "expected_behavior": "bill",
        "actual_behavior": "not billed",
        "created_at": "2026-07-19T10:00:00Z"
    }), encoding="utf-8")

    ticket = load_ticket_from_json(path)

    assert isinstance(ticket, SupportTicketInput)
    assert ticket.external_ticket_id == "T-1"
    assert ticket.request_body == {"transaction_id": "tx_1"}
    assert ticket.response_status == 200
    assert ticket.actual_behavior == "not billed"


def test_load_ticket_from_json_rejects_missing_file(tmp_path):
    with pytest.raises(TicketParseError):
        load_ticket_from_json(tmp_path / "missing.json")


def test_load_ticket_from_json_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(TicketParseError):
        load_ticket_from_json(path)


def test_load_ticket_from_json_rejects_non_object(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(TicketParseError):
        load_ticket_from_json(path)
