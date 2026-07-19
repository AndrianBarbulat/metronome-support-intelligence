"""Tests for the drafting service."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest
from datetime import datetime, timezone

from src.database.repository import DocumentationRepository
from src.drafting.service import generate_grounded_draft, review_generated_draft
from src.drafting.providers.mock import MockDraftingProvider


def _make_temp_db():
    """Create a temporary database with schema initialized."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    repo = DocumentationRepository(db_path)
    repo.initialize_schema()

    # Seed minimal ticket + analysis data for grounding
    now = datetime.now(timezone.utc).isoformat()
    conn = repo._get_conn()
    conn.execute(
        """INSERT INTO support_tickets
           (external_ticket_id, subject, customer_message, status,
            sanitized, redaction_count, created_at, updated_at)
           VALUES (?, ?, ?, 'analyzed', 1, 0, ?, ?)""",
        ("TEST-001", "Contract 409", "Getting 409 on contract creation.", now, now),
    )
    ticket_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Evidence
    import json
    conn.execute(
        """INSERT INTO support_ticket_evidence
           (ticket_id, http_method, endpoint_path, request_body_json,
            response_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            ticket_id, "POST", "/v1/contracts/create",
            json.dumps({"customer_id": "cust-1", "uniqueness_key": "key-123"}),
            409, now,
        ),
    )

    # Analysis
    conn.execute(
        """INSERT INTO support_ticket_analyses
           (ticket_id, analyzer_version, summary, signals_json,
            observations_json, validation_findings_json,
            hypotheses_json, missing_evidence_json,
            investigation_steps_json, created_at)
           VALUES (?, '1.0.0', 'Test analysis', '{}',
            '[]', '[]', '[]', '[]', '[]', ?)""",
        (ticket_id, now),
    )
    conn.commit()
    repo.close()
    return db_path, ticket_id


class TestDraftingService:
    """Integration tests for the drafting service."""

    def test_generate_with_mock_provider(self):
        db_path, ticket_id = _make_temp_db()
        try:
            provider = MockDraftingProvider(mode="valid")
            draft = generate_grounded_draft(
                draft_type="customer_update",
                database_path=db_path,
                ticket_id=ticket_id,
                provider=provider,
            )
            assert draft.id is not None
            assert draft.draft_type == "customer_update"
            assert len(draft.body) > 0
            assert draft.provider == "mock"
            assert draft.status == "needs_review"
        finally:
            db_path.unlink(missing_ok=True)

    def test_reject_unsupported_draft_type(self):
        db_path, ticket_id = _make_temp_db()
        try:
            provider = MockDraftingProvider(mode="valid")
            with pytest.raises(ValueError, match="Unsupported draft type"):
                generate_grounded_draft(
                    draft_type="nonexistent_type",
                    database_path=db_path,
                    ticket_id=ticket_id,
                    provider=provider,
                )
        finally:
            db_path.unlink(missing_ok=True)

    def test_customer_resolution_without_resolution_rejected(self):
        db_path, ticket_id = _make_temp_db()
        try:
            import os
            os.environ["DRAFTING_PROVIDER"] = "mock"
            provider = MockDraftingProvider(mode="valid")
            with pytest.raises(ValueError, match="no confirmed resolution"):
                generate_grounded_draft(
                    draft_type="customer_resolution",
                    database_path=db_path,
                    ticket_id=ticket_id,
                    provider=provider,
                )
        finally:
            db_path.unlink(missing_ok=True)

    def test_provider_failure_draft_still_persisted(self):
        db_path, ticket_id = _make_temp_db()
        try:
            provider = MockDraftingProvider(mode="provider_failure")
            draft = generate_grounded_draft(
                draft_type="customer_update",
                database_path=db_path,
                ticket_id=ticket_id,
                provider=provider,
            )
            assert draft.status == "validation_failed"
            assert "Provider error" in draft.body
        finally:
            db_path.unlink(missing_ok=True)

    def test_draft_persisted_to_db(self):
        db_path, ticket_id = _make_temp_db()
        try:
            provider = MockDraftingProvider(mode="valid")
            draft = generate_grounded_draft(
                draft_type="customer_update",
                database_path=db_path,
                ticket_id=ticket_id,
                provider=provider,
            )
            assert draft.id is not None

            # Verify in DB
            repo = DocumentationRepository(db_path)
            repo.initialize_schema()
            row = repo.get_generated_draft(draft.id)
            assert row is not None
            assert row["draft_type"] == "customer_update"
            assert row["status"] == "needs_review"
            repo.close()
        finally:
            db_path.unlink(missing_ok=True)


class TestReviewWorkflow:
    """Tests for human review workflow transitions."""

    def _create_and_approve(self, db_path, ticket_id):
        provider = MockDraftingProvider(mode="valid")
        draft = generate_grounded_draft(
            draft_type="customer_update",
            database_path=db_path,
            ticket_id=ticket_id,
            provider=provider,
        )
        return draft

    def test_approve_transition(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            result = review_generated_draft(
                draft_id=draft.id,
                decision="approve",
                reviewer="Tester",
                notes="Looks good.",
                database_path=db_path,
            )
            assert result.status == "approved"
        finally:
            db_path.unlink(missing_ok=True)

    def test_reject_transition(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            result = review_generated_draft(
                draft_id=draft.id,
                decision="reject",
                reviewer="Tester",
                notes="Needs more work.",
                database_path=db_path,
            )
            assert result.status == "rejected"
        finally:
            db_path.unlink(missing_ok=True)

    def test_mark_used_transition(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            # First approve
            review_generated_draft(
                draft_id=draft.id,
                decision="approve",
                reviewer="Tester",
                notes="Approved.",
                database_path=db_path,
            )
            # Then mark used
            result = review_generated_draft(
                draft_id=draft.id,
                decision="mark_used",
                reviewer="Tester",
                notes="Sent to customer.",
                database_path=db_path,
            )
            assert result.status == "used"
        finally:
            db_path.unlink(missing_ok=True)

    def test_validation_failed_cannot_be_approved(self):
        db_path, ticket_id = _make_temp_db()
        try:
            provider = MockDraftingProvider(mode="unknown_fact")
            draft = generate_grounded_draft(
                draft_type="customer_update",
                database_path=db_path,
                ticket_id=ticket_id,
                provider=provider,
            )
            assert draft.status == "validation_failed"

            with pytest.raises(ValueError, match="Cannot approve"):
                review_generated_draft(
                    draft_id=draft.id,
                    decision="approve",
                    reviewer="Tester",
                    notes="Force approve.",
                    database_path=db_path,
                )
        finally:
            db_path.unlink(missing_ok=True)

    def test_rejected_cannot_be_marked_used(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            review_generated_draft(
                draft_id=draft.id,
                decision="reject",
                reviewer="Tester",
                notes="Rejected.",
                database_path=db_path,
            )
            with pytest.raises(ValueError, match="Cannot mark draft"):
                review_generated_draft(
                    draft_id=draft.id,
                    decision="mark_used",
                    reviewer="Tester",
                    notes="Try to use rejected.",
                    database_path=db_path,
                )
        finally:
            db_path.unlink(missing_ok=True)

    def test_generated_cannot_be_marked_used_without_approval(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            assert draft.status == "needs_review"

            with pytest.raises(ValueError, match="Cannot mark draft"):
                review_generated_draft(
                    draft_id=draft.id,
                    decision="mark_used",
                    reviewer="Tester",
                    notes="Skip approval.",
                    database_path=db_path,
                )
        finally:
            db_path.unlink(missing_ok=True)

    def test_review_metadata_persisted(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            review_generated_draft(
                draft_id=draft.id,
                decision="approve",
                reviewer="JaneDoe",
                notes="All checks passed.",
                database_path=db_path,
            )
            repo = DocumentationRepository(db_path)
            repo.initialize_schema()
            row = repo.get_generated_draft(draft.id)
            assert row["reviewed_by"] == "JaneDoe"
            assert row["review_notes"] == "All checks passed."
            assert row["reviewed_at"] is not None
            repo.close()
        finally:
            db_path.unlink(missing_ok=True)

    def test_unsupported_decision_rejected(self):
        db_path, ticket_id = _make_temp_db()
        try:
            draft = self._create_and_approve(db_path, ticket_id)
            with pytest.raises(ValueError, match="Unsupported review decision"):
                review_generated_draft(
                    draft_id=draft.id,
                    decision="delete",
                    reviewer="Tester",
                    notes="Invalid decision.",
                    database_path=db_path,
                )
        finally:
            db_path.unlink(missing_ok=True)