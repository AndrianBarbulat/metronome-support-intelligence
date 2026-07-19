"""Human review workflow for feedback items."""

from __future__ import annotations

from pathlib import Path

from src.database.repository import DocumentationRepository

from .models import FEEDBACK_DECISIONS, FEEDBACK_STATUSES, FeedbackItem


TRANSITIONS = {
    "draft": {"request_changes": "needs_review", "reject": "rejected"},
    "needs_review": {"approve": "approved", "reject": "rejected", "request_changes": "draft"},
    "approved": {"mark_planned": "planned", "reject": "rejected"},
    "planned": {"mark_implemented": "implemented"},
    "implemented": {"mark_verified": "verified"},
    "verified": {"close": "closed"},
    "closed": {},
    "rejected": {"request_changes": "needs_review"},
}


class FeedbackReviewError(Exception):
    """Raised when a feedback item review transition is invalid."""


def review_feedback_item(
    feedback_id: int,
    decision: str,
    reviewer: str,
    notes: str | None,
    database_path: Path,
) -> FeedbackItem:
    if decision not in FEEDBACK_DECISIONS:
        raise FeedbackReviewError(f"Unsupported decision: {decision}")
    if not reviewer.strip():
        raise FeedbackReviewError("reviewer is required")

    repo = DocumentationRepository(database_path)
    try:
        repo.initialize_schema()
        row = repo.get_feedback_item(feedback_id)
        if row is None:
            raise FeedbackReviewError(f"Feedback item not found: {feedback_id}")
        current = row["status"]
        new_status = TRANSITIONS.get(current, {}).get(decision)
        if new_status is None:
            raise FeedbackReviewError(f"Invalid transition: {current} via {decision}")
        if new_status not in FEEDBACK_STATUSES:
            raise FeedbackReviewError(f"Unsupported status: {new_status}")
        updated = repo.update_feedback_item_status(feedback_id, new_status, reviewer, notes)
        return _row_to_feedback_item(updated)
    finally:
        repo.close()


def _row_to_feedback_item(row) -> FeedbackItem:
    import json

    return FeedbackItem(
        id=row["id"],
        resolution_id=row["resolution_id"],
        feedback_type=row["feedback_type"],
        gap_code=row["gap_code"],
        title=row["title"],
        summary=row["summary"],
        evidence=json.loads(row["evidence_json"]),
        affected_sources=json.loads(row["affected_sources_json"]),
        proposed_change=json.loads(row["proposed_change_json"]),
        priority=row["priority"],
        status=row["status"],
        owner=row["owner"],
        reviewed_by=row["reviewed_by"],
        review_notes=row["review_notes"],
    )
