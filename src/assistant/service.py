"""Connect documentation retrieval, deterministic analysis, and grounded drafting."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from src.database.repository import DocumentationRepository
from src.drafting.config import load_config
from src.drafting.models import DraftGroundingPackage, GroundingFact
from src.drafting.providers.base import DraftingProvider
from src.drafting.providers.mock import MockDraftingProvider
from src.drafting.service import generate_grounded_draft_from_package
from src.support.analyzer import analyze_support_ticket
from src.support.models import SupportTicketInput, TicketInvestigationReport
from src.support.sanitizer import sanitize_ticket

from .models import MetronomeAssistantResult


_ANSWER_REQUIRED_SECTIONS = [
    "Direct answer",
    "What the evidence shows",
    "What remains unconfirmed",
    "Recommended checks",
    "Customer communication",
    "Internal escalation",
    "Sources",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def answer_metronome_question(
    question: str,
    database_path: Path,
    *,
    provider: DraftingProvider | None = None,
    provider_name: str | None = None,
    persist: bool = True,
    tone: str = "clear and technical",
) -> MetronomeAssistantResult:
    """Answer a natural-language Metronome question using the existing pipeline.

    The deterministic analyzer owns retrieval, concept mapping, observations,
    hypotheses, missing evidence, and the investigation checklist. Gemini (or
    the mock provider) receives only the closed grounding package and drafts a
    single response containing the answer and communication outputs.
    """
    load_config()

    cleaned = question.strip()
    if not cleaned:
        raise ValueError("Question or issue must not be empty.")

    ticket = SupportTicketInput(
        subject=_subject_from_question(cleaned),
        customer_message=cleaned,
        actual_behavior=cleaned,
    )
    sanitized_ticket = sanitize_ticket(ticket).sanitized_ticket

    report = analyze_support_ticket(
        ticket=ticket,
        database_path=database_path,
        persist=persist,
    )

    package = build_assistant_grounding_package(
        question=sanitized_ticket.customer_message,
        report=report,
        database_path=database_path,
        tone=tone,
    )

    resolved_provider = provider or _resolve_provider(provider_name)
    draft = generate_grounded_draft_from_package(
        grounding_package=package,
        database_path=database_path,
        provider=resolved_provider,
        persist=persist,
    )

    return MetronomeAssistantResult(
        question=sanitized_ticket.customer_message,
        investigation=report,
        grounding_package=package,
        answer=draft,
    )


def build_assistant_grounding_package(
    *,
    question: str,
    report: TicketInvestigationReport,
    database_path: Path,
    tone: str = "clear and technical",
) -> DraftGroundingPackage:
    """Build an in-memory closed grounding package from an investigation report."""
    analysis_id = _latest_analysis_id(database_path, report.ticket_id)
    pkg = DraftGroundingPackage(
        ticket_id=report.ticket_id,
        analysis_id=analysis_id,
        resolution_id=None,
        feedback_id=None,
        draft_type="support_answer",
        audience="internal",
        tone=tone,
        required_sections=list(_ANSWER_REQUIRED_SECTIONS),
        prohibited_claims=[
            "Do not invent a confirmed root cause.",
            "Do not claim an unresolved issue is fixed.",
            "Do not expose secrets or reconstruct redacted values.",
            "Do not introduce undocumented API behaviour.",
        ],
        created_at=_utc_now(),
    )

    pkg.observed_facts.append(GroundingFact(
        fact_code="question.input",
        statement=f"The submitted question or issue is: {question}",
        fact_type="request_evidence",
        evidence_reference="user.input",
        confirmation_status="observed",
        customer_safe=True,
    ))

    for index, observation in enumerate(report.observations, 1):
        pkg.observed_facts.append(GroundingFact(
            fact_code=observation.observation_code or f"observation.{index}",
            statement=observation.statement,
            fact_type="ticket_observation",
            evidence_reference=observation.evidence_reference or "analysis.observation",
            confirmation_status="observed",
            customer_safe=True,
        ))

    for index, finding in enumerate(report.validation_findings, 1):
        status = "documentation_supported" if finding.status in {"passed", "failed", "warning"} else "unconfirmed"
        pkg.confirmed_facts.append(GroundingFact(
            fact_code=finding.rule_id or f"validation.{index}",
            statement=finding.statement,
            fact_type="validation_finding",
            evidence_reference=finding.evidence or "analysis.validation",
            confirmation_status=status,
            source_url=finding.source_url,
            customer_safe=True,
        ))

    for code in report.selected_concept_codes:
        pkg.confirmed_facts.append(GroundingFact(
            fact_code=f"mapped.{code}",
            statement=f"Mapped investigation concept: {code}",
            fact_type="mapped_concept",
            evidence_reference="analysis.concept_mapping",
            confirmation_status="documentation_supported",
            customer_safe=True,
        ))

    for index, hypothesis in enumerate(report.hypotheses, 1):
        statement = hypothesis.title
        if hypothesis.explanation:
            statement = f"{statement} {hypothesis.explanation}"
        pkg.hypotheses.append(GroundingFact(
            fact_code=hypothesis.hypothesis_code or f"hypothesis.{index}",
            statement=statement,
            fact_type="hypothesis",
            evidence_reference="analysis.hypothesis",
            confirmation_status="unconfirmed",
            customer_safe=True,
        ))

    for index, missing in enumerate(report.missing_evidence, 1):
        pkg.missing_evidence.append(GroundingFact(
            fact_code=f"missing.{_safe_code(missing.field) or index}",
            statement=f"{missing.field}: {missing.reason}",
            fact_type="missing_evidence",
            evidence_reference="analysis.missing_evidence",
            confirmation_status="missing",
            customer_safe=True,
        ))

    for step in report.investigation_steps:
        codes = ", ".join(step.concept_codes) if step.concept_codes else "general"
        pkg.confirmed_facts.append(GroundingFact(
            fact_code=f"checklist.step.{step.order}",
            statement=f"Recommended check {step.order}: {step.action} Reason: {step.reason} Concepts: {codes}",
            fact_type="investigation_step",
            evidence_reference=step.source_url or "analysis.checklist",
            confirmation_status="documentation_supported",
            source_url=step.source_url,
            customer_safe=True,
        ))

    selected_urls: list[str] = []
    for source in report.documentation_sources:
        if source.source_url not in selected_urls:
            selected_urls.append(source.source_url)
            pkg.documentation_sources.append({
                "page_title": source.page_title,
                "source_url": source.source_url,
                "heading": source.heading,
                "relevance_score": source.relevance_score,
                "ranking_reasons": source.ranking_reasons,
                "usage_type": source.usage_type,
            })

    for index, doc_fact in enumerate(_load_documentation_facts(database_path, selected_urls), 1):
        pkg.documentation_facts.append(GroundingFact(
            fact_code=f"documentation.{index}",
            statement=doc_fact["statement"],
            fact_type="documentation_fact",
            evidence_reference=doc_fact["heading"] or doc_fact["source_url"],
            confirmation_status="documentation_supported",
            source_url=doc_fact["source_url"],
            customer_safe=True,
        ))

    return pkg


def _resolve_provider(provider_name: str | None) -> DraftingProvider:
    selected = (provider_name or os.getenv("DRAFTING_PROVIDER", "mock")).strip().lower()
    if selected == "mock":
        return MockDraftingProvider(mode="valid")
    if selected == "gemini":
        from src.drafting.providers.gemini import GeminiDraftingProvider

        return GeminiDraftingProvider()
    raise ValueError(f"Unsupported provider: {selected}")


def _subject_from_question(question: str) -> str:
    first_line = question.splitlines()[0].strip()
    if len(first_line) <= 100:
        return first_line
    return first_line[:97].rstrip() + "..."


def _safe_code(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _latest_analysis_id(database_path: Path, ticket_id: int | None) -> int | None:
    if ticket_id is None or not database_path.exists():
        return None
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        row = repo.get_latest_analysis_for_ticket(ticket_id)
        return int(row["id"]) if row is not None else None
    finally:
        repo.close()


def _load_documentation_facts(
    database_path: Path,
    source_urls: list[str],
    *,
    per_source: int = 2,
    max_chars: int = 900,
) -> list[dict[str, str]]:
    if not source_urls or not database_path.exists():
        return []

    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    facts: list[dict[str, str]] = []
    try:
        conn = repo._get_conn()
        for source_url in source_urls:
            rows = conn.execute(
                """SELECT c.heading, c.content
                   FROM documentation_chunks c
                   JOIN documentation_pages p ON p.id = c.page_id
                   WHERE p.source_url = ? AND p.status = 'active'
                   ORDER BY c.chunk_index
                   LIMIT ?""",
                (source_url, per_source),
            ).fetchall()
            for row in rows:
                content = " ".join(str(row["content"] or "").split())
                if not content:
                    continue
                facts.append({
                    "source_url": source_url,
                    "heading": str(row["heading"] or ""),
                    "statement": content[:max_chars],
                })
        return facts
    finally:
        repo.close()
