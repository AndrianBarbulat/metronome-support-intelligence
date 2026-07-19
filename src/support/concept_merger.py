"""Merge overlapping investigation concepts by merge_group."""

from __future__ import annotations

from collections import defaultdict

from .investigation_concepts import InvestigationConcept
from .models import MergedConceptGroup


PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def merge_concepts(
    concepts: list[InvestigationConcept],
) -> list[InvestigationConcept]:
    """Merge concepts with the same `merge_group` into consolidated entries.

    The resulting concept uses the action/reason from the most specific
    (non-generic) concept, and retains all source_capabilities from merged
    members.
    """
    if not concepts:
        return []

    groups: dict[str, list[InvestigationConcept]] = defaultdict(list)
    standalone: list[InvestigationConcept] = []

    for c in concepts:
        if c.merge_group:
            groups[c.merge_group].append(c)
        else:
            standalone.append(c)

    result: list[InvestigationConcept] = list(standalone)

    for group_name, members in groups.items():
        if len(members) == 1:
            result.append(members[0])
        else:
            merged = _merge_group(group_name, members)
            result.append(merged)

    # Deduplicate by code
    seen: set[str] = set()
    deduped: list[InvestigationConcept] = []
    for c in result:
        if c.code not in seen:
            seen.add(c.code)
            deduped.append(c)

    return deduped


def describe_merged_groups(concepts: list[InvestigationConcept]) -> list[MergedConceptGroup]:
    """Return report-friendly descriptions for concepts produced by merge groups."""
    groups: list[MergedConceptGroup] = []
    for concept in concepts:
        codes = concept.concept_codes or [concept.code]
        if concept.merge_group and len(codes) > 1:
            groups.append(MergedConceptGroup(
                merge_group=concept.merge_group,
                concept_codes=codes,
                action=concept.action,
                reason=concept.reason,
            ))
    return groups


def _merge_group(
    group_name: str,
    members: list[InvestigationConcept],
) -> InvestigationConcept:
    """Merge members into one concept. Prefer the scenario-specific member."""
    # Sort: non-generic scenario first, then by priority
    members.sort(
        key=lambda c: (
            0 if c.scenario != "generic" else 1,
            PRIORITY_ORDER.get(c.priority, 2),
        )
    )
    primary = members[0]
    concept_codes = list(dict.fromkeys(
        code for m in members for code in (m.concept_codes or [m.code])
    ))
    all_caps = list(dict.fromkeys(
        cap for m in members for cap in m.source_capabilities
    ))
    all_prereqs = list(dict.fromkeys(
        p for m in members for p in m.prerequisites
    ))
    max_priority = min(
        members,
        key=lambda c: PRIORITY_ORDER.get(c.priority, 2),
    ).priority
    any_blocking = any(m.blocking for m in members)
    action = _merged_action(group_name, members, primary)
    reason = _combine_text([m.reason for m in members])
    expected = _combine_expected([m.expected_evidence for m in members])

    return InvestigationConcept(
        code=primary.code,
        action=action,
        reason=reason,
        expected_evidence=expected,
        priority=max_priority,
        blocking=any_blocking,
        prerequisites=all_prereqs,
        source_capabilities=all_caps,
        triggered_by=primary.triggered_by,
        scenario=primary.scenario,
        merge_group=group_name,
        concept_codes=concept_codes,
    )


def _merged_action(
    group_name: str,
    members: list[InvestigationConcept],
    primary: InvestigationConcept,
) -> str:
    codes = {m.code for m in members}
    if group_name == "request_capture":
        if codes <= {"generic.capture_request_id", "generic.capture_timestamp"}:
            return "Record the request ID and timestamp if they are not already available."
        return "Record the missing request identifiers, timing, and request evidence needed for investigation."
    if group_name == "response_capture":
        return "Record the missing response status, headers, and body evidence."
    if group_name == "endpoint_verification":
        if any(c.startswith("contract.") for c in codes):
            return "Confirm that POST /v1/contracts/create matches the documented contract-creation operation."
        return primary.action
    if group_name == "minimal_reproduction":
        return "Reproduce the issue once with the smallest valid request needed to confirm the behavior."
    if group_name == "final_state":
        if "usage.verify_final_state" in codes:
            return "Verify whether the expected invoice line item appears after processing."
        if any(c.startswith("contract.") for c in codes):
            return "Verify the final contract state."
        return primary.action
    if group_name == "engineering_escalation":
        scenario_specific = [m for m in members if m.scenario != "generic"]
        return scenario_specific[0].action if scenario_specific else primary.action
    if group_name == "customer_reference":
        return "Verify the referenced customer exists and is active."
    if group_name == "pricing_reference":
        if any(c == "contract.compare_existing_pricing" for c in codes):
            return "Compare the existing contract customer and pricing configuration with the intended contract."
        return "Verify the referenced pricing configuration exists and is active."
    return primary.action


def _combine_text(values: list[str]) -> str:
    unique = [v for v in dict.fromkeys(v.strip() for v in values if v and v.strip())]
    return " ".join(unique)


def _combine_expected(values: list[str | None]) -> str | None:
    unique = [v for v in dict.fromkeys(v.strip() for v in values if v and v.strip())]
    if not unique:
        return None
    return " ".join(unique)
