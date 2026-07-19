"""Deterministic mock drafting provider for automated testing."""

from __future__ import annotations

import json

from src.drafting.providers.errors import DraftingInvalidResponseError

# ---------------------------------------------------------------------------
# Supported deterministic mock modes
# ---------------------------------------------------------------------------
MOCK_MODES = {
    "valid",
    "invalid_json",
    "unknown_fact",
    "unknown_source",
    "unsupported_root_cause",
    "unlabelled_hypothesis",
    "secret_leak",
    "missing_section",
    "provider_failure",
}


class MockDraftingProvider:
    """Returns deterministic outputs based on the selected *mode*.

    Allows the evaluation suite to prove that validators reject unsafe
    outputs without calling a live API.
    """

    provider_name = "mock"
    model_name = "mock-deterministic"

    def __init__(self, mode: str = "valid") -> None:
        if mode not in MOCK_MODES:
            raise ValueError(f"Unknown mock mode: {mode}")
        self.mode = mode

    def generate(
        self,
        *,
        system_instruction: str,
        structured_input: dict[str, object],
        output_schema: dict[str, object],
    ) -> dict[str, object]:
        if self.mode == "provider_failure":
            raise DraftingInvalidResponseError("Mock provider failure requested.")

        if self.mode == "invalid_json":
            raise DraftingInvalidResponseError(
                "Mock provider returned unparseable text."
            )

        if self.mode == "unknown_fact":
            return _mock_unknown_fact(structured_input)

        if self.mode == "unknown_source":
            return _mock_unknown_source(structured_input)

        if self.mode == "unsupported_root_cause":
            return _mock_unsupported_root_cause(structured_input)

        if self.mode == "unlabelled_hypothesis":
            return _mock_unlabelled_hypothesis(structured_input)

        if self.mode == "secret_leak":
            return _mock_secret_leak(structured_input)

        if self.mode == "missing_section":
            return _mock_missing_section(structured_input)

        # Default: valid response
        return _mock_valid(structured_input)


# ---------------------------------------------------------------------------
# Mock payload builders
# ---------------------------------------------------------------------------


def _mock_valid(input_data: dict[str, object]) -> dict[str, object]:
    return {
        "subject": "Support investigation update",
        "body": _build_body_from_facts(input_data),
        "used_fact_codes": _collect_fact_codes(input_data),
        "used_source_urls": _collect_source_urls(input_data),
        "claim_map": _build_claim_map(input_data),
    }


def _mock_unknown_fact(input_data: dict[str, object]) -> dict[str, object]:
    return {
        "subject": "Investigation update",
        "body": "The contract was created successfully at 2024-01-15.",
        "used_fact_codes": ["contract.created.success"],
        "used_source_urls": [],
        "claim_map": [
            {
                "claim": "The contract was created successfully at 2024-01-15.",
                "fact_codes": ["contract.created.success"],
            }
        ],
    }


def _mock_unknown_source(input_data: dict[str, object]) -> dict[str, object]:
    return {
        "subject": "Documentation observation",
        "body": "See https://docs.example.com/not-in-grounding for details.",
        "used_fact_codes": _collect_fact_codes(input_data),
        "used_source_urls": ["https://docs.example.com/not-in-grounding"],
        "claim_map": _build_claim_map(input_data),
    }


def _mock_unsupported_root_cause(input_data: dict[str, object]) -> dict[str, object]:
    return {
        "subject": "Root cause identified",
        "body": "The root cause was definitely the uniqueness key reused by a prior operation.",
        "used_fact_codes": _collect_fact_codes(input_data),
        "used_source_urls": _collect_source_urls(input_data),
        "claim_map": [
            {
                "claim": (
                    "The root cause was definitely the uniqueness key reused "
                    "by a prior operation."
                ),
                "fact_codes": _collect_fact_codes(input_data),
            }
        ],
    }


def _mock_unlabelled_hypothesis(input_data: dict[str, object]) -> dict[str, object]:
    hypotheses = input_data.get("hypotheses", [])
    return {
        "subject": "Investigation findings",
        "body": "The uniqueness key was reused by an earlier logical operation.",
        "used_fact_codes": _collect_fact_codes(input_data),
        "used_source_urls": _collect_source_urls(input_data),
        "claim_map": [
            {
                "claim": (
                    "The uniqueness key was reused by an earlier logical operation."
                ),
                "fact_codes": [h.get("fact_code", "") for h in hypotheses[:1]],
            }
        ],
    }


