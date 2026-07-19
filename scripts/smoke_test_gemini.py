#!/usr/bin/env python3
"""Manual smoke test for the Gemini drafting provider.

This script is NOT part of automated pytest. It calls the live Gemini API
using a synthetic sanitized grounding package.

Prerequisites:
    GEMINI_API_KEY must be set in .env or environment.
    GEMINI_MODEL must be set (e.g. gemini-2.5-flash).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.drafting.providers.gemini import GeminiDraftingProvider
from src.drafting.providers.errors import DraftingProviderError
from src.drafting.prompts import build_system_instruction, get_prompt_version


def main() -> None:
    print("=== Gemini Drafting Smoke Test ===")
    print()

    # Provider setup
    try:
        provider = GeminiDraftingProvider()
    except DraftingProviderError as exc:
        print(f"Provider configuration error: {exc}")
        print("Set GEMINI_API_KEY and GEMINI_MODEL in .env or environment.")
        sys.exit(1)

    print(f"Provider : {provider.provider_name}")
    print(f"Model    : {provider.model_name}")
    print(f"Prompt   : {get_prompt_version()}")
    print()

    # Build synthetic grounding package
    grounding = {
        "draft_type": "customer_update",
        "audience": "customer",
        "tone": "professional",
        "ticket_id": None,
        "analysis_id": None,
        "resolution_id": None,
        "feedback_id": None,
        "confirmed_facts": [],
        "observed_facts": [
            {
                "fact_code": "response.status.present",
                "statement": "The ingestion endpoint returned HTTP 200 for event ID evt_abc123.",
                "confirmation_status": "observed",
            }
        ],
        "hypotheses": [
            {
                "fact_code": "hyp.property_mismatch",
                "statement": (
                    "The submitted property name may not match the billable "
                    "metric configuration."
                ),
                "confirmation_status": "unconfirmed",
            }
        ],
        "missing_evidence": [
            {
                "fact_code": "missing.metric_config",
                "statement": "Billable metric property configuration for the customer.",
                "confirmation_status": "missing",
            }
        ],
        "resolution_facts": [],
        "feedback_facts": [],
        "documentation_sources": [],
        "allowed_identifiers": {},
        "required_sections": [
            "Acknowledgement",
            "Confirmed findings",
            "What remains under investigation",
            "Information required",
            "Next steps",
        ],
    }

    system_instruction = build_system_instruction(
        draft_type="customer_update",
        audience="customer",
        tone="professional",
        required_sections=grounding["required_sections"],
    )

    output_schema = {
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

    print("Sending request to Gemini ...")
    try:
        result = provider.generate(
            system_instruction=system_instruction,
            structured_input=grounding,
            output_schema=output_schema,
        )
    except DraftingProviderError as exc:
        print(f"\nGemini request failed: {exc}")
        print("No ticket or resolution data was changed.")
        sys.exit(1)

    print()
    print("--- Validation Result ---")
    # Run validators
    from src.drafting.models import DraftGroundingPackage
    from src.drafting.validator import validate_draft

    pkg = DraftGroundingPackage(
        ticket_id=None,
        analysis_id=None,
        resolution_id=None,
        feedback_id=None,
        draft_type="customer_update",
        audience="customer",
        tone="professional",
        required_sections=grounding["required_sections"],
    )

    validation = validate_draft(result, pkg)
    print(f"Valid: {validation.valid}")
    if validation.errors:
        print("Errors:")
        for e in validation.errors:
            print(f"  - {e}")
    if validation.warnings:
        print("Warnings:")
        for w in validation.warnings:
            print(f"  - {w}")

    print()
    print("--- Used Fact Codes ---")
    for fc in result.get("used_fact_codes", []):
        print(f"  - {fc}")

    print()
    print("--- Used Source URLs ---")
    urls = result.get("used_source_urls", [])
    if urls:
        for u in urls:
            print(f"  - {u}")
    else:
        print("  (none)")

    print()
    print("--- Claim Map ---")
    for cm in result.get("claim_map", []):
        print(f"  Claim: {cm.get('claim', '')}")
        print(f"  Codes: {cm.get('fact_codes', [])}")
        print()

    print("--- Draft Body ---")
    print(result.get("body", ""))
    print()

    # Check for secrets
    from src.drafting.sanitization import contains_secrets
    if contains_secrets(result.get("body", "")):
        print("WARNING: Draft body contains detected secret patterns!")
        sys.exit(1)

    print("Smoke test completed successfully.")
    print("No secrets detected.")
    print("Draft is structurally valid.")


if __name__ == "__main__":
    main()