import pytest

from src.feedback.evaluator import transition_is_valid
from src.feedback.review_service import FeedbackReviewError, review_feedback_item
from src.support.resolution_service import confirm_ticket_resolution

from tests.phase5_helpers import make_resolution, persisted_analysis


def _feedback_id(tmp_path):
    db, ticket_id, analysis_id = persisted_analysis(tmp_path)
    confirmed = confirm_ticket_resolution(
        make_resolution(ticket_id=ticket_id, analysis_id=analysis_id),
        db,
    )
    return db, confirmed.feedback_items[0].id


def test_valid_transition_helper():
    assert transition_is_valid("needs_review", "approve")
    assert not transition_is_valid("approved", "mark_implemented")


def test_valid_approval_transition(tmp_path):
    db, feedback_id = _feedback_id(tmp_path)

    item = review_feedback_item(feedback_id, "approve", "Andrian", None, db)

    assert item.status == "approved"
    assert item.reviewed_by == "Andrian"


def test_invalid_transition_rejected(tmp_path):
    db, feedback_id = _feedback_id(tmp_path)

    with pytest.raises(FeedbackReviewError):
        review_feedback_item(feedback_id, "mark_implemented", "Andrian", None, db)


def test_implemented_item_can_be_verified(tmp_path):
    db, feedback_id = _feedback_id(tmp_path)

    review_feedback_item(feedback_id, "approve", "Andrian", None, db)
    review_feedback_item(feedback_id, "mark_planned", "Andrian", None, db)
    review_feedback_item(feedback_id, "mark_implemented", "Andrian", None, db)
    item = review_feedback_item(feedback_id, "mark_verified", "Andrian", "Verified in docs.", db)

    assert item.status == "verified"
    assert item.review_notes == "Verified in docs."


def test_rejected_item_can_be_reopened_explicitly(tmp_path):
    db, feedback_id = _feedback_id(tmp_path)

    review_feedback_item(feedback_id, "reject", "Andrian", None, db)
    item = review_feedback_item(feedback_id, "request_changes", "Andrian", "Revise proposal.", db)

    assert item.status == "needs_review"
