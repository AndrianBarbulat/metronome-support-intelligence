#!/usr/bin/env python3
"""Migrate SQLite documentation and support records to PostgreSQL.

Reads from ``data/metronome_docs.db`` and writes to ``DATABASE_URL``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))


def _safe_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port}{parsed.path}"
    except Exception:
        return "***"


def _get_count(cur, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def main() -> None:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set.")
        print("  set DATABASE_URL=postgresql://user:password@host:5432/dbname?pgbouncer=true")
        raise SystemExit(1)

    sqlite_path = _PROJECT_ROOT / "data" / "metronome_docs.db"
    if not sqlite_path.exists():
        print(f"ERROR: SQLite database not found: {sqlite_path}")
        raise SystemExit(1)

    print(f"Source: {sqlite_path}")
    print(f"Target: {_safe_url(db_url)}")

    import sqlite3
    sqlite = sqlite3.connect(str(sqlite_path))
    sqlite.row_factory = sqlite3.Row

    import psycopg2
    import psycopg2.extras
    pg = psycopg2.connect(db_url)
    pg.cursor_factory = psycopg2.extras.RealDictCursor
    pg.autocommit = False

    schema_path = _PROJECT_ROOT / "database" / "postgres_schema.sql"
    print("Applying PostgreSQL schema...")
    pg_cur = pg.cursor()
    pg_cur.execute(schema_path.read_text(encoding="utf-8"))
    pg.commit()
    print("Schema applied.")

    tables_order = [
        "documentation_pages", "documentation_versions", "documentation_sync_runs",
        "documentation_parsed_versions", "documentation_chunks",
        "support_tickets", "support_ticket_evidence", "support_ticket_analyses",
        "support_ticket_document_links", "support_ticket_resolutions",
        "support_resolution_identifiers", "support_hypothesis_outcomes",
        "support_regression_cases", "support_feedback_items", "support_generated_drafts",
    ]

    total = 0
    for table in tables_order:
        sqlite_cur = sqlite.execute(f"SELECT * FROM {table}")
        rows = sqlite_cur.fetchall()
        if not rows:
            print(f"  {table}: 0 rows")
            continue
        col_names = [d[0] for d in sqlite_cur.description]
        sql_cols = ", ".join(col_names)
        placeholders = ", ".join(["%s"] * len(col_names))
        pg_cur.execute(f"DELETE FROM {table}")
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            values = [tuple(row[c] for c in col_names) for row in batch]
            args_str = ", ".join(
                pg_cur.mogrify(f"({placeholders})", v).decode("utf-8") for v in values
            )
            pg_cur.execute(f"INSERT INTO {table} ({sql_cols}) VALUES {args_str} ON CONFLICT DO NOTHING")
        pg.commit()
        pg_count = _get_count(pg_cur, table)
        print(f"  {table}: {len(rows)} rows, {pg_count} verified")
        total += len(rows)

    for table in tables_order:
        try:
            pg_cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), false)"
            )
        except Exception:
            pass
    pg.commit()

    print()
    print("Verification:")
    s_total = p_total = 0
    for table in tables_order:
        sc = _get_count(sqlite, table)
        pc = _get_count(pg_cur, table)
        ok = "OK" if sc == pc else "MISMATCH"
        print(f"  {table}: SQLite={sc}, PG={pc} {ok}")
        s_total += sc
        p_total += pc
    print(f"  TOTAL: SQLite={s_total}, PG={p_total}")

    sqlite.close()
    pg.close()
    print(f"\nMigration complete. {total} records migrated.")


if __name__ == "__main__":
    main()