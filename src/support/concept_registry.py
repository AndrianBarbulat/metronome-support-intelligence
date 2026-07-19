"""Registry of all investigation concepts with adaptive evidence-aware selection."""

from __future__ import annotations

from dataclasses import dataclass

from .concept_merger import merge_concepts
from .concept_suppression import suppress_redundant_concepts
from .investigation_concepts import ALL_CONCEPTS, InvestigationConcept
from .models import (
    ConceptSelectionDecision,
    ExtractedTicketSignals,
    InvestigationHypothesis,
    InvestigationObservation,
    MissingEvidence,
    SupportTicketInput,
    ValidationFinding,
)


@dataclass
class ConceptSelectionResult:
    candidate_concepts: list[InvestigationConcept]
    selected_concepts: list[InvestigationConcept]
    merged_concepts: list[InvestigationConcept]
    decisions: list[ConceptSelectionDecision]


class InvestigationConceptRegistry:
    def __init__(self) -> None:
        self._by_code: dict[str, InvestigationConcept] = {}
        for concept in ALL_CONCEPTS:
            self._by_code[concept.code] = concept

    def get(self, code: str) -> InvestigationConcept | None:
        return self._by_code.get(code)

    def get_for_scenario(self, scenario: str) -> list[InvestigationConcept]:
        return [c for c in ALL_CONCEPTS if c.scenario == scenario or c.scenario == "generic"]

    @property
    def concept_count(self) -> int:
        return len(self._by_code)

    def count_by_scenario(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for concept in ALL_CONCEPTS:
            counts[concept.scenario] = counts.get(concept.scenario, 0) + 1
        return counts

    def duplicate_concept_codes(self) -> list[str]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for concept in ALL_CONCEPTS:
            if concept.code in seen:
                duplicates.append(concept.code)
            seen.add(concept.code)
        return duplicates

    def missing_prerequisite_codes(self) -> list[tuple[str, str]]:
        known = {c.code for c in ALL_CONCEPTS}
        missing: list[tuple[str, str]] = []
        for concept in ALL_CONCEPTS:
            for prereq in concept.prerequisites:
                if prereq not in known:
                    missing.append((concept.code, prereq))
        return missing

    def dependency_cycles(self) -> list[list[str]]:
        known = {c.code: c for c in ALL_CONCEPTS}
        cycles: list[list[str]] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(code: str, path: list[str]) -> None:
            if code in visiting:
                idx = path.index(code) if code in path else 0
                cycles.append(path[idx:] + [code])
                return
            if code in visited:
                return
            visiting.add(code)
            concept = known.get(code)
            if concept:
                for prereq in concept.prerequisites:
                    if prereq in known:
                        visit(prereq, path + [prereq])
            visiting.remove(code)
            visited.add(code)

        for code in known:
            visit(code, [code])
        return cycles

    def unused_concepts(self) -> list[str]:
        known_scenarios = {"generic", "contracts", "usage", "customers"}
        return [c.code for c in ALL_CONCEPTS if c.scenario not in known_scenarios]

    def validation_report(self) -> dict[str, object]:
        return {
            "total_concepts": self.concept_count,
            "concepts_by_scenario": self.count_by_scenario(),
            "duplicate_concept_codes": self.duplicate_concept_codes(),
            "missing_prerequisite_codes": self.missing_prerequisite_codes(),
            "dependency_cycles": self.dependency_cycles(),
            "unused_concepts": self.unused_concepts(),
        }

    def select(
        self,
        signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
        hypotheses: list[InvestigationHypothesis],
        missing: list[MissingEvidence],
        ticket: SupportTicketInput | None = None,
    ) -> list[InvestigationConcept]:
        """Select, suppress, and merge concepts based on evidence state."""
        return self.select_with_trace(
            signals=signals,
            findings=findings,
            hypotheses=hypotheses,
            missing=missing,
            ticket=ticket,
        ).merged_concepts

    def select_with_trace(
        self,
        signals: ExtractedTicketSignals,
        findings: list[ValidationFinding],
        hypotheses: list[InvestigationHypothesis],
        missing: list[MissingEvidence],
        ticket: SupportTicketInput | None,
        observations: list[InvestigationObservation] | None = None,
    ) -> ConceptSelectionResult:
        scenario = signals.product_area or "generic"
        candidates = self._scenario_candidates(scenario)
        applicable: list[InvestigationConcept] = []
        decisions: list[ConceptSelectionDecision] = []

        for concept in candidates:
            reason = _not_applicable_reason(concept, signals, findings, hypotheses, ticket)
            if reason:
                decisions.append(ConceptSelectionDecision(
                    concept_code=concept.code,
                    status="not_applicable",
                    reasons=[reason],
                ))
            else:
                applicable.append(concept)

        selected, suppression_decisions = suppress_redundant_concepts(
            applicable,
            ticket or SupportTicketInput(),
            signals,
            findings,
            observations=observations,
        )
        decisions.extend(suppression_decisions)
        merged = merge_concepts(selected)
        return ConceptSelectionResult(
            candidate_concepts=candidates,
            selected_concepts=selected,
            merged_concepts=merged,
            decisions=decisions,
        )

    def _scenario_candidates(self, scenario: str) -> list[InvestigationConcept]:
        return [c for c in ALL_CONCEPTS if c.scenario == scenario or c.scenario == "generic"]


def _any_trigger_matches(
    triggers: list[str],
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    hypotheses: list[InvestigationHypothesis],
) -> bool:
    return any(_trigger_matches(trigger, signals, findings, hypotheses) for trigger in triggers)


def _trigger_matches(
    trigger: str,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    hypotheses: list[InvestigationHypothesis],
) -> bool:
    if trigger == "scenario.contract_creation":
        return signals.product_area == "contracts" and signals.http_method == "POST"
    if trigger == "scenario.usage_ingestion":
        return signals.product_area == "usage" and signals.http_method == "POST"
    if trigger == "scenario.customer_creation":
        return signals.product_area == "customers" and signals.http_method == "POST"

    if trigger == "status_409":
        return signals.status_code == 409
    if trigger == "status_400":
        return signals.status_code in (400, 422)

    if trigger.startswith("finding."):
        finding_part = trigger.replace("finding.", "", 1)
        if "." in finding_part:
            finding_code, expected_status = finding_part.rsplit(".", 1)
        else:
            finding_code, expected_status = finding_part, None
        return any(
            f.rule_id == finding_code and (expected_status is None or f.status == expected_status)
            for f in findings
        )

    if trigger.startswith("hypothesis."):
        hyp_code = trigger.replace("hypothesis.", "", 1)
        return any(h.hypothesis_code == hyp_code for h in hypotheses)

    return False


def _not_applicable_reason(
    concept: InvestigationConcept,
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    hypotheses: list[InvestigationHypothesis],
    ticket: SupportTicketInput | None,
) -> str | None:
    if concept.triggered_by and not _any_trigger_matches(concept.triggered_by, signals, findings, hypotheses):
        return f"No trigger matched: {concept.triggered_by}"

    if signals.product_area is None and concept.scenario == "generic":
        evidence_only = {
            "generic.capture_request_id",
            "generic.capture_timestamp",
            "generic.capture_complete_request",
            "generic.capture_complete_response",
            "generic.confirm_expected_behavior",
            "generic.confirm_actual_behavior",
            "generic.verify_authentication",
            "generic.verify_endpoint_and_method",
        }
        if concept.code not in evidence_only:
            return "vague tickets only gather identifying evidence"

    if concept.code in {
        "contract.determine_retry_intent",
        "contract.locate_previous_operation",
        "contract.inspect_previous_result",
        "contract.retrieve_existing_contract",
        "contract.compare_existing_pricing",
        "contract.decide_key_reuse",
    } and not _has_contract_uniqueness_evidence(signals, findings, ticket):
        return "no contract uniqueness evidence is present"

    return None


def _has_contract_uniqueness_evidence(
    signals: ExtractedTicketSignals,
    findings: list[ValidationFinding],
    ticket: SupportTicketInput | None,
) -> bool:
    if "uniqueness_key" in signals.request_fields or "uniqueness_key" in signals.technical_tokens:
        return True
    if signals.status_code == 409:
        return True
    if any(f.rule_id == "contract-409-uniqueness" for f in findings):
        return True
    if ticket and ticket.response_body is not None:
        response_text = str(ticket.response_body).lower()
        return "unique" in response_text or "duplicate" in response_text
    return False
