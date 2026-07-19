#!/usr/bin/env python3
"""Confirm a human-submitted support-ticket resolution."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Confirm a human-submitted ticket resolution.")
    parser.add_argument("--input", type=Path, required=True, help="Resolution JSON file.")
    parser.add_argument("--database", type=Path, default=Path("data/metronome_docs.db"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show-comparison", action="store_true")
    parser.add_argument("--show-feedback", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.support.resolution_service import confirm_ticket_resolution, load_resolution_from_json

    input_path = _resolve(project_root, args.input)
    database_path = _resolve(project_root, args.database)
    target_db = database_path

    with tempfile.TemporaryDirectory() if args.dry_run else _null_context() as tmp_dir:
        if args.dry_run:
            target_db = Path(tmp_dir) / "dry-run.db"
            shutil.copyfile(database_path, target_db)

        resolution = load_resolution_from_json(input_path)
        resolution = _ensure_investigation_context(project_root, input_path, resolution, target_db)
        confirmed = confirm_ticket_resolution(resolution, target_db)

        payload = asdict(confirmed)
        if args.output:
            output_path = _resolve(project_root, args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        prefix = "Dry-run confirmed" if args.dry_run else "Confirmed"
        print(f"{prefix} resolution {confirmed.id}")
        print(f"Ticket: {confirmed.ticket_id}")
        print(f"Root cause: {confirmed.root_cause_code}")
        print(f"Status: {confirmed.resolution_status}")
        if confirmed.regression_case:
            print(f"Regression case: {confirmed.regression_case.case_code}")

        if args.show_comparison:
            print("\nHypothesis outcomes")
            for outcome in confirmed.hypothesis_outcomes:
                print(f"- {outcome.hypothesis_code}: {outcome.outcome}")

        if args.show_feedback:
            print("\nFeedback proposals")
            for item in confirmed.feedback_items:
                print(f"- [{item.status}] {item.gap_code}: {item.title}")


def _ensure_investigation_context(project_root: Path, input_path: Path, resolution, database_path: Path):
    if resolution.ticket_id > 0 and resolution.analysis_id > 0:
        return resolution

    from src.database.repository import DocumentationRepository
    from src.support.analyzer import analyze_support_ticket
    from src.support.ticket_parser import load_ticket_from_json

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    ticket_file = raw.get("ticket_input_file")
    if not ticket_file:
        raise SystemExit("Resolution JSON must include ticket_id/analysis_id or ticket_input_file.")
    ticket_path = _resolve(project_root, Path(ticket_file))
    ticket = load_ticket_from_json(ticket_path)

    repo = DocumentationRepository(database_path)
    try:
        repo.initialize_schema()
        before = repo._get_conn().execute("SELECT COALESCE(MAX(id), 0) FROM support_tickets").fetchone()[0]
    finally:
        repo.close()

    analyze_support_ticket(ticket=ticket, database_path=database_path, persist=True)

    repo = DocumentationRepository(database_path)
    try:
        repo.initialize_schema()
        ticket_row = repo._get_conn().execute(
            """SELECT id FROM support_tickets
               WHERE id > ?
               ORDER BY id DESC
               LIMIT 1""",
            (before,),
        ).fetchone()
        if ticket_row is None:
            raise SystemExit("Ticket investigation was not persisted.")
        analysis = repo.get_latest_analysis_for_ticket(ticket_row["id"])
        if analysis is None:
            raise SystemExit("Ticket analysis was not persisted.")
        return replace(resolution, ticket_id=ticket_row["id"], analysis_id=analysis["id"])
    finally:
        repo.close()


def _resolve(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else project_root / path


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


if __name__ == "__main__":
    main()
