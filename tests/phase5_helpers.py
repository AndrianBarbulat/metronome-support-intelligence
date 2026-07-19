import shutil
from pathlib import Path

from src.database.repository import DocumentationRepository
from src.support.analyzer import analyze_support_ticket
from src.support.models import (
    ExtractedTicketSignals,
    InvestigationHypothesis,
    InvestigationObservation,
    TicketDocumentationSource,
    TicketInvestigationReport,
)
from src.support.resolution_models import TicketResolutionInput
from src.support.ticket_parser import load_ticket_from_json


def make_report(
    ticket_id: int = 1,
    hypotheses: list[InvestigationHypothesis] | None = None,
    observations: list[InvestigationObservation] | None = None,
    sources: list[TicketDocumentationSource] | None = None,
    signals: ExtractedTicketSignals | None = None,
) -> TicketInvestigationReport:
    return TicketInvestigationReport(
        ticket_id=ticket_id,
        summary="Investigation summary",
        sanitized=True,
        signals=signals or ExtractedTicketSignals(
            product_area="contracts",
            http_method="POST",
            endpoint_path="/v1/contracts/create",
            status_code=409,
            identifiers={"customer_id": ["cust_123"]},
        ),
        observations=observations or [
            InvestigationObservation(
                statement="The request contains a uniqueness key for cust_123.",
                evidence_type="request",
                observation_code="request.field.uniqueness_key.present",
            )
        ],
        hypotheses=hypotheses or [
            InvestigationHypothesis(
                title="The uniqueness key may have been used.",
                explanation="HTTP 409 can indicate an earlier operation.",
                hypothesis_code="contract.409.uniqueness",
            )
        ],
        documentation_sources=sources or [
            TicketDocumentationSource(
                page_title="Create a contract",
                source_url="https://docs.metronome.com/create-contract",
                heading="Create",
                relevance_score=1.0,
                usage_type="primary",
            ),
            TicketDocumentationSource(
                page_title="API idempotency",
                source_url="https://docs.metronome.com/idempotency",
                heading="Uniqueness keys",
                relevance_score=0.9,
                usage_type="error_behavior",
            ),
        ],
    )


def make_resolution(**overrides) -> TicketResolutionInput:
    data = {
        "ticket_id": 1,
        "analysis_id": 1,
        "resolution_status": "confirmed",
        "root_cause_code": "idempotency.previous_operation_succeeded",
        "root_cause_category": "idempotency",
        "root_cause_summary": "The previous operation succeeded.",
        "root_cause_details": "The uniqueness key was reused after the original request succeeded.",
        "resolution_summary": "Use the existing contract instead of retrying the same operation.",
        "resolution_steps": ["Retrieved the existing contract."],
        "verification_steps": ["Verify API logs and existing contract."],
        "verification_results": ["API logs showed the existing contract for cust_123."],
        "confirmed_by": "Andrian",
        "confirmed_at": "2026-07-19T12:00:00+00:00",
        "affected_component": "Contracts API",
        "affected_endpoint": "/v1/contracts/create",
        "customer_ids": ["cust_123"],
        "affected_sources": ["Create a contract", "API idempotency"],
    }
    data.update(overrides)
    return TicketResolutionInput(**data)


def persisted_analysis(
    tmp_path,
    ticket_file: str = "data/examples/contract_409.json",
) -> tuple[Path, int, int]:
    db = tmp_path / "docs.db"
    shutil.copyfile(Path("data/metronome_docs.db"), db)

    repo = DocumentationRepository(db)
    try:
        repo.initialize_schema()
        before = repo._get_conn().execute("SELECT COALESCE(MAX(id), 0) FROM support_tickets").fetchone()[0]
    finally:
        repo.close()

    analyze_support_ticket(load_ticket_from_json(Path(ticket_file)), db, persist=True)

    repo = DocumentationRepository(db)
    try:
        ticket_row = repo._get_conn().execute(
            """SELECT id FROM support_tickets
               WHERE id > ?
               ORDER BY id DESC
               LIMIT 1""",
            (before,),
        ).fetchone()
        analysis = repo.get_latest_analysis_for_ticket(ticket_row["id"])
        return db, ticket_row["id"], analysis["id"]
    finally:
        repo.close()
