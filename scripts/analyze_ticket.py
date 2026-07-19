#!/usr/bin/env python3
"""CLI for analyzing a support ticket."""

from __future__ import annotations

import argparse, json, sys
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a support ticket.")
    parser.add_argument("--input", type=Path, required=True, help="Path to ticket JSON file.")
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    parser.add_argument("--analyzer-version", type=str, default="1.0.0")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--explain-retrieval", action="store_true")
    parser.add_argument("--explain-concepts", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    db_path = project_root / args.database
    input_path = project_root / args.input

    if not input_path.exists():
        print(f"Error: ticket not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, str(project_root))
    from src.support.ticket_parser import load_ticket_from_json
    from src.support.analyzer import analyze_support_ticket

    ticket = load_ticket_from_json(input_path)
    report = analyze_support_ticket(
        ticket=ticket, database_path=db_path,
        analyzer_version=args.analyzer_version,
        persist=not args.no_persist,
    )

    # Print report
    print("\nTicket Investigation\n")
    print("Summary")
    print(report.summary)
    print()

    print("Confirmed observations")
    for i, o in enumerate(report.observations, 1):
        print(f"{i}. {o.statement}")
    print()

    if report.hypotheses:
        print("Possible causes")
        for i, h in enumerate(report.hypotheses, 1):
            print(f"{i}. {h.title}  (confidence: {h.confidence:.2f})")
            for v in h.verification_steps:
                print(f"   - {v}")
        print()

    if report.missing_evidence:
        print("Missing evidence")
        for m in report.missing_evidence:
            print(f"- {m.field} ({m.priority}): {m.reason}")
        print()

    print("Investigation checklist")
    for s in report.investigation_steps:
        print(f"{s.order}. {s.action}")
    print()

    print("Documentation sources")
    for i, d in enumerate(report.documentation_sources, 1):
        print(f"{i}. {d.page_title}")
        print(f"   {d.source_url}")
    print()

    if args.explain_retrieval:
        print(f"Retrieval query: {report.retrieval_query}")
        print(f"Retrieval confidence: {report.retrieval_confidence:.2f}")
        print()

    if args.explain_concepts:
        _print_concept_explanation(report)

    if args.output:
        out_path = project_root / args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict
        out_path.write_text(json.dumps({k: v for k, v in asdict(report).items()
                                         if k != 'content'}, indent=2, default=str), encoding="utf-8")
        print(f"Report saved to: {out_path}")

def _print_concept_explanation(report) -> None:
    decisions_by_status = {"selected": [], "already_complete": [], "suppressed": [], "not_applicable": []}
    for decision in report.concept_decisions:
        decisions_by_status.setdefault(decision.status, []).append(decision)

    print("Concept selection explanation")
    print()
    print("Candidate concepts")
    for code in report.candidate_concept_codes:
        print(f"- {code}")
    print()

    for status, label in [
        ("selected", "Selected concepts"),
        ("already_complete", "Already-complete concepts"),
        ("suppressed", "Suppressed concepts"),
        ("not_applicable", "Not-applicable concepts"),
    ]:
        print(label)
        for decision in decisions_by_status.get(status, []):
            print(f"- {decision.concept_code}")
            for reason in decision.reasons:
                print(f"  Reason: {reason}")
            if decision.satisfied_by:
                print(f"  Satisfied by: {', '.join(decision.satisfied_by)}")
        print()

    print("Merge groups")
    if report.merged_concept_groups:
        for group in report.merged_concept_groups:
            print(f"- {group.merge_group}")
            for code in group.concept_codes:
                print(f"  - {code}")
            print(f"  Into: {group.action}")
    else:
        print("- none")
    print()

    print("Merged checklist steps")
    for step in report.investigation_steps:
        print(f"{step.order}. {step.action}")
        print(f"   Concepts: {', '.join(step.concept_codes)}")
    print()

    print("Ordering dependencies")
    for step in report.investigation_steps:
        if step.concept_codes:
            print(f"- {step.order}: {', '.join(step.concept_codes)}")
    print()

    print("Source capability links")
    for source in report.documentation_sources:
        caps = ", ".join(source.source_capabilities) or "none"
        purposes = ", ".join(source.source_purposes) or "none"
        print(f"- {source.page_title}: capabilities={caps}; purposes={purposes}")
    print()

    print("Final checklist")
    for step in report.investigation_steps:
        print(f"{step.order}. {step.action}")
    print()


if __name__ == "__main__":
    main()
