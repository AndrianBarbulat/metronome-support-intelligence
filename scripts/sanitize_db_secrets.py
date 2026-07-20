"""Remove Slack webhook URLs and other secrets from the documentation database.

Uses raw content-based sanitization that works even with FTS triggers.
"""
import re
import sqlite3
from pathlib import Path

DB_PATH = Path("data/metronome_docs.db")
HOOK_PATTERN = re.compile(
    r"https://hooks\.slack\.com/services/[^\s<>\"')\]]+", re.IGNORECASE
)

REDACTED_URL = "https://hooks.slack.com/REDACTED"


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 1. Check schema for documentation_chunks FTS triggers
    triggers = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='documentation_chunks'"
    ).fetchall()
    print(f"FTS triggers on documentation_chunks: {len(triggers)}")
    for t in triggers:
        print(f"  {t['name']}")

    # Drop FTS triggers so we can UPDATE directly
    for t in triggers:
        conn.execute(f"DROP TRIGGER {t['name']}")

    # 2. Sanitize documentation_versions.raw_markdown
    rows = conn.execute(
        "SELECT id, raw_markdown FROM documentation_versions "
        "WHERE raw_markdown LIKE '%hooks.slack.com%'"
    ).fetchall()
    print(f"\nVersion rows with Slack webhooks: {len(rows)}")
    for row in rows:
        sanitized = HOOK_PATTERN.sub(REDACTED_URL, row["raw_markdown"])
        conn.execute(
            "UPDATE documentation_versions SET raw_markdown = ? WHERE id = ?",
            (sanitized, row["id"]),
        )
        print(f"  Sanitized version id={row['id']}")

    # 3. Sanitize documentation_chunks.content
    rows = conn.execute(
        "SELECT id, content FROM documentation_chunks "
        "WHERE content LIKE '%hooks.slack.com%'"
    ).fetchall()
    print(f"\nChunk rows with Slack webhooks: {len(rows)}")
    for row in rows:
        sanitized = HOOK_PATTERN.sub(REDACTED_URL, row["content"])
        conn.execute(
            "UPDATE documentation_chunks SET content = ? WHERE id = ?",
            (sanitized, row["id"]),
        )
        print(f"  Sanitized chunk id={row['id']}")

    # 4. Rebuild FTS index from scratch
    conn.execute("DELETE FROM documentation_chunks_fts")
    conn.execute(
        "INSERT INTO documentation_chunks_fts(rowid, content) "
        "SELECT id, content FROM documentation_chunks"
    )
    print("\nFTS index rebuilt.")

    # 5. Re-create the FTS triggers
    for t in triggers:
        conn.executescript(t["sql"])
    print(f"Re-created {len(triggers)} FTS triggers.")

    conn.commit()
    conn.close()
    print("\nDone. Database sanitized — Slack webhook URLs replaced with REDACTED.")


if __name__ == "__main__":
    main()