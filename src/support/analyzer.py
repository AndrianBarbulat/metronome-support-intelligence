"""Orchestrate support ticket analysis with adaptive concept-driven investigation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.database.repository import DocumentationRepository
from src.documentation.search import search_documentation
from src.documentation.reranker import SearchResult

from .checklist_builder import build_investigation_checklist, identify_missing_evidence
from .concept_registry import InvestigationConceptRegistry
from .evidence_validator import ALL_PROVIDERS
from .models import (
    InvestigationHypothesis,
    InvestigationStep,
    MissingEvidence,
    SupportTicketInput,
    TicketDocumentationSource,
    TicketInvestigationReport,
    ValidationFinding,
)
from .observation_builder import build_observations
from .retrieval_query import build_retrieval_plan
from .sanitizer import sanitize_ticket
from .signal_extractor import extract_signals
from .source_selector import select_ticket_sources

_registry = InvestigationConceptRegistry()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def analyze_support_ticket(
    ticket: SupportTicketInput,
    database_path: Path,
    analyzer_version: str = "1.0.0",
    persist: bool = True,
) -> TicketInvestigationReport:
    # 1. Sanitize
    sanitization = sanitize_ticket(ticket)
    st = sanitization.sanitized_ticket

    # 2. Extract signals
    signals = extract_signals(st)
    signal_confidence = _calc_signal_confidence(signals)

    # 3. Build multi-query retrieval plan
    plan = build_retrieval_plan(signals)

    # 4. Retrieve documentation with multiple queries
    all_doc_results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for query in plan.all_queries():
        if not query.strip():
            continue
        results = search_documentation(database_path=database_path, query=query, limit=10)
        for r in results:
            if r.source_url not in seen_urls:
                seen_urls.add(r.source_url)
                all_doc_results.append(r)

    retrieval_confidence = _calc_retrieval_confidence(all_doc_results)

    # 5. Run rule providers
    validation_findings, _provider_steps = _run_providers(st, signals, all_doc_results)

    # 6. Select documentation sources
    selected_sources, discarded_sources = select_ticket_sources(all_doc_results, signals, limit=6)
    doc_confidence = _calc_documentation_confidence(selected_sources)

    # 7. Create observations
    observations = build_observations(st, signals, validation_findings, selected_sources)

    # 8. Identify missing evidence
    missing = identify_missing_evidence(st, signals)
    evidence_comp = _calc_evidence_completeness(missing)

    # 9. Generate hypotheses
    hypotheses = _generate_hypotheses(st, signals, all_doc_results, validation_findings)

    # 10. Select, suppress, merge investigation concepts (evidence-aware)
    concepts = _registry.select(
        signals, validation_findings, hypotheses, missing, ticket=st,
    )

    # 11. Build concept-driven checklist with source links
    checklist = build_investigation_checklist(concepts, selected_sources)

    # 12. Summary & confidence
    summary = _build_summary(st, signals, selected_sources)
    investigation_conf = _calc_investigation_confidence(signal_confidence, doc_confidence, evidence_comp, hypotheses)

    report = TicketInvestigationReport(
        ticket_id=None,
        summary=summary,
        sanitized=sanitization.redaction_count > 0,
        signals=signals,
        observations=observations,
        validation_findings=validation_findings,
        hypotheses=hypotheses,
        missing_evidence=missing,
        investigation_steps=checklist,
        documentation_sources=selected_sources,
        discarded_sources=discarded_sources,
        retrieval_query="; ".join(plan.all_queries()),
        retrieval_confidence=retrieval_confidence,
        signal_confidence=signal_confidence,
        documentation_confidence=doc_confidence,
        evidence_completeness=evidence_comp,
        investigation_confidence=investigation_conf,
        generated_at=_utc_now(),
        analyzer_version=analyzer_version,
    )

    if persist:
        repo = DocumentationRepository(database_path)
        try:
            repo.initialize_schema()
            repo.persist_ticket_analysis(ticket=st, report=report, analyzer_version=analyzer_version)
        finally:
            repo.close()

    return report


def _run_providers(ticket, signals, doc_results):
    findings: list[ValidationFinding] = []
    for provider in ALL_PROVIDERS:
        if provider.supports(signals):
            findings.extend(provider.evaluate(ticket, signals, doc_results))
    return findings, []


def _calc_signal_confidence(signals) -> float:
    score = 0.0
    if signals.http_method: score += 0.15
    if signals.endpoint_path: score += 0.25
    if signals.status_code is not None: score += 0.15
    if signals.request_fields: score += 0.15
    if signals.product_area: score += 0.15
    if signals.technical_tokens: score += 0.15
    return min(1.0, score)


def _calc_retrieval_confidence(results) -> float:
    if not results: return 0.0
    avg = sum(r.final_score for r in results) / len(results)
    return min(1.0, max(0.0, avg / 20.0))


def _calc_documentation_confidence(sources) -> float:
    if not sources: return 0.0
    return 0.8 if any(s.usage_type == "primary" for s in sources) else 0.4


def _calc_evidence_completeness(missing) -> float:
    critical = sum(1 for m in missing if m.priority == "critical")
    high = sum(1 for m in missing if m.priority == "high")
    return max(0.0, 1.0 - ((critical * 3 + high) / 20.0))


def _calc_investigation_confidence(sig, doc, ev, hypotheses) -> float:
    base = (sig + doc + ev) / 3.0
    base = max(base, 0.5) if hypotheses else min(base, 0.4)
    return min(1.0, max(0.0, base))


def _generate_hypotheses(ticket, signals, doc_results, findings) -> list[InvestigationHypothesis]:
    hypotheses: list[InvestigationHypothesis] = []

    if signals.status_code == 409 and "uniqueness_key" in signals.request_fields:
        hypotheses.append(InvestigationHypothesis(
            title="The uniqueness key may have been used by an earlier operation.",
            explanation="HTTP 409 Conflict with a uniqueness_key often means the key was already consumed.",
            confidence=min(0.90, 0.30 + 0.25 + 0.20),
            hypothesis_code="contract.409.uniqueness",
        ))
    failed_fields = [f for f in findings if f.status == "failed" and "required" in f.rule_id.lower()]
    if failed_fields:
        hypotheses.append(InvestigationHypothesis(
            title="A required field may be missing from the request.",
            explanation="The API documentation specifies required fields not present.",
            confidence=0.70,
            hypothesis_code="contract.400.missing_field",
        ))
    if signals.product_area == "usage" and ticket.actual_behavior and \
       any(t in ticket.actual_behavior.lower() for t in ("not bill", "zero", "not reflect")):
        hypotheses.append(InvestigationHypothesis(
            title="Usage may be accepted but not matched to a billable metric.",
            explanation="Ingestion succeeds but billing requires matching to an active billable metric and rate card.",
            confidence=0.65,
            hypothesis_code="usage.200.not_billed",
        ))
    return hypotheses[:5]


def _build_summary(ticket, signals, sources) -> str:
    parts: list[str] = []
    if signals.http_method and signals.endpoint_path:
        parts.append(f"{signals.http_method} {signals.endpoint_path} returned")
        parts.append(f"HTTP {signals.status_code}." if signals.status_code else "an error.")
    elif ticket.subject:
        parts.append(ticket.subject.strip() + ".")
    if signals.request_fields and "uniqueness_key" in signals.request_fields:
        parts.append("The request contains a uniqueness_key.")
    parts.append("The cause is not yet confirmed.")
    if sources:
        parts.append(f"Documentation retrieved: {sources[0].page_title}.")
    return " ".join(parts)