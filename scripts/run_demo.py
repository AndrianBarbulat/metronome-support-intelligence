#!/usr/bin/env python3
"""Metronome Support Intelligence — local development wrapper.

Run::

    python scripts/run_demo.py

Then open http://127.0.0.1:8501.

This is the same application served by ``vercel dev``.  It imports the
single Flask application from ``app.py`` rather than duplicating routes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app import app
from src.drafting.config import load_config

load_config()

PORT = int(os.getenv("DEMO_PORT", "8501"))
DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def _check() -> int:
    from src.database.repository import DocumentationRepository

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1
    repo = DocumentationRepository(DB_PATH)
    try:
        conn = repo._get_conn()
        articles = conn.execute(
            "SELECT COUNT(*) FROM documentation_pages WHERE status='active'"
        ).fetchone()[0]
        cases = conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0]
        drafts = conn.execute(
            "SELECT COUNT(*) FROM support_generated_drafts"
        ).fetchone()[0]
    finally:
        repo.close()
    print(f"Application ready. Documentation articles: {articles}")
    print(f"Saved cases: {cases}; generated drafts: {drafts}")
    gemini_ready = bool(os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_MODEL"))
    print(f"Gemini configured: {'yes' if gemini_ready else 'no'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Metronome Support Intelligence (local development)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration without starting the server.",
    )
    args = parser.parse_args()
    if args.check:
        raise SystemExit(_check())
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print(
            "Run scripts/sync_documentation.py and "
            "scripts/process_documentation.py first."
        )
        raise SystemExit(1)
    print("Metronome Support Intelligence")
    print(f"Open: http://127.0.0.1:{PORT}")
    print(
        "Questions, analyses, documentation links, grounded answers "
        "and reviews are persisted."
    )
    print("Press Ctrl+C to stop.")
    app.run(host="127.0.0.1", port=PORT, debug=False)


if __name__ == "__main__":
    main()