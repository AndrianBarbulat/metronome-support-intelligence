#!/usr/bin/env python3
"""Reset demo/support data while preserving documentation."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database.repository import DocumentationRepository

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"


def main() -> None:
    print("Resetting demo and support data...")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print("Database not found. Nothing to reset.")
        return

    # Safety check — refuse to delete if this doesn't look like our database
    if not str(DB_PATH).endswith("metronome_docs.db"):
        print("SAFETY: Refusing to delete from an unrecognized database path.")
        sys.exit(1)

    repo = DocumentationRepository(DB_PATH)
    repo.initialize_schema()

    # Count before
    before_pages = repo.count_documentation_pages()
    print(f"Documentation pages before: {before_pages}")

    counts = repo.delete_demo_data()
    for table, count in sorted(counts.items()):
        if count > 0:
            print(f"  Deleted {count} rows from {table}")

    after_pages = repo.count_documentation_pages()
    print(f"Documentation pages after:  {after_pages}")

    if after_pages != before_pages:
        print("WARNING: Documentation pages changed during reset!")
        sys.exit(1)

    print("Demo data reset complete. Documentation is preserved.")
    repo.close()


if __name__ == "__main__":
    main()