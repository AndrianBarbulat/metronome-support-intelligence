"""Infer investigation capabilities from documentation sources."""

from __future__ import annotations

from .models import TicketDocumentationSource

CAPABILITY_MAP: dict[str, list[str]] = {
    "contract_creation": [
        "create a contract", "amend a contract", "edit a contract",
        "provision a contract", "create contract",
    ],
    "contract_retrieval": [
        "get a contract", "list customer contracts", "list contracts",
        "get contract", "list all contracts",
    ],
    "idempotency": [
        "api idempotency", "idempotency", "uniqueness key", "uniqueness_key",
    ],
    "event_ingestion": [
        "ingest events", "send usage events", "usage event",
        "high volume", "usage events at scale",
    ],
    "event_search": [
        "search events", "get batched usage", "get usage data",
        "event search",
    ],
    "billable_metric_configuration": [
        "create a billable metric", "billable metric",
        "create billable metric", "streaming billable metric",
        "sql billable metric",
    ],
    "rate_card_configuration": [
        "create a rate card", "rate card", "get a rate schedule",
        "add a rate", "add rates", "rate schedule",
    ],
    "invoice_verification": [
        "get an invoice", "list invoices", "invoice",
        "regenerate an invoice", "list invoice breakdowns",
    ],
    "authentication": [
        "api authentication", "authentication", "bearer",
        "api key", "create a token",
    ],
}


def infer_capabilities(source: TicketDocumentationSource) -> list[str]:
    """Infer investigation capabilities from a documentation source's title and heading."""
    capabilities: list[str] = []
    title_lower = source.page_title.lower()
    heading_lower = (source.heading or "").lower()
    combined = f"{title_lower} {heading_lower}"

    for capability, keywords in CAPABILITY_MAP.items():
        for kw in keywords:
            if kw in combined:
                capabilities.append(capability)
                break

    return list(dict.fromkeys(capabilities))


def source_satisfies_capability(
    source: TicketDocumentationSource, capability: str
) -> bool:
    """Check whether a source satisfies a specific investigation capability."""
    return capability in infer_capabilities(source)


def find_best_source_for_capability(
    sources: list[TicketDocumentationSource],
    capability: str,
) -> TicketDocumentationSource | None:
    """Find the best-matching source for a given capability."""
    candidates = [
        s for s in sources if source_satisfies_capability(s, capability)
    ]
    if not candidates:
        return None
    # Prefer primary, then highest relevance
    candidates.sort(
        key=lambda s: (
            0 if s.usage_type == "primary" else 1,
            -s.relevance_score,
        )
    )
    return candidates[0]