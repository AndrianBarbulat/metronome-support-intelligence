from pathlib import Path

from src.support.analyzer import analyze_support_ticket
from src.support.ticket_parser import load_ticket_from_json

DB = Path("data/metronome_docs.db")


def analyze(name):
    return analyze_support_ticket(load_ticket_from_json(Path(f"data/examples/{name}.json")), DB, persist=False)


def flat_codes(report):
    return [code for step in report.investigation_steps for code in step.concept_codes]


def test_analyzer_contract_409_final_checklist_has_no_duplicate_actions():
    report = analyze("contract_409")
    actions = [step.action for step in report.investigation_steps]

    assert len(actions) == len(set(actions))


def test_analyzer_contract_409_does_not_request_existing_payload_fields():
    report = analyze("contract_409")
    text = " ".join(step.action.lower() for step in report.investigation_steps)

    assert "collect the complete request payload" not in text
    assert "starting_at" not in text


def test_analyzer_accepted_not_billed_has_expected_final_state_and_escalation():
    report = analyze("usage_accepted_not_billed")

    assert "usage.verify_final_state" in flat_codes(report)
    assert "usage.prepare_escalation" in report.investigation_steps[-1].concept_codes


def test_analyzer_report_preserves_selection_decisions_and_merge_groups():
    report = analyze("contract_409")

    assert report.concept_decisions
    assert any(d.status == "suppressed" for d in report.concept_decisions)
    assert any(g.merge_group == "engineering_escalation" for g in report.merged_concept_groups)


def test_analyzer_sources_include_required_purposes():
    report = analyze("usage_accepted_not_billed")
    purposes = {purpose for source in report.documentation_sources for purpose in source.source_purposes}

    assert {"operation", "verification", "configuration", "final_state"}.issubset(purposes)
