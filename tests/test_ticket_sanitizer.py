"""Tests for support ticket sanitization."""

from src.support.models import SupportTicketInput
from src.support.sanitizer import sanitize_ticket


def test_authorization_header_redacted():
    t = SupportTicketInput(
        subject="test",
        request_headers={"Authorization": "Bearer secret-token"},
    )
    result = sanitize_ticket(t)
    assert result.sanitized_ticket.request_headers["Authorization"] == "[REDACTED]"
    assert result.redaction_count >= 1


def test_api_key_header_redacted():
    t = SupportTicketInput(
        subject="test",
        request_headers={"X-API-Key": "my-api-key"},
    )
    result = sanitize_ticket(t)
    assert result.sanitized_ticket.request_headers["X-API-Key"] == "[REDACTED]"


def test_content_type_preserved():
    t = SupportTicketInput(
        subject="test",
        request_headers={"Content-Type": "application/json"},
    )
    result = sanitize_ticket(t)
    assert result.sanitized_ticket.request_headers["Content-Type"] == "application/json"


def test_bearer_token_redacted_in_message():
    t = SupportTicketInput(
        subject="issue",
        customer_message="My token is Bearer abc123xyz and it stopped working",
    )
    result = sanitize_ticket(t)
    assert "Bearer abc123xyz" not in result.sanitized_ticket.customer_message
    assert "[REDACTED]" in result.sanitized_ticket.customer_message


def test_jwt_token_redacted():
    t = SupportTicketInput(
        subject="issue",
        customer_message="Using token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.test",
    )
    result = sanitize_ticket(t)
    assert "eyJhbGci" not in result.sanitized_ticket.customer_message


def test_uuid_preserved_default():
    t = SupportTicketInput(
        subject="test",
        customer_message="Customer ID: 4db51251-61de-4bfe-b9ce-495e244f3491",
    )
    result = sanitize_ticket(t)
    assert "4db51251-61de-4bfe-b9ce-495e244f3491" in result.sanitized_ticket.customer_message


def test_uuid_redacted_strict():
    t = SupportTicketInput(
        subject="test",
        customer_message="Customer ID: 4db51251-61de-4bfe-b9ce-495e244f3491",
    )
    result = sanitize_ticket(t, strict=True)
    assert "4db51251-61de-4bfe-b9ce-495e244f3491" not in result.sanitized_ticket.customer_message


def test_original_ticket_not_mutated():
    t = SupportTicketInput(
        subject="test",
        request_headers={"Authorization": "secret"},
    )
    _ = sanitize_ticket(t)
    assert t.request_headers["Authorization"] == "secret"


def test_empty_ticket():
    t = SupportTicketInput(subject="test")
    result = sanitize_ticket(t)
    assert result.redaction_count == 0