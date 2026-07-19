#!/usr/bin/env python3
"""Ask a natural-language Metronome question using the complete intelligence pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.drafting.config import load_config
from src.assistant.service import answer_metronome_question


def _read_question(args: argparse.Namespace) -> str:
    if args.file:
        return args.file.read_text(encoding="utf-8")
    if args.question:
        return " ".join(args.question)
    print("Describe the Metronome question or issue.")
    print("Finish with Ctrl+Z then Enter on Windows, or Ctrl+D on macOS/Linux.")
    return sys.stdin.read()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Answer a Metronome question using local documentation and grounded AI.",
    )
    parser.add_argument("question", nargs="*", help="Question or issue text.")
    parser.add_argument("--file", type=Path, help="Read the question from a text file.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/metronome_docs.db"),
        help="SQLite documentation database.",
    )
    parser.add_argument("--provider", choices=["gemini", "mock"], default=None)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    load_config()
    database_path = args.database
    if not database_path.is_absolute():
        database_path = _PROJECT_ROOT / database_path
    if not database_path.exists():
        parser.error(f"Database not found: {database_path}")

    question = _read_question(args).strip()
    if not question:
        parser.error("Question or issue must not be empty.")

    result = answer_metronome_question(
        question,
        database_path,
        provider_name=args.provider,
        persist=not args.no_persist,
    )

    report = result.investigation
    draft = result.answer

    print("\n=== Grounded Answer ===\n")
    print(draft.body)

    print("\n=== Mapped Concepts ===")
    for code in report.selected_concept_codes:
        print(f"- {code}")

    print("\n=== Relevant Documentation ===")
    for source in report.documentation_sources:
        heading = f" — {source.heading}" if source.heading else ""
        print(f"- {source.page_title}{heading}")
        print(f"  {source.source_url}")

    print("\n=== Observations ===")
    for observation in report.observations:
        print(f"- {observation.statement}")

    print("\n=== Hypotheses ===")
    if report.hypotheses:
        for hypothesis in report.hypotheses:
            print(f"- UNCONFIRMED: {hypothesis.title}")
    else:
        print("- None supported yet.")

    print("\n=== Missing Evidence ===")
    for missing in report.missing_evidence:
        print(f"- {missing.field}: {missing.reason}")

    print("\n=== Investigation Checklist ===")
    for step in report.investigation_steps:
        print(f"{step.order}. {step.action}")

    print("\n=== Validation ===")
    print(f"Provider: {draft.provider}")
    print(f"Model: {draft.model}")
    print(f"Status: {draft.validation_status}")
    print(f"Fact codes: {', '.join(draft.used_fact_codes) or 'none'}")
    print(f"Sources: {', '.join(draft.used_source_urls) or 'none'}")
    if draft.validation_errors:
        print("Errors:")
        for error in draft.validation_errors:
            print(f"- {error}")
    if draft.validation_warnings:
        print("Warnings:")
        for warning in draft.validation_warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
