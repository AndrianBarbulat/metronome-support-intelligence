"""Tests for the documentation synchronization pipeline."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.documentation.hashing import calculate_content_hash
from src.documentation.index_loader import (
    IndexLoadError,
    load_documentation_index,
)
from src.documentation.models import (
    DocumentationEntry,
    DownloadResult,
    SyncSummary,
)
from src.database.connection import get_connection
from src.database.repository import DocumentationRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_temp_db() -> Path:
    """Return a path to a temporary SQLite database file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return Path(tmp.name)


def _make_index_file(entries: list[dict]) -> Path:
    """Write a minimal index JSON and return its path."""
    data = {
        "source_file": "data/llms.txt",
        "parsed_at": "2026-01-01T00:00:00Z",
        "total_entries": len(entries),
        "entries": entries,
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8",
    )
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def _make_entry(url: str = "https://docs.metronome.com/api-reference/test.md",
                title: str = "Test Article",
                description: str = "A test article.") -> DocumentationEntry:
    return DocumentationEntry(
        title=title,
        url=url,
        description=description,
        document_type="api_reference",
        category="test",
        subcategory=None,
        slug="test",
        file_name="test.md",
        source_line_number=1,
        raw_line="- [Test](...)...",
    )


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------
class TestHashing:
    def test_deterministic(self):
        h1 = calculate_content_hash("hello")
        h2 = calculate_content_hash("hello")
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content(self):
        h1 = calculate_content_hash("hello")
        h2 = calculate_content_hash("world")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Index loader