def _mock_secret_leak(input_data: dict[str, object]) -> dict[str, object]:
    return {
        "subject": "Investigation update",
        "body": "We used Bearer sk_live_abc123xyz to authenticate.",
        "used_fact_codes": _collect_fact_codes(input_data),
        "used_source_urls": _collect_source_urls(input_data),
        "claim_map": [
            {
                "claim": "We used Bearer sk_live_abc123xyz to authenticate.",
                "fact_codes": _collect_fact_codes(input_data),
            }
        ],
    }


def _mock_missing_section(input_data: dict[str, object]) -> dict[str, object]:
    return {
        "subject": None,
        "body": "We received your request.",
        "used_fact_codes": _collect_fact_codes(input_data),
        "used_source_urls": _collect_source_urls(input_data),
        "claim_map": [],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_body_from_facts(input_data: dict[str, object]) -> str:
    """Derive a simple body from the grounding facts for valid mock mode."""
    draft_type = input_data.get("draft_type", "customer_update")
    parts: list[str] = []

    if draft_type == "support_answer":
        observed = input_data.get("observed_facts", [])
        documented = input_data.get("documentation_facts", [])
        confirmed = input_data.get("confirmed_facts", [])
        hypotheses = input_data.get("hypotheses", [])
        missing = input_data.get("missing_evidence", [])

        parts.append("## Direct Answer")
        if hypotheses:
            parts.append(
                "The available evidence points to a possible configuration or matching issue, "
                "but the root cause still requires verification."
            )
        elif observed or documented:
            parts.append("The available evidence and documentation are summarized below.")
        else:
            parts.append("There is not enough evidence yet to provide a reliable technical conclusion.")

        parts.append("")
        parts.append("## What the Evidence Shows")
        for fact in observed[:6]:
            parts.append(f"- Observed: {fact.get('statement', fact.get('fact_code', ''))}")
        for fact in documented[:6]:
            parts.append(f"- Documented: {fact.get('statement', fact.get('fact_code', ''))}")

        parts.append("")
        parts.append("## What Remains Unconfirmed")
        if hypotheses:
            for fact in hypotheses:
                parts.append(
                    f"- Possible: {fact.get('statement', fact.get('fact_code', ''))} "
                    "This requires verification."
                )
        else:
            parts.append("- No specific root-cause hypothesis is supported yet.")
        for fact in missing:
            parts.append(f"- Missing: {fact.get('statement', fact.get('fact_code', ''))}")

        parts.append("")
        parts.append("## Recommended Checks")
        steps = [f for f in confirmed if f.get("fact_type") == "investigation_step"]
        for fact in steps[:10]:
            parts.append(f"- {fact.get('statement', fact.get('fact_code', ''))}")
        if not steps:
            parts.append("- Collect the missing evidence before confirming a root cause.")

        parts.append("")
        parts.append("## Customer Communication")
        parts.append(
            "We reviewed the issue and confirmed the observations listed above. "
            "A possible cause is still being verified, and the recommended checks will determine the next action."
        )

        parts.append("")
        parts.append("## Internal Escalation")
        parts.append(
            "Escalate only after the recommended checks are complete and include the observed evidence, "
            "missing evidence, mapped concepts, and documentation sources."
        )

        parts.append("")
        parts.append("## Sources")
        for source in input_data.get("documentation_sources", []):
            if isinstance(source, dict) and source.get("source_url"):
                parts.append(f"- {source['source_url']}")

    elif draft_type == "customer_update":
        parts.append("We have reviewed your ticket and completed the initial investigation.")
        parts.append("")
        confirmed = input_data.get("confirmed_facts", [])
        observed = input_data.get("observed_facts", [])
        hypotheses = input_data.get("hypotheses", [])

        if confirmed or observed:
            parts.append("## Confirmed Findings")
            for f in confirmed:
                parts.append(f"- {f.get('statement', f.get('fact_code', ''))}")
            for f in observed:
                parts.append(f"- {f.get('statement', f.get('fact_code', ''))}")

        parts.append("")
        parts.append("## What Remains Under Investigation")
        for h in hypotheses:
            parts.append(
                f"- {h.get('statement', h.get('fact_code', ''))} "
                f"(this is a hypothesis and requires verification)"
            )

        missing = input_data.get("missing_evidence", [])
        if missing:
            parts.append("")
            parts.append("## Information Required")
            for m in missing:
                parts.append(f"- {m.get('statement', m.get('fact_code', ''))}")

        parts.append("")
        parts.append("## Next Steps")
        parts.append("We will continue investigating and update you with our findings.")

    elif draft_type == "customer_resolution":
        parts.append("We have completed our investigation and identified the root cause.")
        parts.append("")
        parts.append("## Confirmed Root Cause")
        resolution = input_data.get("resolution_facts", [])
        for r in resolution:
            parts.append(f"- {r.get('statement', r.get('fact_code', ''))}")
        parts.append("")
        parts.append("## Resolution")
        parts.append("The configuration has been updated to correct the issue.")
        parts.append("")
        parts.append("## Verification")
        parts.append("We verified that requests now succeed with HTTP 200.")

    elif draft_type == "engineering_escalation":
        parts.append("## Issue Summary")
        parts.append("Requesting engineering review of the following issue.")
        parts.append("")
        parts.append("## Customer Impact")
        parts.append("Customer is blocked from completing contract creation.")
        parts.append("")
        parts.append("## Observed Evidence")
        observed = input_data.get("observed_facts", [])
        for o in observed:
            parts.append(f"- {o.get('statement', o.get('fact_code', ''))}")
        parts.append("")
        parts.append("## Hypotheses")
        for h in input_data.get("hypotheses", []):
            parts.append(f"- [Unconfirmed] {h.get('statement', h.get('fact_code', ''))}")
        parts.append("")
        parts.append("## Documentation Consulted")
        for s in input_data.get("documentation_sources", []):
            url = s.get("source_url", "") if isinstance(s, dict) else str(s)
            parts.append(f"- {url}")
        parts.append("")
        parts.append("## Specific Engineering Questions")
        parts.append("Can you confirm the uniqueness key behavior described above?")

    elif draft_type == "documentation_proposal":
        parts.append("## Affected Documentation")
        parts.append("See referenced sources.")
        parts.append("")
        parts.append("## Observed Support Problem")
        parts.append("Multiple customers encountered this issue without clear documentation.")
        parts.append("")
        parts.append("## Proposed Content")
        parts.append("Add troubleshooting section for this scenario.")
        parts.append("")
        parts.append("## Verification Requirements")
        parts.append("Review by documentation team required.")

    elif draft_type == "product_feedback":
        parts.append("## Customer Problem")
        parts.append("Customer experienced difficulty identifying the root cause.")
        parts.append("")
        parts.append("## Current Product Behavior")
        parts.append("The API accepts the request but provides insufficient correlation data.")
        parts.append("")
        parts.append("## Proposed Improvement")
        parts.append("Add request correlation ID to response headers.")
        parts.append("")
        parts.append("## Expected Impact")
        parts.append("Reduces time-to-resolution for support tickets.")

    elif draft_type == "executive_summary":
        parts.append("## Customer Problem")
        parts.append("Brief summary of the customer issue.")
        parts.append("")
        parts.append("## Technical Evidence")
        parts.append("See fact references below.")
        parts.append("")
        parts.append("## Investigation Approach")
        parts.append("Deterministic evidence collection and documentation correlation.")
        parts.append("")
        parts.append("## Resolution")
        parts.append("Confirmed and verified.")
        parts.append("")
        parts.append("## Business Impact")
        parts.append("Improved support workflow and documentation feedback loop.")

    else:
        parts.append("Investigation draft generated.")

    return "\n".join(parts)


def _collect_fact_codes(input_data: dict[str, object]) -> list[str]:
    """Collect all fact codes from the grounding package."""
    keys = [
        "confirmed_facts",
        "observed_facts",
        "documentation_facts",
        "hypotheses",
        "missing_evidence",
        "resolution_facts",
        "feedback_facts",
    ]
    codes: list[str] = []
    for key in keys:
        for f in input_data.get(key, []):
            fc = f.get("fact_code", "")
            if fc and fc not in codes:
                codes.append(fc)
    return codes


def _collect_source_urls(input_data: dict[str, object]) -> list[str]:
    sources = input_data.get("documentation_sources", [])
    urls: list[str] = []
    for s in sources:
        if isinstance(s, dict):
            url = s.get("source_url", "")
        else:
            url = str(s)
        if url and url not in urls:
            urls.append(url)
    return urls


def _build_claim_map(input_data: dict[str, object]) -> list[dict[str, object]]:
    """Build a simple claim map from the confirmed facts."""
    facts = input_data.get("confirmed_facts", [])
    if not facts:
        facts = input_data.get("observed_facts", [])
    return [
        {
            "claim": f.get("statement", ""),
            "fact_codes": [f.get("fact_code", "")],
        }
        for f in facts[:5]
    ]