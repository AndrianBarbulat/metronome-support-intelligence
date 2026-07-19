"""Merge overlapping investigation concepts by merge_group."""

from __future__ import annotations

from collections import defaultdict

from .investigation_concepts import InvestigationConcept


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


def _merge_group(
    group_name: str,
    members: list[InvestigationConcept],
) -> InvestigationConcept:
    """Merge members into one concept. Prefer the scenario-specific member."""
    # Sort: non-generic scenario first, then by priority
    members.sort(
        key=lambda c: (
            0 if c.scenario != "generic" else 1,
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(c.priority, 2),
        )
    )
    primary = members[0]
    all_caps = list(dict.fromkeys(
        cap for m in members for cap in m.source_capabilities
    ))
    all_prereqs = list(dict.fromkeys(
        p for m in members for p in m.prerequisites
    ))
    max_priority = min(
        members,
        key=lambda c: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(c.priority, 2),
    ).priority
    any_blocking = any(m.blocking for m in members)

    return InvestigationConcept(
        code=primary.code,
        action=primary.action,
        reason=primary.reason,
        expected_evidence=primary.expected_evidence,
        priority=max_priority,
        blocking=any_blocking,
        prerequisites=all_prereqs,
        source_capabilities=all_caps,
        triggered_by=primary.triggered_by,
        scenario=primary.scenario,
        merge_group=group_name,
    )