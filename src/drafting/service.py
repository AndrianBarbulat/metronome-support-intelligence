"""Grounded drafting service — the main entry point for draft generation."""

from __future__ import annotations

import json
from pathlib import Path

from src.database.repository import DocumentationRepository
from src.drafting.models import (
    DraftGroundingPackage,
    GeneratedDraft,
    SUPPORTED_DRAFT_TYPES,
    DRAFT_DECISIONS,
)
from src.drafting.grounding_factory import build_grounding_package
from src.drafting.prompts import build_system_instruction, get_prompt_version
from src.drafting.validator import validate_draft
from src.drafting.source_validator import validate_documentation_sources
from src.drafting.providers.base import DraftingProvider
from src.drafting.providers.mock import MockDraftingProvider
from src.drafting.providers.errors import (
    DraftingProviderError,
    DraftingConfigurationError,
)


_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "used_fact_codes": {"type": "array", "items": {"type": "string"}},
        "used_source_urls": {"type": "array", "items": {"type": "string"}},
        "claim_map": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "fact_codes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim", "fact_codes"],
            },
        },
    },
    "required": ["subject", "body", "used_fact_codes", "used_source_urls", "claim_map"],
}


def generate_grounded_draft(
    *,
    draft_type: str,
    database_path: Path,
    ticket_id: int | None = None,
    analysis_id: int | None = None,
    resolution_id: int | None = None,
    feedback_id: int | None = None,
    provider: DraftingProvider | None = None,
    tone: str = "professional",
) -> GeneratedDraft:
    """Generate a draft from persisted Phase 4/5 data."""
    if draft_type not in SUPPORTED_DRAFT_TYPES:
        raise ValueError(f"Unsupported draft type: {draft_type}")

    package = build_grounding_package(
        draft_type=draft_type,
        database_path=database_path,
        ticket_id=ticket_id,
        analysis_id=analysis_id,
        resolution_id=resolution_id,
        feedback_id=feedback_id,
        tone=tone,
    )
    return generate_grounded_draft_from_package(
        grounding_package=package,
        database_path=database_path,
        provider=provider,
        persist=True,
    )


def generate_grounded_draft_from_package(
    *,
    grounding_package: DraftGroundingPackage,
    database_path: Path,
    provider: DraftingProvider | None = None,
    persist: bool = True,
) -> GeneratedDraft:
    """Generate and validate a draft from a closed in-memory grounding package.

    This is the orchestration entry point used by the natural-language assistant.
    It keeps Gemini limited to the facts already produced by the deterministic
    analyzer and documentation index.
    """
    package = grounding_package
    draft_type = package.draft_type
    if draft_type not in SUPPORTED_DRAFT_TYPES:
        raise ValueError(f"Unsupported draft type: {draft_type}")

    if provider is None:
        provider = _default_provider()

    if draft_type == "customer_resolution":
        has_confirmed = any(
            fact.fact_type == "confirmed_root_cause"
            and fact.confirmation_status == "confirmed"
            for fact in package.resolution_facts
        )
        if not has_confirmed:
            raise ValueError(
                "Cannot generate customer_resolution draft: "
                "no confirmed resolution exists."
            )

    system_instruction = build_system_instruction(
        draft_type=draft_type,
        audience=package.audience,
        tone=package.tone,
        required_sections=package.required_sections,
    )
    structured_input = _serialize_package(package)

    try:
        provider_output = provider.generate(
            system_instruction=system_instruction,
            structured_input=structured_input,
            output_schema=_OUTPUT_SCHEMA,
        )
    except DraftingProviderError as exc:
        draft = GeneratedDraft(
            id=None,
            draft_type=draft_type,
            subject=None,
            body=f"Provider error: {exc}",
            provider=provider.provider_name,
            model=provider.model_name,
            prompt_version=get_prompt_version(),
            grounding_package_version=package.package_version,
            validation_status="invalid",
            validation_errors=[str(exc)],
            status="validation_failed",
        )
        if persist:
            _persist_draft(draft, package, database_path)
        return draft

    validation_result = validate_draft(provider_output, package)

    source_urls = [str(url) for url in provider_output.get("used_source_urls", [])]
    if source_urls:
        allowed_sources = [
            str(source.get("source_url", ""))
            for source in package.documentation_sources
            if isinstance(source, dict) and source.get("source_url")
        ]
        source_errors = validate_documentation_sources(
            source_urls,
            database_path,
            allowed_sources=allowed_sources,
        )
        if source_errors:
            validation_result.errors.extend(source_errors)
            validation_result.valid = False

    if not validation_result.valid:
        status = "validation_failed"
        validation_status = "invalid"
    elif validation_result.warnings:
        status = "needs_review"
        validation_status = "warning"
    else:
        status = "needs_review"
        validation_status = "valid"

    claim_map = list(provider_output.get("claim_map", []))
    draft = GeneratedDraft(
        id=None,
        draft_type=draft_type,
        subject=str(provider_output.get("subject") or ""),
        body=str(provider_output.get("body", "")),
        used_fact_codes=list(provider_output.get("used_fact_codes", [])),
        used_source_urls=source_urls,
        claim_map=claim_map,
        provider=provider.provider_name,
        model=provider.model_name,
        prompt_version=get_prompt_version(),
        grounding_package_version=package.package_version,
        validation_status=validation_status,
        validation_errors=validation_result.errors,
        validation_warnings=validation_result.warnings,
        unsupported_claims=validation_result.unsupported_claims,
        status=status,
    )

    if persist:
        _persist_draft(draft, package, database_path)
    return draft


