"""Build multi-query retrieval plans for ticket investigation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ExtractedTicketSignals


@dataclass
class TicketRetrievalPlan:
    primary_queries: list[str] = field(default_factory=list)
    supporting_queries: list[str] = field(default_factory=list)
    field_queries: list[str] = field(default_factory=list)
    verification_queries: list[str] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)

    def all_queries(self) -> list[str]:
        return (self.primary_queries + self.supporting_queries +
                self.field_queries + self.verification_queries)


def build_retrieval_plan(signals: ExtractedTicketSignals) -> TicketRetrievalPlan:
    """Build a multi-query retrieval plan from extracted signals."""
    plan = TicketRetrievalPlan()

    # ── Primary operation queries ──
    primary_parts: list[str] = []
    if signals.http_method:
        primary_parts.append(signals.http_method)
    if signals.endpoint_path:
        primary_parts.append(signals.endpoint_path)
        plan.primary_queries.append(" ".join(primary_parts))
    if signals.probable_operation and signals.product_area:
        plan.primary_queries.append(f"{signals.probable_operation} {signals.product_area.replace('-', ' ')}")

    # ── Supporting / error-behavior queries ──
    if signals.status_code == 409 and "uniqueness_key" in signals.technical_tokens:
        plan.supporting_queries.append("uniqueness_key 409 API idempotency uniqueness key")
    elif signals.status_code == 409:
        plan.supporting_queries.append("409 duplicate conflict API idempotency")
    if signals.status_code in (400, 422):
        plan.supporting_queries.append(f"{signals.status_code} required field missing validation")

    # Cross-cutting support
    if signals.status_code in (401, 403):
        plan.supporting_queries.append("API authentication bearer token")
    if signals.status_code == 429:
        plan.supporting_queries.append("rate limit 429 API status codes")
    if signals.product_area:
        plan.supporting_queries.append(f"{signals.product_area.replace('-', ' ')} overview")

    # ── Field-specific queries ──
    interesting = [t for t in signals.technical_tokens
                   if t not in ("customer_id", "product_id")][:4]
    for token in interesting:
        plan.field_queries.append(f"{token} {signals.product_area or ''}")

    # ── Verification / troubleshooting queries ──
    if signals.product_area == "contracts" and signals.status_code == 409:
        plan.verification_queries.append("get contract list customer contracts")
    if signals.product_area == "contracts":
        plan.verification_queries.append("contract customer_id rate card")
    if signals.product_area == "usage":
        plan.verification_queries.append("search events transaction_id customer")
        plan.verification_queries.append("billable metric event_type properties filters")
        plan.verification_queries.append("contract rate card billing period invoice")
    if signals.product_area == "customers":
        plan.verification_queries.append("get customer list customers ingest alias")

    return _deduplicate_plan(plan)


def _deduplicate_plan(plan: TicketRetrievalPlan) -> TicketRetrievalPlan:
    seen: set[str] = set()
    for attr in ["primary_queries", "supporting_queries", "field_queries", "verification_queries"]:
        deduped: list[str] = []
        for q in getattr(plan, attr):
            normalized = " ".join(sorted(q.lower().split()))
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(q)
        setattr(plan, attr, deduped)
    return plan