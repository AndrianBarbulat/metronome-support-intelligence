"""Validate high-risk claims against grounding facts."""

from __future__ import annotations

from src.drafting.models import DraftGroundingPackage, GroundingFact

# ---------------------------------------------------------------------------
# High-risk claim patterns that require strict fact-code support
# ---------------------------------------------------------------------------
_HIGH_RISK_PATTERNS: list[tuple[str, str]] = [
    ("root cause was", "confirmed"),
    ("root cause is", "confirmed"),
    ("the issue has been resolved", "confirmed"),
    ("this occurred because", "confirmed"),
    ("the API rejected", "observed"),
    ("the contract was created", "confirmed"),
    ("the customer was billed", "confirmed"),
    ("the invoice was corrected", "confirmed"),
    ("the event matched", "confirmed"),
    ("the event did not match", "confirmed"),
    ("Metronome guarantees", "documentation_supported"),
    ("the endpoint requires", "documentation_supported"),
    ("definitely", "confirmed"),
    ("certainly", "confirmed"),
]

# Hypothesis-adjacent language — allowed only when explicitly hedged
_HYPOTHESIS_HEDGING = [
    "may",
    "might",
    "possible",
    "possibly",
    "suspected",
    "likely",
    "potentially",
    "could",
    "requires verification",
    "not yet confirmed",
    "working hypothesis",
    "under investigation",
]


def check_high_risk_claims(
    body: str,
    claim_map: list[dict[str, object]],
    grounding_package: DraftGroundingPackage,
) -> list[str]:
    """Return unsupported claims found in the draft body.

    For each high-risk pattern detected, verify that the associated
    fact codes in claim_map reference facts with the required
    confirmation status.
    """
    unsupported: list[str] = []
    body_lower = body.lower()

    # Build fact-code lookup
    all_facts: dict[str, GroundingFact] = {}
    for fact_list in [
        grounding_package.confirmed_facts,
        grounding_package.observed_facts,
        grounding_package.documentation_facts,
        grounding_package.hypotheses,
        grounding_package.resolution_facts,
    ]:
        for fact in fact_list:
            all_facts[fact.fact_code] = fact

    for pattern, min_status in _HIGH_RISK_PATTERNS:
        if pattern in body_lower:
            # Check if there's a hedging word nearby
            hedged = _is_hedged(body_lower, pattern)

            # Always check claims that require confirmed evidence
            # For other statuses, also validate when not hedged
            if not hedged:
                supporting_codes = _find_supporting_codes(claim_map, pattern)
                if not _has_status(supporting_codes, all_facts, min_status):
                    unsupported.append(
                        f"High-risk claim '{pattern}' lacks {min_status} evidence. "
                        f"Supporting fact codes: {supporting_codes}"
                    )

    # Additional: check for "resolved" / "fixed" claims when resolution is missing
    resolution_keywords = ["has been resolved", "has been fixed", "issue is fixed", "is resolved"]
    if any(kw in body_lower for kw in resolution_keywords):
        has_confirmed_resolution = any(
            f.confirmation_status == "confirmed" and f.fact_type == "confirmed_root_cause"
            for f in grounding_package.resolution_facts
        )
        if not has_confirmed_resolution:
            unsupported.append(
                "Draft implies resolution, but no confirmed root cause exists in grounding package."
            )

    return unsupported


def _is_hedged(body_lower: str, pattern: str) -> bool:
    """Check whether hedging language appears near the pattern."""
    idx = body_lower.find(pattern)
    if idx < 0:
        return True  # pattern not found, not a concern
    # Check 100 chars before the pattern
    before = body_lower[max(0, idx - 100): idx]
    return any(hedge in before for hedge in _HYPOTHESIS_HEDGING)


def _find_supporting_codes(
    claim_map: list[dict[str, object]],
    pattern: str,
) -> list[str]:
    """Find fact codes from claim_map entries whose claim matches the pattern."""
    codes: list[str] = []
    pattern_lower = pattern.lower()
    for entry in claim_map:
        claim_text = str(entry.get("claim", "")).lower()
        if pattern_lower in claim_text:
            fc = entry.get("fact_codes", [])
            if isinstance(fc, list):
                codes.extend(str(c) for c in fc)
    return codes


def _has_status(
    fact_codes: list[str],
    all_facts: dict[str, GroundingFact],
    min_status: str,
) -> bool:
    """Check if at least one fact code has status >= min_status."""
    status_rank = {
        "missing": 0,
        "unconfirmed": 1,
        "observed": 2,
        "documentation_supported": 3,
        "confirmed": 4,
    }
    required_rank = status_rank.get(min_status, 0)
    for code in fact_codes:
        fact = all_facts.get(code)
        if fact is not None:
            fact_rank = status_rank.get(fact.confirmation_status, 0)
            if fact_rank >= required_rank:
                return True
    return False