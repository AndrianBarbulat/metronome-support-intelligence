"""Validate that required sections are present in generated drafts."""

from __future__ import annotations


def check_required_sections(
    body: str,
    required_sections: list[str],
    draft_type: str,
) -> list[str]:
    """Return the list of required sections that are MISSING from *body*.

    Checks for section markers using multiple strategies:
    1. Markdown heading markers (## Section Name)
    2. Bold markers (**Section Name**)
    3. Keyword presence matches
    """
    missing: list[str] = []
    body_lower = body.lower()

    for section in required_sections:
        if _section_present(body_lower, section.lower()):
            continue
        if _keyword_match(body_lower, section.lower(), draft_type):
            continue
        missing.append(section)

    return missing


def _section_present(body_lower: str, section_lower: str) -> bool:
    """Check for explicit section markers."""
    # Check for markdown headings
    if f"## {section_lower}" in body_lower:
        return True
    if f"# {section_lower}" in body_lower:
        return True
    # Check for bold markers
    if f"**{section_lower}**" in body_lower:
        return True
    # Check for uppercase variant
    if f"## {section_lower.upper()}" in body_lower:
        return True
    return False


def _keyword_match(body_lower: str, section_lower: str, draft_type: str) -> bool:
    """Use keyword-based fallback matching for common sections."""
    # Map sections to keywords that indicate coverage
    keyword_map: dict[str, str] = {
        "acknowledgement": "thank you for",
        "confirmed findings": "confirmed",
        "confirmed root cause": "root cause",
        "what remains under investigation": "investigation",
        "information required": "missing",
        "next steps": "next",
        "resolution": "resolved",
        "verification": "verif",
        "prevention": "prevent",
        "issue summary": "issue",
        "customer impact": "impact",
        "environment or account context": "account",
        "endpoint and response": "endpoint",
        "sanitized request evidence": "request",
        "sanitized response evidence": "response",
        "confirmed observations": "observ",
        "current hypotheses": "hypothesis",
        "documentation consulted": "documentation",
        "investigation completed": "completed",
        "reproduction status": "reproduc",
        "missing evidence": "missing",
        "specific engineering questions": "question",
        "business impact": "impact",
    }

    keyword = keyword_map.get(section_lower)
    if keyword and keyword in body_lower:
        return True
    return False