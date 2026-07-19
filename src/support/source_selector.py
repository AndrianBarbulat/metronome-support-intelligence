"""Select and classify documentation sources for support tickets.

Classifies sources as primary, supporting, or incidental based on:
- endpoint/operation match
- product area and category
- technical token coverage
- cross-cutting capability detection
- incidental penalty for weak matches
"""

from __future__ import annotations

from src.documentation.reranker import SearchResult

from .models import ExtractedTicketSignals, TicketDocumentationSource
from .source_capabilities import infer_capabilities, purpose_for_capability


def select_ticket_sources(
    results: list[SearchResult],
    signals: ExtractedTicketSignals,
    limit: int = 5,
    required_capabilities: list[str] | None = None,
) -> tuple[list[TicketDocumentationSource], list[TicketDocumentationSource]]:
    required_capabilities = required_capabilities or []
    sources: list[TicketDocumentationSource] = []
    for r in results:
        usage = _classify_usage(r, signals)
        source = TicketDocumentationSource(
            page_title=r.page_title,
            source_url=r.source_url,
            heading=r.heading,
            relevance_score=r.final_score,
            matched_tokens=r.matched_technical_tokens,
            ranking_reasons=r.ranking_reasons,
            usage_type=usage,
            http_method=r.http_method,
            endpoint_path=r.endpoint_path,
        )
        capabilities = infer_capabilities(source)
        source.source_capabilities = capabilities
        source.source_purposes = list(dict.fromkeys(
            purpose_for_capability(capability) for capability in capabilities
        ))
        sources.append(source)

    priority_order = {"primary": 0, "supporting": 1, "incidental": 2}
    sources.sort(key=lambda s: (
        priority_order.get(s.usage_type, 99),
        _operation_rank(s, signals),
        -s.relevance_score,
    ))

    selected = [s for s in sources if s.usage_type != "incidental"]
    discarded = [s for s in sources if s.usage_type == "incidental"]
    capability_selected: list[TicketDocumentationSource] = []
    for capability in required_capabilities:
        matches = [
            s for s in sources
            if capability in s.source_capabilities and s.usage_type != "incidental"
        ]
        if not matches:
            matches = [s for s in sources if capability in s.source_capabilities]
        matches.sort(key=lambda s: (
            0 if s.usage_type == "primary" else 1,
            -s.relevance_score,
        ))
        if matches:
            capability_selected.append(matches[0])

    seen_prefixes: dict[str, int] = {}
    diverse: list[TicketDocumentationSource] = []
    operation_first = [s for s in selected if s.usage_type == "primary"][:2]
    for s in operation_first + capability_selected + selected:
        if any(existing.source_url == s.source_url for existing in diverse):
            continue
        prefix = _page_prefix(s.page_title)
        count = seen_prefixes.get(prefix, 0)
        if count < 2:
            diverse.append(s)
            seen_prefixes[prefix] = count + 1
        else:
            discarded.append(s)

    return diverse[:limit], discarded[:10]


def _classify_usage(result: SearchResult, signals: ExtractedTicketSignals) -> str:
    page = result.page_title.lower()
    endpoint = (result.endpoint_path or "").lower()
    sig_ep = (signals.endpoint_path or "").lower()
    score = result.final_score
    category = result.category or ""

    if signals.product_area == "contracts":
        incidental_contract_pages = ["package", "subscription seats", "historical invoices"]
        if any(term in page for term in incidental_contract_pages):
            return "incidental"

    # ── Primary: exact endpoint match ──
    if sig_ep and endpoint and sig_ep.rstrip("/") == endpoint.rstrip("/"):
        return "primary"

    # ── Primary: operation + area phrase match ──
    if signals.probable_operation and signals.product_area:
        if signals.probable_operation in page and _area_overlap(signals.product_area, page):
            return "primary"

    if signals.product_area == "contracts":
        incidental_contract_pages = ["create a package", "subscription seats", "historical invoices"]
        if any(term in page for term in incidental_contract_pages):
            return "incidental"

    # ── Primary: API reference with exact category match and high score ──
    if result.document_type == "api_reference" and score >= 3.0:
        if signals.product_area and _category_matches(category, signals.product_area):
            return "primary"

    # ── Supporting: cross-cutting capability docs ──
    supporting_capabilities = ["idempotency", "authentication", "pagination", "status code", "webhook"]
    if any(sig in page for sig in supporting_capabilities):
        if score > 1.0:
            return "supporting"

    # ── Supporting: same area, different operation ──
    if signals.product_area and _category_matches(category, signals.product_area):
        return "supporting"

    # ── Incidental: weak score ──
    if score < 2.0:
        return "incidental"

    # ── Incidental: different category ──
    if signals.product_area and category and not _category_matches(category, signals.product_area):
        return "incidental"

    # ── Incidental: matched only common fields ──
    common_fields = {"customer_id", "starting_at", "product_id", "timestamp"}
    matched = set(t.lower() for t in (result.matched_technical_tokens or []))
    if matched and matched.issubset(common_fields):
        if score < 5.0:
            return "incidental"

    return "supporting"


def _operation_rank(source: TicketDocumentationSource, signals: ExtractedTicketSignals) -> int:
    if signals.endpoint_path and source.endpoint_path:
        if signals.endpoint_path.rstrip("/") == source.endpoint_path.rstrip("/"):
            if not signals.http_method or not source.http_method or signals.http_method == source.http_method:
                return 0
    title = source.page_title.lower()
    endpoint = signals.endpoint_path or ""
    if signals.product_area == "customers" and endpoint.endswith("/customers/create"):
        if title.startswith("create a customer"):
            return 0
    if signals.product_area == "contracts" and endpoint.endswith("/contracts/create"):
        if title.startswith("create a contract"):
            return 0
    if signals.product_area == "usage" and endpoint.endswith("/ingest"):
        if title.startswith("ingest events"):
            return 0
    return 1


def _category_matches(category: str, product_area: str) -> bool:
    return category.replace("-", "_") == product_area.replace("-", "_")


def _area_overlap(area: str, page_title: str) -> bool:
    mapped = {
        "contracts": "contract", "customers": "customer",
        "billable-metrics": "billable metric", "billable_metrics": "billable metric",
        "credits-and-commits": "commit", "credits_and_commits": "commit",
        "rate-cards": "rate card", "rate_cards": "rate card",
        "usage": "ingest", "alerts": "alert", "invoices": "invoice",
        "notifications": "notification", "products": "product",
        "packages": "package", "security": "audit",
    }
    expected = mapped.get(area, area)
    return expected in page_title


def _page_prefix(title: str) -> str:
    prefixes = {
        "create a contract": "contract-create", "get a contract": "contract-get",
        "list customer contracts": "contract-list", "amend a contract": "contract-amend",
        "archive a contract": "contract-archive", "edit a contract": "contract-edit",
        "create a customer": "customer-create", "get a customer": "customer-get",
        "list customers": "customer-list", "archive a customer": "customer-archive",
        "ingest events": "usage-ingest", "send usage events": "usage-send",
        "search events": "usage-search",
        "create a threshold": "alert-create", "create a billable metric": "metric-create",
        "get a billable metric": "metric-get",
        "create a package": "package-create", "create a product": "product-create",
        "create a credit": "credit-create", "list invoices": "invoice-list",
        "get an invoice": "invoice-get",
    }
    for key, val in prefixes.items():
        if title.lower().startswith(key):
            return val
    return title[:20].lower()
