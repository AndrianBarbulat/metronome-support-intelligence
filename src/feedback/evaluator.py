"""Small helpers for feedback evaluation."""

from __future__ import annotations

from .review_service import TRANSITIONS


def transition_is_valid(current_status: str, decision: str) -> bool:
    return decision in TRANSITIONS.get(current_status, {})
