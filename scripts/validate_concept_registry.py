#!/usr/bin/env python3
"""Validate and report the investigation concept registry."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.support.concept_registry import InvestigationConceptRegistry

    registry = InvestigationConceptRegistry()
    report = registry.validation_report()

    print("Concept Registry Validation")
    print()
    print(f"Total concepts: {report['total_concepts']}")
    print("Concepts by scenario")
    for scenario, count in report["concepts_by_scenario"].items():
        print(f"- {scenario}: {count}")
    print(f"Duplicate concept codes: {report['duplicate_concept_codes']}")
    print(f"Missing prerequisite codes: {report['missing_prerequisite_codes']}")
    print(f"Dependency cycles: {report['dependency_cycles']}")
    print(f"Unused concepts: {report['unused_concepts']}")

    if (
        report["duplicate_concept_codes"]
        or report["missing_prerequisite_codes"]
        or report["dependency_cycles"]
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