def review_generated_draft(
    *,
    draft_id: int,
    decision: str,
    reviewer: str,
    notes: str | None,
    database_path: Path,
) -> GeneratedDraft:
    """Review a previously generated draft."""
    if decision not in DRAFT_DECISIONS:
        raise ValueError(f"Unsupported review decision: {decision}")

    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        row = repo.get_generated_draft(draft_id)
        if row is None:
            raise ValueError(f"Draft {draft_id} not found.")

        current_status = row["status"]
        if decision == "approve":
            if current_status != "needs_review":
                raise ValueError(
                    f"Cannot approve draft {draft_id}: current status is '{current_status}', "
                    "must be 'needs_review'."
                )
            new_status = "approved"
        elif decision == "reject":
            if current_status != "needs_review":
                raise ValueError(
                    f"Cannot reject draft {draft_id}: current status is '{current_status}', "
                    "must be 'needs_review'."
                )
            new_status = "rejected"
        elif decision == "mark_used":
            if current_status != "approved":
                raise ValueError(
                    f"Cannot mark draft {draft_id} as used: current status is '{current_status}', "
                    "must be 'approved'."
                )
            new_status = "used"
        else:
            new_status = current_status

        repo.update_draft_review_status(draft_id, new_status, reviewer, notes)
        updated_row = repo.get_generated_draft(draft_id)
        if updated_row is None:
            raise ValueError(f"Draft {draft_id} disappeared after review update.")
        return _row_to_draft(updated_row)
    finally:
        repo.close()


def _default_provider() -> DraftingProvider:
    import os

    provider_name = os.getenv("DRAFTING_PROVIDER", "mock").strip().lower()
    if provider_name == "mock":
        return MockDraftingProvider(mode="valid")
    if provider_name == "gemini":
        from src.drafting.providers.gemini import GeminiDraftingProvider

        return GeminiDraftingProvider()
    raise DraftingConfigurationError(f"Unknown DRAFTING_PROVIDER: {provider_name}")


def _serialize_package(package: DraftGroundingPackage) -> dict[str, object]:
    def fact_dict(fact: object) -> dict[str, object]:
        return dict(fact.__dict__) if hasattr(fact, "__dict__") else {}

    return {
        "draft_type": package.draft_type,
        "audience": package.audience,
        "tone": package.tone,
        "ticket_id": package.ticket_id,
        "analysis_id": package.analysis_id,
        "resolution_id": package.resolution_id,
        "feedback_id": package.feedback_id,
        "confirmed_facts": [fact_dict(f) for f in package.confirmed_facts],
        "observed_facts": [fact_dict(f) for f in package.observed_facts],
        "documentation_facts": [fact_dict(f) for f in package.documentation_facts],
        "hypotheses": [fact_dict(f) for f in package.hypotheses],
        "missing_evidence": [fact_dict(f) for f in package.missing_evidence],
        "resolution_facts": [fact_dict(f) for f in package.resolution_facts],
        "feedback_facts": [fact_dict(f) for f in package.feedback_facts],
        "documentation_sources": package.documentation_sources,
        "allowed_identifiers": package.allowed_identifiers,
        "required_sections": package.required_sections,
        "prohibited_claims": package.prohibited_claims,
        "package_version": package.package_version,
    }


def _persist_draft(
    draft: GeneratedDraft,
    package: DraftGroundingPackage,
    database_path: Path,
) -> None:
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        draft_id = repo.create_generated_draft(
            draft_type=draft.draft_type,
            audience=package.audience,
            tone=package.tone,
            subject=draft.subject,
            body=draft.body,
            grounding_package_json=json.dumps(_serialize_package(package), default=str),
            used_fact_codes_json=json.dumps(draft.used_fact_codes),
            used_source_urls_json=json.dumps(draft.used_source_urls),
            claim_map_json=json.dumps(draft.claim_map),
            provider=draft.provider,
            model=draft.model,
            prompt_version=draft.prompt_version,
            grounding_package_version=draft.grounding_package_version,
            validation_status=draft.validation_status,
            validation_errors_json=json.dumps(draft.validation_errors),
            validation_warnings_json=json.dumps(draft.validation_warnings),
            unsupported_claims_json=json.dumps(draft.unsupported_claims),
            status=draft.status,
            ticket_id=package.ticket_id,
            analysis_id=package.analysis_id,
            resolution_id=package.resolution_id,
            feedback_id=package.feedback_id,
        )
        draft.id = draft_id
    finally:
        repo.close()


def _row_to_draft(row) -> GeneratedDraft:
    return GeneratedDraft(
        id=row["id"],
        draft_type=row["draft_type"],
        subject=row["subject"],
        body=row["body"],
        used_fact_codes=json.loads(row["used_fact_codes_json"]),
        used_source_urls=json.loads(row["used_source_urls_json"]),
        claim_map=json.loads(row["claim_map_json"]),
        provider=row["provider"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        grounding_package_version=row["grounding_package_version"],
        validation_status=row["validation_status"],
        validation_errors=json.loads(row["validation_errors_json"]),
        validation_warnings=json.loads(row["validation_warnings_json"]),
        unsupported_claims=json.loads(row["unsupported_claims_json"]),
        status=row["status"],
        generated_at=row["created_at"],
    )
