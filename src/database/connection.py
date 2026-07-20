"""SQLite connection management for the documentation database."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

_VERCEL_PACKAGED_DB = Path("/var/task/data/metronome_docs.db")
_VERCEL_RUNTIME_DB = Path("/tmp/metronome_docs.db")
_PROJECT_DB = Path("data/metronome_docs.db")


def resolve_db_path(explicit_path: Path | None = None) -> Path:
    """Return the resolved database path.

    Resolution rules (first match wins):

    1. *explicit_path* supplied by a test / script
       → return it unchanged

    2. ``VERCEL=1`` environment variable is set
       → copy the packaged database from ``/var/task/data/metronome_docs.db``
         to ``/tmp/metronome_docs.db`` (atomic copy + rename) and return the
         ``/tmp`` path.  Raises :exc:`FileNotFoundError` with a clear message
         if the packaged database is missing.

    3. Local development (default)
       → return ``data/metronome_docs.db`` relative to the current working
         directory.
    """
    if explicit_path is not None:
        return explicit_path

    is_vercel = os.getenv("VERCEL", "") == "1"

    if is_vercel:
        if _VERCEL_RUNTIME_DB.exists():
            return _VERCEL_RUNTIME_DB
        if not _VERCEL_PACKAGED_DB.exists():
            raise FileNotFoundError(
                f"Packaged database not found at {_VERCEL_PACKAGED_DB}. "
                "Ensure the prebuilt SQLite database is included in the "
                "Vercel deployment."
            )
        _copy_atomic(_VERCEL_PACKAGED_DB, _VERCEL_RUNTIME_DB)
        return _VERCEL_RUNTIME_DB

    return _PROJECT_DB


def _copy_atomic(src: Path, dst: Path) -> None:
    """Copy *src* to *dst* atomically via a temporary sibling.

    Writes to a temporary file on the same volume and then renames, so
    concurrent readers never see a partially-written database.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst_tmp = Path(dst.parent, f".{dst.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(src, dst_tmp)
        dst_tmp.replace(dst)
    finally:
        if dst_tmp.exists():
            dst_tmp.unlink(missing_ok=True)


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
