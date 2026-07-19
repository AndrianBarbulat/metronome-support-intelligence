"""Topological sort for investigation concept ordering."""

from __future__ import annotations

from collections import defaultdict, deque

from .investigation_concepts import InvestigationConcept


class DependencyCycleError(Exception):
    """Raised when concept prerequisites form a cycle."""


def order_concepts(concepts: list[InvestigationConcept]) -> list[InvestigationConcept]:
    """Topologically sort concepts by prerequisites.

    Concepts with earlier prerequisites come first.
    Concepts with higher priority are ordered before lower-priority peers.
    Escalation is always last.
    Final-state verification precedes escalation.
    """
    if not concepts:
        return []

    code_map = {c.code: c for c in concepts}
    in_degree: dict[str, int] = {c.code: 0 for c in concepts}
    adj: dict[str, list[str]] = defaultdict(list)

    for c in concepts:
        for prereq in c.prerequisites:
            if prereq in code_map:
                adj[prereq].append(c.code)
                in_degree[c.code] += 1

    # Kahn's algorithm
    queue: deque[str] = deque()
    for code, deg in in_degree.items():
        if deg == 0:
            queue.append(code)

    ordered_codes: list[str] = []
    while queue:
        # Sort queue by priority for stable ordering
        candidates = sorted(
            queue, key=lambda cd: _priority_order(code_map[cd].priority)
        )
        queue.clear()
        for code in candidates:
            ordered_codes.append(code)
            for nxt in adj[code]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

    if len(ordered_codes) != len(concepts):
        raise DependencyCycleError(
            f"Cycle detected among concepts: "
            f"{set(c.code for c in concepts) - set(ordered_codes)}"
        )

    result = [code_map[code] for code in ordered_codes]

    # Post-order: ensure escalation is last, final_state before escalation
    result = _move_to_end_by_group(result, "engineering_escalation")
    result = _move_before_group(result, "final_state", "engineering_escalation")

    # Deduplicate by code
    seen: set[str] = set()
    deduped: list[InvestigationConcept] = []
    for c in result:
        if c.code not in seen:
            seen.add(c.code)
            deduped.append(c)

    return deduped


def _priority_order(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 2)


def _move_to_end_by_group(
    concepts: list[InvestigationConcept], group: str
) -> list[InvestigationConcept]:
    """Move all concepts with the given merge_group to the end."""
    matching = [c for c in concepts if c.merge_group == group]
    others = [c for c in concepts if c.merge_group != group]
    return others + matching


def _move_before_group(
    concepts: list[InvestigationConcept], before_group: str, after_group: str
) -> list[InvestigationConcept]:
    """Ensure concepts in *before_group* appear before concepts in *after_group*."""
    before = [c for c in concepts if c.merge_group == before_group]
    after = [c for c in concepts if c.merge_group == after_group]
    middle = [c for c in concepts if c.merge_group not in (before_group, after_group)]
    result = middle
    try:
        idx = next(i for i, c in enumerate(result) if c.merge_group == after_group)
    except StopIteration:
        idx = len(result)
    for b in before:
        result.insert(idx, b)
    return result


def _move_to_end(
    concepts: list[InvestigationConcept], code: str
) -> list[InvestigationConcept]:
    result = [c for c in concepts if c.code != code]
    target = next((c for c in concepts if c.code == code), None)
    if target:
        result.append(target)
    return result


def _move_before(
    concepts: list[InvestigationConcept], before_code: str, after_code: str
) -> list[InvestigationConcept]:
    """Ensure *before_code* appears before *after_code*."""
    bc = next((c for c in concepts if c.code == before_code), None)
    ac = next((c for c in concepts if c.code == after_code), None)
    if not bc or not ac:
        return concepts
    result = [c for c in concepts if c.code not in (before_code, after_code)]
    try:
        idx = result.index(ac) if ac in result else len(result)
    except ValueError:
        idx = len(result)
    result.insert(idx, bc)
    return result