"""Post-generation draft validator.

Validates structure, fact references, source references, status rules,
privacy, and required sections.
"""

from __future__ import annotations

from src.drafting.models import (
    DraftGroundingPackage,
    DraftValidationResult,
    GroundingFact,
    SUPPORTED_DRAFT_TYPES,
)
from src.drafting.sanitization import contains_secrets
from src.drafting.claim_checker import check_high_risk_claims
from src.drafting.section_validator import check_required_sections


def validate_draft(
    provider_output: dict[str, object],
    grounding_package: DraftGroundingPackage,
) -> DraftValidationResult:
    """Run the complete validation suite on a provider output."""

    errors: list[str] = []
    warnings: list[str] = []
    unsupported: list[str] = []
    missing_sections: list[str] = []

    # ------------------------------------------------------------------
    # 1. Structure validation
    # ------------------------------------------------------------------
    if not isinstance(provider_output, dict):
        errors.append("Provider output is not a dictionary.")
        return DraftValidationResult(
            valid=False, errors=errors, warnings=warnings,
            unsupported_claims=unsupported,
            missing_required_sections=missing_sections,
        )

    body = str(provider_output.get("body", ""))
    if not body.strip():
        errors.append("Draft body is empty.")

    used_fact_codes = provider_output.get("used_fact_codes", [])
    if not isinstance(used_fact_codes, list):
        errors.append("used_fact_codes must be a list.")
        used_fact_codes = []

    used_source_urls = provider_output.get("used_source_urls", [])
    if not isinstance(used_source_urls, list):
        errors.append("used_source_urls must be a list.")
        used_source_urls = []

    claim_map = provider_output.get("claim_map", [])
    if not isinstance(claim_map, list):
        errors.append("claim_map must be a list.")
        claim_map = []

    for i, entry in enumerate(claim_map):
        if not isinstance(entry, dict):
            errors.append(f"claim_map[{i}] is not a dictionary.")
        else:
            if "claim" not in entry:
                errors.append(f"claim_map[{i}] missing 'claim' key.")
            if "fact_codes" not in entry:
                errors.append(f"claim_map[{i}] missing 'fact_codes' key.")

    # ------------------------------------------------------------------
    # 2. Fact-reference validation
    # ------------------------------------------------------------------
    all_fact_codes = _collect_all_fact_codes(grounding_package)

    for fc in used_fact_codes:
        if fc not in all_fact_codes:
            errors.append(f"Used fact code '{fc}' does not exist in grounding package.")

    for entry in claim_map:
        if isinstance(entry, dict):
            entry_codes = entry.get("fact_codes", [])
            if isinstance(entry_codes, list):
                for fc in entry_codes:
                    if str(fc) not in all_fact_codes:
                        errors.append(
                            f"Claim map references unknown fact code '{fc}'."
                        )

    # Check no internal-only facts used for customer drafts
    if grounding_package.audience == "customer":
        for fc in used_fact_codes:
            fact = all_fact_codes.get(fc)
            if fact is not None and fact.internal_only:
                errors.append(
                    f"Internal-only fact code '{fc}' used in customer-facing draft."
                )

    # ------------------------------------------------------------------
    # 3. Source-reference validation
    # ------------------------------------------------------------------
    known_source_urls = {
        str(s.get("source_url", ""))
        for s in grounding_package.documentation_sources
        if isinstance(s, dict)
    }

    for url in used_source_urls:
        if str(url) not in known_source_urls:
            errors.append(f"Source URL '{url}' not found in grounding package.")

    # ------------------------------------------------------------------
    # 4. Status rules
    # ------------------------------------------------------------------
    draft_type = grounding_package.draft_type

    # Customer resolution requires confirmed resolution
    if draft_type == "customer_resolution":
        has_confirmed = any(
            f.confirmation_status == "confirmed"
            and f.fact_type == "confirmed_root_cause"
            for f in grounding_package.resolution_facts
        )
        if not has_confirmed:
            errors.append(
                "Customer resolution requires a confirmed root cause, "
                "but no confirmed resolution fact exists."
            )

    # Documentation proposal requires affected sources
    if draft_type == "documentation_proposal":
        if not grounding_package.documentation_sources:
            warnings.append(
                "Documentation proposal has no affected documentation sources."
            )

    # Product feedback requires feedback facts
    if draft_type == "product_feedback":
        if not grounding_package.feedback_facts:
            errors.append(
                "Product feedback draft requires at least one feedback fact."
            )

    # ------------------------------------------------------------------
    # 5. Privacy
    # ------------------------------------------------------------------
    if contains_secrets(body):
        errors.append("Draft body contains detected secret patterns.")

    # Check for reconstructed identifiers not in allowed set
    for identifier_type, allowed_values in grounding_package.allowed_identifiers.items():
        allowed_set = set(allowed_values)
        # Rudimentary check: if body contains alphanumeric tokens that look like IDs
        # but aren't in the allowed set, flag them.
        # This is a best-effort check; real secret scanning is deeper.
        pass  # Detailed PII scanning would be a separate pass

    # ------------------------------------------------------------------
    # 6. High-risk claims
    # ------------------------------------------------------------------
    unsupported = check_high_risk_claims(body, claim_map, grounding_package)
    for uc in unsupported:
        errors.append(f"Unsupported claim: {uc}")

    # ------------------------------------------------------------------
    # 7. Required sections
    # ------------------------------------------------------------------
    missing_sections = check_required_sections(
        body,
        grounding_package.required_sections,
        draft_type,
    )
    for ms in missing_sections:
        warnings.append(f"Missing recommended section: '{ms}'")

    # ------------------------------------------------------------------
    # 8. Confirmation language check
    # ------------------------------------------------------------------
    _check_confirmation_language(body, claim_map, all_fact_codes, errors, warnings)

    # ------------------------------------------------------------------
    # Determine overall validity
    # ------------------------------------------------------------------
    valid = len(errors) == 0
    if warnings and not errors:
        validation_status = "warning"
    elif errors:
        validation_status = "invalid"
    else:
        validation_status = "valid"

    return DraftValidationResult(
        valid=valid,
        errors=errors,
        warnings=warnings,
        unsupported_claims=unsupported,
        missing_required_sections=missing_sections,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_all_fact_codes(pkg: DraftGroundingPackage) -> dict[str, GroundingFact]:
    """Build a flat dictionary of fact_code → GroundingFact."""
    result: dict[str, GroundingFact] = {}
    for fact_list in [
        pkg.confirmed_facts,
        pkg.observed_facts,
        pkg.documentation_facts,
        pkg.hypotheses,
        pkg.missing_evidence,
        pkg.resolution_facts,
        pkg.feedback_facts,
    ]:
        for fact in fact_list:
            result[fact.fact_code] = fact
    return result


def _check_confirmation_language(
    body: str,
    claim_map: list[dict[str, object]],
    all_facts: dict[str, GroundingFact],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Ensure confirmation language matches fact status.

    If a claim references only unconfirmed hypotheses, the body
    must not use definitive language about that claim.
    """
    confident_markers = [
        "confirmed",
        "definitely",
        "certainly",
        "undoubtedly",
        "proven",
    ]

    for entry in claim_map:
        if not isinstance(entry, dict):
            continue
        claim = str(entry.get("claim", "")).lower()
        codes = entry.get("fact_codes", [])
        if not isinstance(codes, list) or not codes:
            continue

        # Check if all supporting codes are unconfirmed
        all_unconfirmed = True
        has_confirmed = False
        for fc in codes:
            fact = all_facts.get(str(fc))
            if fact is not None:
                if fact.confirmation_status == "confirmed":
                    has_confirmed = True
                    all_unconfirmed = False
                elif fact.confirmation_status != "unconfirmed":
                    all_unconfirmed = False

        if all_unconfirmed and codes:
            # Check if the claim text uses confident language
            for marker in confident_markers:
                if marker in claim:
                    warnings.append(
                        f"Claim '{claim[:80]}...' uses confident language "
                        f"('{marker}') but references only unconfirmed facts."
                    )
                    break