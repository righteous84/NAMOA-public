"""Notification read model (GUI/UX Phase 4)."""

from dataclasses import dataclass
from typing import Optional


NOTIFICATION_CATEGORIES = frozenset(
    {
        "information",
        "success",
        "working",
        "attention",
        "error",
        "neutral",
    }
)


@dataclass
class Notification:
    """
    One durable user-facing notification.

    A notification is derived presentation of an authoritative
    moment (a recorded state transition). It is never domain truth:
    it is never read back into a decision, recommendation, execution,
    or provenance authority. Notifications persist until dismissed.
    """

    id: int

    category: str = "information"

    title: str = ""

    message: Optional[str] = None

    media_id: Optional[int] = None

    execution_job_id: Optional[int] = None

    recommendation_id: Optional[int] = None

    scan_id: Optional[int] = None

    created_at: Optional[str] = None

    dismissed_at: Optional[str] = None