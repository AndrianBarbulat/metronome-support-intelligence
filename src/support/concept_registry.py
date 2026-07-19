"""Registry of all investigation concepts with adaptive evidence-aware selection."""

from __future__ import annotations

from .concept_merger import merge_concepts
from .concept_suppression import suppress_redundant_concepts
from .investigation_concepts import ALL_CONCEPTS, InvestigationConcept
from .models import (
    ExtractedTicketSignals,
    InvestigationHypothesis,
    MissingEvidence,
    ValidationFinding,
)


class InvestigationConceptRegistry:
    def __init__(self) -> None:
        self._by_code: dict[str, InvestigationConcept] = {}
        for c in ALL_CONCEPTS:
            self._by_code[c.code] = c

    def get(self, code: str) -> InvestigationConcept | None:
        return self._by_code.get(code)

    def get_for_scenario(self, scenario: str) -> list[InvestigationConcept]:
        return [c for c in ALL_CONCEPTS if c.scenario == scenario or c.scenario == "generic"]

    @property
    def concept_count(self) -> int:
        return len(self._by_code)

    def count_by_scenario(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in ALL_CONCEPTS:
            counts[c.scenario] = counts.get(c.scenario, 0) + 1
        return counts

    def select(
        self,
        signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
        hypotheses: list[InvestigationHypothesis],
        missing: list[MissingEvidence],
        ticket=None,
    ) -> list[InvestigationConcept]:
        """Select, suppress, and merge concepts based on evidence state."""
        scenario = signals.product_area or "generic"

        # 1. Get candidate concepts
        candidates = self._get_candidates(scenario, signals, findings, hypotheses)

        # 2. Suppress redundant concepts (evidence-aware)
        selected, _decisions = suppress_redundant_concepts(
            candidates, ticket, signals, findings
        )

        # 3. Merge overlapping concepts
        merged = merge_concepts(selected)

        return merged

    def _get_candidates(
        self,
        scenario: str,
        signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
        hypotheses: list[InvestigationHypothesis],
    ) -> list[InvestigationConcept]:
        """Get candidate concepts matching scenario and triggers."""
        candidates: list[InvestigationConcept] = []

        for c in ALL_CONCEPTS:
            if c.scenario != scenario and c.scenario != "generic":
                continue

            # If concept has triggers, check if any match
            if c.triggered_by:
                if not _any_trigger_matches(c.triggered_by, signals, findings, hypotheses):
                    continue

            candidates.append(c)

        # Always include final state and escalation
        for code in ["generic.verify_final_state", "generic.prepare_escalation"]:
            concept = self._by_code.get(code)
            if concept and concept not in candidates:
                candidates.append(concept)

        return candidates


def _any_trigger_matches(
    triggers: list[str],
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    hypotheses: list[InvestigationHypothesis],
) -> bool:
    for trigger in triggers:
        if _trigger_matches(trigger, signals, findings, hypotheses):
            return True
    return False


def _trigger_matches(
    trigger: str,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    hypotheses: list[InvestigationHypothesis],
) -> bool:
    # Scenario triggers
    if trigger == "scenario.contract_creation":
        return signals.product_area == "contracts" and signals.http_method == "POST"
    if trigger == "scenario.usage_ingestion":
        return signals.product_area == "usage" and signals.http_method == "POST"
    if trigger == "scenario.customer_creation":
        return signals.product_area == "customers" and signals.http_method == "POST"

    # Status code triggers
    if trigger == "status_409":
        return signals.status_code == 409
    if trigger == "status_400":
        return signals.status_code in (400, 422)

    # Finding triggers
    if trigger.startswith("finding."):
        finding_code = trigger.replace("finding.", "", 1).rsplit(".", 1)[0]
        for f in findings:
            if f.rule_id == finding_code and f.status == "passed":
                return True

    # Hypothesis triggers
    if trigger.startswith("hypothesis."):
        hyp_code = trigger.replace("hypothesis.", "", 1)
        for h in hypotheses:
            if h.hypothesis_code == hyp_code:
                return True

    return False