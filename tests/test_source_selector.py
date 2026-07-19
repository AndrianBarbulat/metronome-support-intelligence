from src.documentation.reranker import SearchResult
from src.support.models import ExtractedTicketSignals
from src.support.source_selector import select_ticket_sources


def result(title, endpoint=None, category="contracts", score=5.0):
    return SearchResult(
        page_title=title,
        heading=None,
        heading_path=[],
        source_url=f"https://docs.example/{title}.md",
        document_type="api_reference",
        category=category,
        http_method="POST",
        endpoint_path=endpoint,
        chunk_type="operation",
        content_excerpt="",
        content="",
        final_score=score,
    )


def test_exact_operation_source_sorts_first():
    selected, _ = select_ticket_sources([
        result("Create historical invoices", "/v1/contracts/createHistoricalInvoices", score=20),
        result("Create a contract", "/v1/contracts/create", score=5),
    ], ExtractedTicketSignals(product_area="contracts", http_method="POST", endpoint_path="/v1/contracts/create"))

    assert selected[0].page_title == "Create a contract"


def test_incidental_contract_package_source_is_excluded():
    selected, discarded = select_ticket_sources([
        result("Create a package", "/v1/packages/create", score=20),
        result("Create a contract", "/v1/contracts/create", score=5),
    ], ExtractedTicketSignals(product_area="contracts", http_method="POST", endpoint_path="/v1/contracts/create"))

    assert all(s.page_title != "Create a package" for s in selected)
    assert any(s.page_title == "Create a package" for s in discarded)


def test_required_capability_source_is_included():
    selected, _ = select_ticket_sources([
        result("Create a contract", "/v1/contracts/create", score=5),
        result("API idempotency", None, category=None, score=1),
    ], ExtractedTicketSignals(product_area="contracts", http_method="POST", endpoint_path="/v1/contracts/create"),
        required_capabilities=["idempotency"])

    assert any("idempotency" in s.source_capabilities for s in selected)


def test_selected_sources_include_purpose_metadata():
    selected, _ = select_ticket_sources([
        result("Search events", "/v1/events/search", category="usage"),
    ], ExtractedTicketSignals(product_area="usage", http_method="POST", endpoint_path="/v1/ingest"),
        required_capabilities=["event_search"])

    assert selected[0].source_purposes == ["verification"]
