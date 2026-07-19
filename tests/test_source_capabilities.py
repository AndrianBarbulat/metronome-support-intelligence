from src.support.models import TicketDocumentationSource
from src.support.source_capabilities import (
    find_best_source_for_capability,
    infer_capabilities,
    purpose_for_capability,
    query_for_capability,
    source_satisfies_capability,
)


def source(title: str, score: float = 1.0, usage: str = "supporting"):
    return TicketDocumentationSource(title, f"https://example.com/{title}", None, score, usage_type=usage)


def test_infer_idempotency_capability():
    assert infer_capabilities(source("API idempotency")) == ["idempotency"]


def test_source_satisfies_capability_by_title():
    assert source_satisfies_capability(source("Search events"), "event_search")


def test_find_best_source_prefers_primary_then_score():
    supporting = source("Get a contract", 10.0, "supporting")
    primary = source("Get a contract", 1.0, "primary")

    assert find_best_source_for_capability([supporting, primary], "contract_retrieval") is primary


def test_capability_has_purpose_and_query_hint():
    assert purpose_for_capability("invoice_verification") == "final_state"
    assert "invoice" in query_for_capability("invoice_verification")
