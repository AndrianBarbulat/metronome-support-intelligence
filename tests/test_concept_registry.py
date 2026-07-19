from src.support.concept_registry import InvestigationConceptRegistry


def test_registry_reports_programmatic_count():
    registry = InvestigationConceptRegistry()

    assert registry.concept_count == 45
    assert registry.validation_report()["total_concepts"] == 45


def test_registry_reports_counts_by_scenario():
    counts = InvestigationConceptRegistry().count_by_scenario()

    assert counts == {"generic": 11, "contracts": 14, "usage": 15, "customers": 5}


def test_registry_has_no_duplicate_codes():
    assert InvestigationConceptRegistry().duplicate_concept_codes() == []


def test_registry_has_no_unknown_prerequisites():
    assert InvestigationConceptRegistry().missing_prerequisite_codes() == []


def test_registry_has_no_dependency_cycles():
    assert InvestigationConceptRegistry().dependency_cycles() == []


def test_registry_has_no_unused_scenarios():
    assert InvestigationConceptRegistry().unused_concepts() == []
