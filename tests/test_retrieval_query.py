from src.support.models import ExtractedTicketSignals
from src.support.retrieval_query import build_retrieval_plan


def test_contract_409_plan_includes_idempotency_and_contract_retrieval_queries():
    plan = build_retrieval_plan(ExtractedTicketSignals(
        product_area="contracts",
        http_method="POST",
        endpoint_path="/v1/contracts/create",
        status_code=409,
        technical_tokens=["uniqueness_key"],
    ))

    queries = " ".join(plan.all_queries()).lower()
    assert "/v1/contracts/create" in queries
    assert "idempotency" in queries
    assert "get contract" in queries


def test_usage_plan_includes_event_search_metric_and_invoice_queries():
    plan = build_retrieval_plan(ExtractedTicketSignals(
        product_area="usage",
        http_method="POST",
        endpoint_path="/v1/ingest",
    ))

    queries = " ".join(plan.all_queries()).lower()
    assert "search events" in queries
    assert "billable metric" in queries
    assert "invoice" in queries


def test_auth_plan_includes_authentication_query():
    plan = build_retrieval_plan(ExtractedTicketSignals(status_code=401))

    assert any("authentication" in q.lower() for q in plan.all_queries())


def test_retrieval_plan_deduplicates_equivalent_queries():
    plan = build_retrieval_plan(ExtractedTicketSignals(
        product_area="usage",
        probable_operation="ingest",
        http_method="POST",
        endpoint_path="/v1/ingest",
        technical_tokens=["transaction_id", "transaction_id"],
    ))

    assert len(plan.all_queries()) == len(set(plan.all_queries()))