# ---------------------------------------------------------------------------
class TestIndexLoader:
    def test_load_valid_index(self):
        entries = [
            {
                "title": "Test",
                "url": "https://docs.metronome.com/api-reference/test.md",
                "description": "desc",
                "document_type": "api_reference",
                "category": "alerts",
                "subcategory": None,
                "slug": "test",
                "file_name": "test.md",
                "source_line_number": 1,
                "raw_line": "- [Test](...)",
            }
        ]
        path = _make_index_file(entries)
        try:
            idx = load_documentation_index(path)
            assert idx.source_file == "data/llms.txt"
            assert len(idx.entries) == 1
            assert idx.entries[0].title == "Test"
        finally:
            path.unlink()

    def test_missing_file(self):
        path = Path(tempfile.gettempdir()) / "does_not_exist.json"
        with pytest.raises(IndexLoadError, match="not found"):
            load_documentation_index(path)

    def test_invalid_json(self):
        path = _make_index_file([])
        try:
            path.write_text("not json", encoding="utf-8")
            with pytest.raises(IndexLoadError, match="Invalid JSON"):
                load_documentation_index(path)
        finally:
            path.unlink()

    def test_missing_entries_key(self):
        path = _make_index_file([])
        try:
            path.write_text('{"source_file": "x"}', encoding="utf-8")
            with pytest.raises(IndexLoadError, match="missing the 'entries'"):
                load_documentation_index(path)
        finally:
            path.unlink()

    def test_invalid_article_url_skipped(self):
        entries = [
            {
                "title": "Bad",
                "url": "https://example.com/article.md",
                "description": "",
                "document_type": "",
                "category": None,
                "subcategory": None,
                "slug": "",
                "file_name": "",
                "source_line_number": 1,
                "raw_line": "",
            },
            {
                "title": "Good",
                "url": "https://docs.metronome.com/api-reference/test.md",
                "description": "",
                "document_type": "",
                "category": None,
                "subcategory": None,
                "slug": "",
                "file_name": "",
                "source_line_number": 2,
                "raw_line": "",
            },
        ]
        path = _make_index_file(entries)
        try:
            idx = load_documentation_index(path)
            assert len(idx.entries) == 1
            assert idx.entries[0].title == "Good"
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# Repository / schema
# ---------------------------------------------------------------------------
class TestRepository:
    def test_schema_initialization(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            conn = get_connection(db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {r["name"] for r in tables}
            assert "documentation_pages" in table_names
            assert "documentation_versions" in table_names
            assert "documentation_sync_runs" in table_names
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_start_and_complete_sync_run(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            run_id = repo.start_sync_run("idx.json", "abc123", 10)
            assert run_id > 0

            summary = SyncSummary(
                discovered_count=10, fetched_count=9, new_count=5,
                changed_count=1, unchanged_count=3, failed_count=1,
                missing_count=0,
            )
            errors = [{"url": "x", "title": "x", "error_type": "http_error",
                        "http_status": 500, "message": "fail"}]
            repo.complete_sync_run(run_id, summary, errors, "completed_with_errors")

            conn = get_connection(db_path)
            row = conn.execute(
                "SELECT * FROM documentation_sync_runs WHERE id = ?", (run_id,)
            ).fetchone()
            assert row is not None
            assert row["status"] == "completed_with_errors"
            assert row["fetched_count"] == 9
            assert row["new_count"] == 5
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_create_page_with_version(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            entry = _make_entry()
            result = DownloadResult(
                url=entry.url, success=True,
                raw_markdown="# Hello", http_status=200,
                final_url=entry.url,
            )
            content_hash = calculate_content_hash("# Hello")
            page_id = repo.create_page_with_version(
                entry, result, content_hash, "2026-01-01T00:00:00Z",
            )
            assert page_id > 0

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT * FROM documentation_pages WHERE id = ?", (page_id,)
            ).fetchone()
            assert page["current_version"] == 1
            assert page["current_content_hash"] == content_hash
            assert page["status"] == "active"

            ver = conn.execute(
                "SELECT * FROM documentation_versions WHERE page_id = ?", (page_id,)
            ).fetchone()
            assert ver["version_number"] == 1
            assert ver["raw_markdown"] == "# Hello"
            assert ver["content_hash"] == content_hash
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_unchanged_does_not_create_new_version(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            entry = _make_entry()
            result = DownloadResult(
                url=entry.url, success=True,
                raw_markdown="# Hello", http_status=200,
                final_url=entry.url,
            )
            c_hash = calculate_content_hash("# Hello")
            t1 = "2026-01-01T00:00:00Z"
            t2 = "2026-01-02T00:00:00Z"

            page_id = repo.create_page_with_version(entry, result, c_hash, t1)
            repo.mark_page_unchanged(page_id, entry, t2)

            conn = get_connection(db_path)
            versions = conn.execute(
                "SELECT COUNT(*) as cnt FROM documentation_versions WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            assert versions["cnt"] == 1
            page = conn.execute(
                "SELECT current_version, last_checked_at FROM documentation_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            assert page["current_version"] == 1
            assert page["last_checked_at"] == t2
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_changed_creates_new_version(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            entry = _make_entry()
            t1 = "2026-01-01T00:00:00Z"
            t2 = "2026-01-02T00:00:00Z"

            r1 = DownloadResult(url=entry.url, success=True, raw_markdown="# V1",
                                http_status=200, final_url=entry.url)
            h1 = calculate_content_hash("# V1")
            page_id = repo.create_page_with_version(entry, r1, h1, t1)

            r2 = DownloadResult(url=entry.url, success=True, raw_markdown="# V2",
                                http_status=200, final_url=entry.url)
            h2 = calculate_content_hash("# V2")
            new_ver = repo.create_new_version(page_id, entry, r2, h2, t2)
            assert new_ver == 2

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT current_version, current_content_hash FROM documentation_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            assert page["current_version"] == 2
            assert page["current_content_hash"] == h2

            v1_row = conn.execute(
                "SELECT * FROM documentation_versions WHERE page_id = ? AND version_number = 1",
                (page_id,),
            ).fetchone()
            assert v1_row is not None
            assert v1_row["raw_markdown"] == "# V1"

            v2_row = conn.execute(
                "SELECT * FROM documentation_versions WHERE page_id = ? AND version_number = 2",
                (page_id,),
            ).fetchone()
            assert v2_row is not None
            assert v2_row["raw_markdown"] == "# V2"
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_metadata_update_without_content_version(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            entry = _make_entry(title="Old Title")
            result = DownloadResult(url=entry.url, success=True,
                                    raw_markdown="# X", http_status=200,
                                    final_url=entry.url)
            c_hash = calculate_content_hash("# X")
            page_id = repo.create_page_with_version(entry, result, c_hash, "t1")

            entry_new = _make_entry(title="New Title", description="Updated desc")
            repo.mark_page_unchanged(page_id, entry_new, "t2")

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT title, index_description, current_version FROM documentation_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            assert page["title"] == "New Title"
            assert page["index_description"] == "Updated desc"
            assert page["current_version"] == 1
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_record_fetch_failure(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            entry = _make_entry()
            repo.record_fetch_failure(entry, "t1")

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT * FROM documentation_pages WHERE source_url = ?", (entry.url,)
            ).fetchone()
            assert page["status"] == "fetch_failed"
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_mark_missing_pages(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()

            entry1 = _make_entry(url="https://docs.metronome.com/api-reference/a.md", title="A")
            entry2 = _make_entry(url="https://docs.metronome.com/api-reference/b.md", title="B")

            r = DownloadResult(url=entry1.url, success=True, raw_markdown="# A",
                               http_status=200, final_url=entry1.url)
            repo.create_page_with_version(entry1, r, calculate_content_hash("# A"), "t1")
            r2 = DownloadResult(url=entry2.url, success=True, raw_markdown="# B",
                                http_status=200, final_url=entry2.url)
            repo.create_page_with_version(entry2, r2, calculate_content_hash("# B"), "t1")

            missing = repo.mark_missing_pages({entry1.url}, "t2")
            assert missing == 1

            conn = get_connection(db_path)
            page_a = conn.execute(
                "SELECT status FROM documentation_pages WHERE source_url = ?", (entry1.url,)
            ).fetchone()
            page_b = conn.execute(
                "SELECT status FROM documentation_pages WHERE source_url = ?", (entry2.url,)
            ).fetchone()
            assert page_a["status"] == "active"
            assert page_b["status"] == "missing_from_index"
            conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_reactivate_missing_page(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()

            entry = _make_entry()
            r = DownloadResult(url=entry.url, success=True, raw_markdown="# X",
                               http_status=200, final_url=entry.url)
            c_hash = calculate_content_hash("# X")
            repo.create_page_with_version(entry, r, c_hash, "t1")
            repo.mark_missing_pages(set(), "t2")

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT status FROM documentation_pages WHERE source_url = ?", (entry.url,)
            ).fetchone()
            assert page["status"] == "missing_from_index"

            # Reappears
            page_id = conn.execute(
                "SELECT id FROM documentation_pages WHERE source_url = ?",
                (entry.url,),
            ).fetchone()["id"]
            repo.mark_page_unchanged(page_id, entry, "t3")

            conn2 = get_connection(db_path)
            page2 = conn2.execute(
                "SELECT status FROM documentation_pages WHERE source_url = ?", (entry.url,)
            ).fetchone()
            assert page2["status"] == "active"
            conn.close()
            conn2.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_foreign_key_enforcement(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            with pytest.raises(sqlite3.IntegrityError):
                conn = get_connection(db_path)
                try:
                    conn.execute(
                        "INSERT INTO documentation_versions "
                        "(page_id, version_number, content_hash, raw_markdown, fetched_at) "
                        "VALUES (9999, 1, 'abc', '', 't')"
                    )
                finally:
                    conn.close()
        finally:
            repo.close()
            db_path.unlink()

    def test_atomic_page_and_version(self):
        db_path = _make_temp_db()
        repo = DocumentationRepository(db_path)
        try:
            repo.initialize_schema()
            entry = _make_entry()
            result = DownloadResult(url=entry.url, success=True,
                                    raw_markdown="# Good", http_status=200,
                                    final_url=entry.url)
            c_hash = calculate_content_hash("# Good")
            page_id = repo.create_page_with_version(entry, result, c_hash, "t1")

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT current_version, current_content_hash FROM documentation_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            assert page["current_version"] == 1
            assert page["current_content_hash"] == c_hash
            conn.close()
        finally:
            repo.close()
            db_path.unlink()


# ---------------------------------------------------------------------------
# Downloader (mocked HTTP)
# ---------------------------------------------------------------------------
class TestDownloader:
    def test_successful_download(self):
        from src.documentation.downloader import download_article

        async def _run():
            async with __import__("httpx").AsyncClient() as client:
                sem = asyncio.Semaphore(1)
                with patch.object(client, "get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.text = "# Content"
                    mock_resp.status_code = 200
                    mock_resp.url = "https://docs.metronome.com/api-reference/test.md"
                    mock_get.return_value = mock_resp

                    entry = _make_entry()
                    result = await download_article(client, entry, sem)
                    assert result.success
                    assert result.raw_markdown == "# Content"
                    assert result.http_status == 200
            return True

        assert asyncio.run(_run())

    def test_http_404_no_retry(self):
        from src.documentation.downloader import download_article

        async def _run():
            async with __import__("httpx").AsyncClient() as client:
                sem = asyncio.Semaphore(1)
                with patch.object(client, "get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.text = "Not Found"
                    mock_resp.status_code = 404
                    mock_resp.url = "https://docs.metronome.com/api-reference/test.md"
                    mock_get.return_value = mock_resp

                    entry = _make_entry()
                    result = await download_article(client, entry, sem)
                    assert not result.success
                    assert result.http_status == 404
                    assert result.error_type == "http_error"
                    assert mock_get.call_count == 1
            return True

        assert asyncio.run(_run())

    def test_http_500_retries(self):
        from src.documentation.downloader import download_article

        async def _run():
            async with __import__("httpx").AsyncClient() as client:
                sem = asyncio.Semaphore(1)
                with patch.object(client, "get") as mock_get:
                    fail_resp = MagicMock()
                    fail_resp.text = "Error"
                    fail_resp.status_code = 500
                    fail_resp.url = "https://docs.metronome.com/api-reference/test.md"
                    mock_get.return_value = fail_resp

                    entry = _make_entry()
                    result = await download_article(client, entry, sem)
                    assert not result.success
                    assert mock_get.call_count == 3
            return True

        assert asyncio.run(_run())

    def test_http_429_retries(self):
        from src.documentation.downloader import download_article

        async def _run():
            async with __import__("httpx").AsyncClient() as client:
                sem = asyncio.Semaphore(1)
                with patch.object(client, "get") as mock_get:
                    fail_resp = MagicMock()
                    fail_resp.text = "Rate limited"
                    fail_resp.status_code = 429
                    fail_resp.url = "https://docs.metronome.com/api-reference/test.md"
                    mock_get.return_value = fail_resp

                    entry = _make_entry()
                    result = await download_article(client, entry, sem)
                    assert not result.success
                    assert mock_get.call_count == 3
            return True

        assert asyncio.run(_run())

    def test_timeout_retries(self):
        from src.documentation.downloader import download_article

        async def _run():
            async with __import__("httpx").AsyncClient() as client:
                sem = asyncio.Semaphore(1)
                with patch.object(client, "get", side_effect=__import__("httpx").TimeoutException("timeout")):
                    entry = _make_entry()
                    result = await download_article(client, entry, sem)
                    assert not result.success
                    assert result.error_type == "timeout"
            return True

        assert asyncio.run(_run())

    def test_follows_redirect(self):
        from src.documentation.downloader import download_article

        async def _run():
            async with __import__("httpx").AsyncClient() as client:
                sem = asyncio.Semaphore(1)
                with patch.object(client, "get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.text = "# Redirected"
                    mock_resp.status_code = 200
                    mock_resp.url = "https://docs.metronome.com/api-reference/final.md"
                    mock_get.return_value = mock_resp

                    entry = _make_entry()
                    result = await download_article(client, entry, sem)
                    assert result.success
                    assert result.final_url == "https://docs.metronome.com/api-reference/final.md"
            return True

        assert asyncio.run(_run())


# ---------------------------------------------------------------------------
# Synchronizer integration (mocked)
# ---------------------------------------------------------------------------
class TestSynchronizerIntegration:
    """Integration tests that mock the download function at the synchronizer level."""

    @patch("src.documentation.synchronizer.download_article")
    def test_first_run_all_new(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "Article A",
                    "url": "https://docs.metronome.com/api-reference/a.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": "test",
                    "subcategory": None,
                    "slug": "a",
                    "file_name": "a.md",
                    "source_line_number": 1,
                    "raw_line": "- [A](...)",
                },
            ]
            idx_path = _make_index_file(entries)

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True,
                    raw_markdown="# Article A Content",
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation
            summary = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))

            assert summary.discovered_count == 1
            assert summary.new_count == 1
            assert summary.fetched_count == 1
            assert summary.changed_count == 0
            assert summary.unchanged_count == 0
            assert summary.failed_count == 0

            conn = get_connection(db_path)
            pages = conn.execute("SELECT * FROM documentation_pages").fetchall()
            assert len(pages) == 1
            assert pages[0]["current_version"] == 1
            assert pages[0]["status"] == "active"

            versions = conn.execute("SELECT * FROM documentation_versions").fetchall()
            assert len(versions) == 1
            assert versions[0]["raw_markdown"] == "# Article A Content"
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_second_run_unchanged(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "Article A",
                    "url": "https://docs.metronome.com/api-reference/a.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": "test",
                    "subcategory": None,
                    "slug": "a",
                    "file_name": "a.md",
                    "source_line_number": 1,
                    "raw_line": "- [A](...)",
                },
            ]
            idx_path = _make_index_file(entries)

            MARKDOWN = "# Article A Content"

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True, raw_markdown=MARKDOWN,
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation

            summary1 = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))
            assert summary1.new_count == 1

            # Re-create the mock for second call
            mock_dl.side_effect = _fake
            summary2 = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))
            assert summary2.new_count == 0
            assert summary2.changed_count == 0
            assert summary2.unchanged_count == 1

            conn = get_connection(db_path)
            versions = conn.execute(
                "SELECT COUNT(*) as cnt FROM documentation_versions"
            ).fetchone()
            assert versions["cnt"] == 1
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_content_changed_creates_version_2(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "Article A",
                    "url": "https://docs.metronome.com/api-reference/a.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": "test",
                    "subcategory": None,
                    "slug": "a",
                    "file_name": "a.md",
                    "source_line_number": 1,
                    "raw_line": "- [A](...)",
                },
            ]
            idx_path = _make_index_file(entries)

            content_stack = ["# V1", "# V2"]

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True, raw_markdown=content_stack.pop(0),
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation

            s1 = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))
            assert s1.new_count == 1

            content_stack.append("# V2")
            mock_dl.side_effect = _fake
            s2 = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))
            assert s2.changed_count == 1

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT current_version FROM documentation_pages WHERE source_url = ?",
                ("https://docs.metronome.com/api-reference/a.md",),
            ).fetchone()
            assert page["current_version"] == 2

            v1 = conn.execute(
                "SELECT raw_markdown FROM documentation_versions WHERE version_number = 1"
            ).fetchone()
            v2 = conn.execute(
                "SELECT raw_markdown FROM documentation_versions WHERE version_number = 2"
            ).fetchone()
            assert v1["raw_markdown"] == "# V1"
            assert v2["raw_markdown"] == "# V2"
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_one_failed_download_does_not_stop_others(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "Good",
                    "url": "https://docs.metronome.com/api-reference/good.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": None,
                    "subcategory": None,
                    "slug": "good",
                    "file_name": "good.md",
                    "source_line_number": 1,
                    "raw_line": "",
                },
                {
                    "title": "Bad",
                    "url": "https://docs.metronome.com/api-reference/bad.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": None,
                    "subcategory": None,
                    "slug": "bad",
                    "file_name": "bad.md",
                    "source_line_number": 2,
                    "raw_line": "",
                },
            ]
            idx_path = _make_index_file(entries)

            async def _fake(client, entry, sem):
                if "bad" in entry.url:
                    return DownloadResult(
                        url=entry.url, success=False,
                        error_type="http_error", error_message="HTTP 500",
                        http_status=500, final_url=entry.url,
                    )
                return DownloadResult(
                    url=entry.url, success=True, raw_markdown="# Good",
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation
            summary = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))

            assert summary.discovered_count == 2
            assert summary.fetched_count == 1
            assert summary.failed_count == 1

            conn = get_connection(db_path)
            good = conn.execute(
                "SELECT status FROM documentation_pages WHERE source_url = ?",
                ("https://docs.metronome.com/api-reference/good.md",),
            ).fetchone()
            bad = conn.execute(
                "SELECT status FROM documentation_pages WHERE source_url = ?",
                ("https://docs.metronome.com/api-reference/bad.md",),
            ).fetchone()
            assert good["status"] == "active"
            assert bad["status"] == "fetch_failed"
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_correct_sync_counters(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries_data = [
                {"title": f"Article {i}",
                 "url": f"https://docs.metronome.com/api-reference/{i}.md",
                 "description": "", "document_type": "api_reference",
                 "category": None, "subcategory": None,
                 "slug": str(i), "file_name": f"{i}.md",
                 "source_line_number": i, "raw_line": ""}
                for i in range(5)
            ]
            idx_path = _make_index_file(entries_data)

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True,
                    raw_markdown=f"# Content for {entry.title}",
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation

            summary = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=2))
            assert summary.discovered_count == 5
            assert summary.fetched_count == 5
            assert summary.new_count == 5
            assert summary.failed_count == 0

            mock_dl.side_effect = _fake
            summary2 = asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=2))
            assert summary2.new_count == 0
            assert summary2.unchanged_count == 5
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_sync_errors_recorded_as_json(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "Fail",
                    "url": "https://docs.metronome.com/api-reference/fail.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": None,
                    "subcategory": None,
                    "slug": "fail",
                    "file_name": "fail.md",
                    "source_line_number": 1,
                    "raw_line": "",
                },
            ]
            idx_path = _make_index_file(entries)

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=False,
                    error_type="http_error", error_message="HTTP 500",
                    http_status=500,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation
            asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))

            conn = get_connection(db_path)
            run = conn.execute(
                "SELECT status, errors_json FROM documentation_sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert run["status"] == "completed_with_errors"
            errors = json.loads(run["errors_json"])
            assert len(errors) == 1
            assert errors[0]["http_status"] == 500
            assert "Fail" in errors[0]["title"]
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_preserves_yaml_and_code_fences(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "Complex",
                    "url": "https://docs.metronome.com/api-reference/complex.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": None,
                    "subcategory": None,
                    "slug": "complex",
                    "file_name": "complex.md",
                    "source_line_number": 1,
                    "raw_line": "",
                },
            ]
            idx_path = _make_index_file(entries)

            complex_md = """---
title: Test
openapi: true
---

# Heading

```python
def foo():
    pass
```

```curl
curl -X POST https://api.example.com
```

| Col1 | Col2 |
|------|------|
| A    | B    |
"""

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True, raw_markdown=complex_md,
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation
            asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))

            conn = get_connection(db_path)
            ver = conn.execute(
                "SELECT raw_markdown FROM documentation_versions LIMIT 1"
            ).fetchone()
            assert "---" in ver["raw_markdown"]
            assert "openapi: true" in ver["raw_markdown"]
            assert "```python" in ver["raw_markdown"]
            assert "```curl" in ver["raw_markdown"]
            assert "| Col1 | Col2 |" in ver["raw_markdown"]
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_utc_iso_timestamps(self, mock_dl):
        db_path = _make_temp_db()
        try:
            entries = [
                {
                    "title": "T",
                    "url": "https://docs.metronome.com/api-reference/t.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": None,
                    "subcategory": None,
                    "slug": "t",
                    "file_name": "t.md",
                    "source_line_number": 1,
                    "raw_line": "",
                },
            ]
            idx_path = _make_index_file(entries)

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True, raw_markdown="# T",
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation
            asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))

            conn = get_connection(db_path)
            page = conn.execute(
                "SELECT first_seen_at, last_seen_at FROM documentation_pages LIMIT 1"
            ).fetchone()
            assert "+00:00" in page["first_seen_at"]

            ver = conn.execute(
                "SELECT fetched_at FROM documentation_versions LIMIT 1"
            ).fetchone()
            assert "+00:00" in ver["fetched_at"]

            run = conn.execute(
                "SELECT started_at, completed_at FROM documentation_sync_runs LIMIT 1"
            ).fetchone()
            assert "+00:00" in run["started_at"]
            assert "+00:00" in run["completed_at"]
            conn.close()
        finally:
            db_path.unlink()
            idx_path.unlink()

    @patch("src.documentation.synchronizer.download_article")
    def test_db_created_automatically(self, mock_dl):
        db_path = _make_temp_db()
        db_path.unlink()  # delete — should be recreated
        try:
            entries = [
                {
                    "title": "T",
                    "url": "https://docs.metronome.com/api-reference/t.md",
                    "description": "",
                    "document_type": "api_reference",
                    "category": None,
                    "subcategory": None,
                    "slug": "t",
                    "file_name": "t.md",
                    "source_line_number": 1,
                    "raw_line": "",
                },
            ]
            idx_path = _make_index_file(entries)

            async def _fake(client, entry, sem):
                return DownloadResult(
                    url=entry.url, success=True, raw_markdown="# T",
                    http_status=200, final_url=entry.url,
                )
            mock_dl.side_effect = _fake

            from src.documentation.synchronizer import synchronize_documentation
            asyncio.run(synchronize_documentation(idx_path, db_path, concurrency=1))

            assert db_path.exists()

            conn = get_connection(db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {r["name"] for r in tables}
            assert "documentation_pages" in table_names
            conn.close()
        finally:
            if db_path.exists():
                db_path.unlink()
            idx_path.unlink()