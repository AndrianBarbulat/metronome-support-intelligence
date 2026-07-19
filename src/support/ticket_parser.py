"""Load support tickets from JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from .models import SupportTicketInput


class TicketParseError(Exception):
    """Raised when a ticket JSON file cannot be parsed."""


def load_ticket_from_json(path: Path) -> SupportTicketInput:
    """Load a :class:`SupportTicketInput` from a JSON file at *path*."""
    if not path.exists():
        raise TicketParseError(f"Ticket file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TicketParseError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise TicketParseError(f"Ticket file {path} does not contain a JSON object.")

    return SupportTicketInput(
        external_ticket_id=data.get("external_ticket_id"),
        subject=data.get("subject", ""),
        customer_message=data.get("customer_message", ""),
        http_method=data.get("http_method"),
        endpoint_path=data.get("endpoint_path"),
        request_headers=data.get("request_headers"),
        request_body=data.get("request_body"),
        response_status=data.get("response_status"),
        response_headers=data.get("response_headers"),
        response_body=data.get("response_body"),
        logs=data.get("logs"),
        expected_behavior=data.get("expected_behavior"),
        actual_behavior=data.get("actual_behavior"),
        created_at=data.get("created_at"),
    )