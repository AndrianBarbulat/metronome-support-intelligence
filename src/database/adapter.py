"""Database adapter supporting SQLite (local) and PostgreSQL (production).

Selects backend based on DATABASE_URL environment variable.
On Vercel (VERCEL=1) without DATABASE_URL, SQLite is used via the
packaged database copied to /tmp.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from src.database.connection import resolve_db_path


class DatabaseAdapter:
    """Unified database adapter over SQLite or PostgreSQL."""

    def __init__(self, db_path: Path | None = None, db_url: str | None = None):
        self._db_path = db_path
        self._db_url = db_url
        self._backend: str | None = None
        self._conn: Any = None
        self._module: Any = None

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------
    def _resolve_backend(self) -> str:
        if self._backend:
            return self._backend
        url = self._db_url or os.getenv("DATABASE_URL", "")
        if url:
            self._backend = "postgresql"
        elif self._db_path:
            self._backend = "sqlite"
        else:
            path = os.getenv("DATABASE_PATH", "")
            if path:
                self._backend = "sqlite"
                self._db_path = Path(path)
            else:
                # Use the central resolver (handles Vercel /tmp copy automatically)
                self._db_path = resolve_db_path()
                self._backend = "sqlite"
        return self._backend

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def get_connection(self):
        backend = self._resolve_backend()
        if backend == "sqlite":
            return self._get_sqlite_connection()
        return self._get_pg_connection()

    def _get_sqlite_connection(self):
        if self._conn is not None:
            return self._conn
        import sqlite3
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        self._conn = conn
        return conn

    def _get_pg_connection(self):
        if self._conn is not None and not getattr(self._conn, 'closed', True):
            try:
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return self._conn
            except Exception:
                self._conn = None
        import psycopg2
        import psycopg2.extras
        self._conn = psycopg2.connect(self._db_url or os.getenv("DATABASE_URL", ""))
        self._conn.cursor_factory = psycopg2.extras.RealDictCursor
        return self._conn

    # ------------------------------------------------------------------
    # SQL translation
    # ------------------------------------------------------------------
    def translate_sql(self, sql: str) -> str:
        """Convert SQLite SQL to the active backend dialect."""
        if self._resolve_backend() == "sqlite":
            return sql
        return _sqlite_to_pg(sql)

    # ------------------------------------------------------------------
    # Parameter placeholder
    # ------------------------------------------------------------------
    @property
    def placeholder(self) -> str:
        return "?" if self._resolve_backend() == "sqlite" else "%s"

    # ------------------------------------------------------------------
    # Row factory
    # ------------------------------------------------------------------
    @staticmethod
    def dict_row(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        if isinstance(row, dict):
            return row
        try:
            return dict(row)
        except (TypeError, ValueError):
            return {"value": row}

    # ------------------------------------------------------------------
    # Higher-level execute helpers
    # ------------------------------------------------------------------
    def execute(self, conn, sql: str, params: tuple | None = None) -> Any:
        """Execute SQL and return cursor for the active backend."""
        translated = self.translate_sql(sql)
        param_style = self.placeholder
        if param_style == "%s" and "?" in translated:
            translated = translated.replace("?", "%s")
        if params is None:
            params = ()
        return conn.execute(translated, params)

    def execute_script(self, conn, sql: str) -> None:
        """Execute a multi-statement script."""
        backend = self._resolve_backend()
        if backend == "sqlite":
            conn.executescript(sql)
            return
        # PostgreSQL: split and execute each statement
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        cur = conn.cursor()
        for stmt in statements:
            translated = self.translate_sql(stmt)
            cur.execute(translated)
        cur.close()
        conn.commit()

    def run_migrations(self, conn, schema_sql: str) -> None:
        """Execute CREATE TABLE IF NOT EXISTS style migrations."""
        self.execute_script(conn, schema_sql)

    def last_row_id(self, cursor) -> int | None:
        """Return the last inserted row ID."""
        backend = self._resolve_backend()
        if backend == "sqlite":
            return cursor.lastrowid
        # PostgreSQL with RETURNING
        try:
            return cursor.fetchone()["id"]
        except Exception:
            return None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ------------------------------------------------------------------
# SQL dialect translation helpers
# ------------------------------------------------------------------
def _sqlite_to_pg(sql: str) -> str:
    """Translate SQLite-specific SQL to PostgreSQL."""
    # Remove PRAGMA statements
    sql = re.sub(r"^\s*PRAGMA\s+.*$", "", sql, flags=re.MULTILINE | re.IGNORECASE)

    # Replace AUTOINCREMENT with nothing (PostgreSQL uses SERIAL in schema)
    sql = re.sub(
        r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
        "SERIAL PRIMARY KEY",
        sql,
        flags=re.IGNORECASE,
    )

    # Convert json_extract(col, '$.key') → col::jsonb->>'key'
    sql = re.sub(
        r"json_extract\(\s*(\w+(?:\.\w+)?)\s*,\s*'\$\.(\w+(?:\.\w+)*)'\s*\)",
        r"\1::jsonb->>'\2'",
        sql,
        flags=re.IGNORECASE,
    )

    # Multi-level json_extract with LIKE
    sql = re.sub(
        r"json_extract\(\s*(\w+(?:\.\w+)?)\s*,\s*'\$\.(\w+(?:\.\w+)*)'\s*\)\s+LIKE",
        r"\1::jsonb->>'\2' LIKE",
        sql,
        flags=re.IGNORECASE,
    )

    # json_extract = 1
    sql = re.sub(
        r"json_extract\(\s*(\w+(?:\.\w+)?)\s*,\s*'\$\.(\w+(?:\.\w+)*)'\s*\)\s*=\s*1",
        r"(\1::jsonb->>'\2')::boolean = true",
        sql,
        flags=re.IGNORECASE,
    )

    # COLLATE NOCASE → COLLATE "en_US.utf8"
    sql = sql.replace("COLLATE NOCASE", 'COLLATE "en_US.utf8"')

    # IS NULL / IS NOT NULL comparisons for json_extract
    sql = re.sub(
        r"json_extract\(\s*(\w+(?:\.\w+)?)\s*,\s*'\$\.(\w+(?:\.\w+)*)'\s*\)\s+IS\s+NOT\s+NULL",
        r"\1::jsonb->>'\2' IS NOT NULL",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"json_extract\(\s*(\w+(?:\.\w+)?)\s*,\s*'\$\.(\w+(?:\.\w+)*)'\s*\)\s+IS\s+NULL",
        r"\1::jsonb->>'\2' IS NULL",
        sql,
        flags=re.IGNORECASE,
    )

    # json_extract != ''
    sql = re.sub(
        r"json_extract\(\s*(\w+(?:\.\w+)?)\s*,\s*'\$\.(\w+(?:\.\w+)*)'\s*\)\s*!=\s*''",
        r"\1::jsonb->>'\2' != ''",
        sql,
        flags=re.IGNORECASE,
    )

    # Replace ? with %s (only for PostgreSQL)
    # This is done at execute time

    return sql


# ------------------------------------------------------------------
# Singleton adapter factory
# ------------------------------------------------------------------
_adapter: DatabaseAdapter | None = None


def get_adapter() -> DatabaseAdapter:
    global _adapter
    if _adapter is None:
        _adapter = DatabaseAdapter()
    return _adapter


def reset_adapter() -> None:
    global _adapter
    if _adapter is not None:
        _adapter.close()
    _adapter = None