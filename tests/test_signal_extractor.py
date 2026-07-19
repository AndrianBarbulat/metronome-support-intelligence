from src.support.models import SupportTicketInput
from src.support.signal_extractor import extract_signals


def test_extract_signals_prefers_explicit_method_and_endpoint():
    signals = extract_signals(SupportTicketInput(
        http_method="post",
        endpoint_path="/v1/contracts/create",
        response_status=409,
    ))

    assert signals.http_method == "POST"
    assert signals.endpoint_path == "/v1/contracts/create"
    assert signals.product_area == "contracts"
    assert signals.status_code == 409


def test_extract_signals_infers_endpoint_from_text():
    signals = extract_signals(SupportTicketInput(
        subject="POST /v1/ingest fails",
        customer_message="usage broken",
    ))

    assert signals.endpoint_path == "/v1/ingest"
    assert signals.product_area == "usage"


def test_extract_signals_reads_request_and_response_fields():
    signals = extract_signals(SupportTicketInput(
        request_body={"transaction_id": "tx", "event_type": "compute"},
        response_body={"message": "ok", "code": 200},
    ))

    assert signals.request_fields == ["transaction_id", "event_type"]
    assert signals.response_fields == ["message", "code"]
    assert "transaction_id" in signals.technical_tokens


def test_extract_signals_reads_list_body_fields():
    signals = extract_signals(SupportTicketInput(
        request_body=[{"customer_id": "cust", "timestamp": "2026-07-19T10:00:00Z"}],
    ))

    assert signals.request_fields == ["customer_id", "timestamp"]


def test_extract_signals_detects_error_terms_and_timestamps():
    signals = extract_signals(SupportTicketInput(
        customer_message="400 invalid at 2026-07-19T10:00:00 and duplicate external_id",
    ))

    assert "400" in signals.error_terms
    assert "invalid" in signals.error_terms
    assert signals.timestamps == ["2026-07-19T10:00:00"]


def test_extract_signals_preserves_expected_and_actual_behavior():
    signals = extract_signals(SupportTicketInput(
        expected_behavior="Usage should bill",
        actual_behavior="Invoice is zero",
    ))

    assert signals.expected_behavior == "Usage should bill"
    assert signals.actual_behavior == "Invoice is zero"


def test_extract_signals_maps_natural_language_usage_question():
    signals = extract_signals(SupportTicketInput(
        customer_message=(
            "Our ai_usage event was accepted, but no charge appeared. "
            "We sent token_cost_usd while the billable metric expects cost_usd."
        ),
    ))

    assert signals.product_area == "usage"
    assert signals.probable_operation == "ingest"
    assert "ai_usage" in signals.technical_tokens
    assert "token_cost_usd" in signals.technical_tokens
    assert "cost_usd" in signals.technical_tokens
