"""Models for the user-facing Metronome intelligence workflow."""

from __future__ import annotations

from dataclasses import dataclass

from src.drafting.models import DraftGroundingPackage, GeneratedDraft
from src.support.models import TicketInvestigationReport


@dataclass
class MetronomeAssistantResult:
    """Complete result for one natural-language Metronome question or issue."""

    question: str
    investigation: TicketInvestigationReport
    grounding_package: DraftGroundingPackage
    answer: GeneratedDraft

    @property
    def mapped_concepts(self) -> list[str]:
        return list(self.investigation.selected_concept_codes)
