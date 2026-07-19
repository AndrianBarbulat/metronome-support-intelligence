"""Grounded drafting service — the main entry point for draft generation."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict

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
from src.drafting.providers.base import DraftingProvider
from src.drafting.providers.mock import MockDraftingProvider
from src.drafting.providers.errors import (
    DraftingProviderError,
    DraftingConfigurationError,
)

# ---------------------------------------------------------------------------
# Provider output schema required from every provider
# ---------------------------------------------------------------------------
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
            },
        },
    },
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
    """Generate a grounded draft following the complete Phase 6 pipeline.

    1. Validate draft type
    2. Build sanitized grounding package
    3. Select prompt template
    4. Call configured provider
    5. Validate structured output
    6. Check claims and sources
    7. Create workflow status
    8. Persist result
    9. Return GeneratedDraft
    """
    if draft_type not in SUPPORTED_DRAFT_TYPES:
        raise ValueError(f"Unsupported draft type: {draft_type}")

    # Resolve provider
    if provider is None:
        provider = _default_provider()

    # Build grounding package
    pkg = build_grounding_package(
        draft_type=draft_type,
        database_path=database_path,
        ticket_id=ticket_id,
        analysis_id=analysis_id,
        resolution_id=resolution_id,
        feedback_id=feedback_id,
        tone=tone,
    )

    # Pre-flight: reject customer_resolution without confirmed resolution
    if draft_type == "customer_resolution":
        has_confirmed = any(
            f.fact_type == "confirmed_root_cause"
            and f.confirmation_status == "confirmed"
            for f in pkg.resolution_facts
        )
        if not has_confirmed:
            raise ValueError(
                "Cannot generate customer_resolution draft: "
                "no confirmed resolution exists."
            )

    # Build system instruction
    system_instruction = build_system_instruction(
        draft_type=draft_type,
        audience=pkg.audience,
        tone=pkg.tone,
        required_sections=pkg.required_sections,
    )

    # Serialize grounding package for provider
    structured_input = _serialize_package(pkg)

    # Call provider
    try:
        provider_output = provider.generate(
            system_instruction=system_instruction,
            structured_input=structured_input,
            output_schema=_OUTPUT_SCHEMA,
        )
    except DraftingProviderError as exc:
        # Create a failed draft record
        draft = GeneratedDraft(
            id=None,
            draft_type=draft_type,
            subject=None,
            body=f"Provider error: {exc}",
            provider=provider.provider_name,
            model=provider.model_name,
            prompt_version=get_prompt_version(),
            grounding_package_version=pkg.package_version,
            validation_status="invalid",
            validation_errors=[str(exc)],
            status="validation_failed",
        )
        _persist_draft(draft, pkg, database_path)
        return draft

    # Validate output
    validation_result = validate_draft(provider_output, pkg)

    # Determine status
    if not validation_result.valid:
        status = "validation_failed"
        validation_status = "invalid"
    elif validation_result.warnings:
        status = "needs_review"
        validation_status = "warning"
    else:
        status = "needs_review"
        validation_status = "valid"

    # Build result
    draft = GeneratedDraft(
        id=None,
        draft_type=draft_type,
        subject=str(provider_output.get("subject") or ""),
        body=str(provider_output.get("body", "")),
        used_fact_codes=list(provider_output.get("used_fact_codes", [])),
        used_source_urls=list(provider_output.get("used_source_urls", [])),
        provider=provider.provider_name,
        model=provider.model_name,
        prompt_version=get_prompt_version(),
        grounding_package_version=pkg.package_version,
        validation_status=validation_status,
        validation_errors=validation_result.errors,
        validation_warnings=validation_result.warnings,
        unsupported_claims=validation_result.unsupported_claims,
        status=status,
    )

    # Persist
    _persist_draft(draft, pkg, database_path)

    return draft


def review_generated_draft(
    *,
    draft_id: int,
    decision: str,
    reviewer: str,
    notes: str | None,
    database_path: Path,
) -> GeneratedDraft:
    """Review a previously generated draft.

    Allowed transitions:
      needs_review → approved
      needs_review → rejected
      approved → used

    Rejected transitions:
      validation_failed → approved
      rejected → used
      generated → used
    """
    if decision not in DRAFT_DECISIONS:
        raise ValueError(f"Unsupported review decision: {decision}")

    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        row = repo.get_generated_draft(draft_id)
        if row is None:
            raise ValueError(f"Draft {draft_id} not found.")

        current_status = row["status"]

        # Validate transitions
        if decision == "approve":
            if current_status != "needs_review":
                raise ValueError(
                    f"Cannot approve draft {draft_id}: current status is '{current_status}', "
                    f"must be 'needs_review'."
                )
            new_status = "approved"
        elif decision == "reject":
            if current_status != "needs_review":
                raise ValueError(
                    f"Cannot reject draft {draft_id}: current status is '{current_status}', "
                    f"must be 'needs_review'."
                )
            new_status = "rejected"
        elif decision == "mark_used":
            if current_status != "approved":
                raise ValueError(
                    f"Cannot mark draft {draft_id} as used: current status is '{current_status}', "
                    f"must be 'approved'."
                )
            new_status = "used"
        else:
            new_status = current_status

        repo.update_draft_review_status(draft_id, new_status, reviewer, notes)

        updated_row = repo.get_generated_draft(draft_id)
        return _row_to_draft(updated_row)
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_provider() -> DraftingProvider:
    """Return the configured default provider."""
    import os

    provider_name = os.getenv("DRAFTING_PROVIDER", "mock")
    if provider_name == "mock":
        return MockDraftingProvider(mode="valid")
    if provider_name == "gemini":
        from src.drafting.providers.gemini import GeminiDraftingProvider

        return GeminiDraftingProvider()
    raise DraftingConfigurationError(
        f"Unknown DRAFTING_PROVIDER: {provider_name}"
    )


def _serialize_package(pkg: DraftGroundingPackage) -> dict[str, object]:
    """Serialize the grounding package to a provider-safe dict."""

    def _fact_dict(f: object) -> dict[str, object]:
        if hasattr(f, "__dict__"):
            d = {}
            for k, v in f.__dict__.items():
                d[k] = v
            return d
        return {}

    return {
        "draft_type": pkg.draft_type,
        "audience": pkg.audience,
        "tone": pkg.tone,
        "ticket_id": pkg.ticket_id,
        "analysis_id": pkg.analysis_id,
        "resolution_id": pkg.resolution_id,
        "feedback_id": pkg.feedback_id,
        "confirmed_facts": [_fact_dict(f) for f in pkg.confirmed_facts],
        "observed_facts": [_fact_dict(f) for f in pkg.observed_facts],
        "documentation_facts": [_fact_dict(f) for f in pkg.documentation_facts],
        "hypotheses": [_fact_dict(f) for f in pkg.hypotheses],
        "missing_evidence": [_fact_dict(f) for f in pkg.missing_evidence],
        "resolution_facts": [_fact_dict(f) for f in pkg.resolution_facts],
        "feedback_facts": [_fact_dict(f) for f in pkg.feedback_facts],
        "documentation_sources": pkg.documentation_sources,
        "allowed_identifiers": pkg.allowed_identifiers,
        "required_sections": pkg.required_sections,
        "package_version": pkg.package_version,
    }


def _persist_draft(
    draft: GeneratedDraft,
    pkg: DraftGroundingPackage,
    database_path: Path,
) -> None:
    """Persist the GeneratedDraft to the database."""
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()
    try:
        draft_id = repo.create_generated_draft(
            draft_type=draft.draft_type,
            audience=pkg.audience,
            tone=pkg.tone,
            subject=draft.subject,
            body=draft.body,
            grounding_package_json=json.dumps(_serialize_package(pkg), default=str),
            used_fact_codes_json=json.dumps(draft.used_fact_codes),
            used_source_urls_json=json.dumps(draft.used_source_urls),
            claim_map_json=json.dumps(
                []  # claim_map is stored but not separately in GeneratedDraft
            ),
            provider=draft.provider,
            model=draft.model,
            prompt_version=draft.prompt_version,
            grounding_package_version=draft.grounding_package_version,
            validation_status=draft.validation_status,
            validation_errors_json=json.dumps(draft.validation_errors),
            validation_warnings_json=json.dumps(draft.validation_warnings),
            unsupported_claims_json=json.dumps(draft.unsupported_claims),
            status=draft.status,
            ticket_id=pkg.ticket_id,
            analysis_id=pkg.analysis_id,
            resolution_id=pkg.resolution_id,
            feedback_id=pkg.feedback_id,
        )
        draft.id = draft_id
    finally:
        repo.close()


def _row_to_draft(row) -> GeneratedDraft:
    """Convert a DB row to a GeneratedDraft."""
    import json as _json

    return GeneratedDraft(
        id=row["id"],
        draft_type=row["draft_type"],
        subject=row["subject"],
        body=row["body"],
        used_fact_codes=_json.loads(row["used_fact_codes_json"]),
        used_source_urls=_json.loads(row["used_source_urls_json"]),
        provider=row["provider"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        grounding_package_version=row["grounding_package_version"],
        validation_status=row["validation_status"],
        validation_errors=_json.loads(row["validation_errors_json"]),
        validation_warnings=_json.loads(row["validation_warnings_json"]),
        unsupported_claims=_json.loads(row["unsupported_claims_json"]),
        status=row["status"],
        generated_at=row["created_at"],
    )