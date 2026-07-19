"""SQLite connection management for the documentation database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Return a :class:`sqlite3.Connection` for *db_path* with recommended
    settings.

    Enables foreign keys, WAL journal mode, and uses the built-in
    :func:`sqlite3.Row` factory for dict-like access.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn