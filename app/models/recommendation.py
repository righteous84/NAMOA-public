"""Recommendation persistence read models (Sprint 10 correction)."""

from dataclasses import dataclass, field
from typing import Optional


# Lifecycle states. Only states supported by the existing workflow are
# modelled; execution-side detail remains owned exclusively by the
# execution job (single execution authority).
STATE_PROPOSED = "proposed"
STATE_ACCEPTED = "accepted"
STATE_REJECTED = "rejected"
STATE_QUEUED = "queued"
STATE_EXECUTING = "executing"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"

TERMINAL_STATES = frozenset(
    {STATE_REJECTED, STATE_COMPLETED, STATE_FAILED}
)

ALLOWED_TRANSITIONS = {
    STATE_PROPOSED: {
        STATE_PROPOSED,
        STATE_ACCEPTED,
        STATE_REJECTED,
    },
    STATE_ACCEPTED: {
        STATE_ACCEPTED,
        STATE_QUEUED,
        STATE_REJECTED,
    },
    STATE_REJECTED: {STATE_REJECTED},
    STATE_QUEUED: {STATE_QUEUED, STATE_EXECUTING},
    STATE_EXECUTING: {
        STATE_EXECUTING,
        STATE_COMPLETED,
        STATE_FAILED,
    },
    # completed -> failed covers explicit rollback of a succeeded job;
    # failed -> completed covers recovery that finalises an interrupted
    # replacement as honestly succeeded. Both are execution-authority
    # driven corrections, recorded as events.
    STATE_COMPLETED: {STATE_COMPLETED, STATE_FAILED},
    STATE_FAILED: {STATE_FAILED, STATE_COMPLETED},
}


def assert_transition(current: str, new: str) -> None:

    allowed = ALLOWED_TRANSITIONS.get(current)

    if allowed is None:
        raise ValueError(
            f"unknown recommendation state '{current}'"
        )

    if new not in allowed:
        raise ValueError(
            f"illegal recommendation state transition "
            f"'{current}' -> '{new}'"
        )


@dataclass(slots=True)
class RecommendationRecord:
    """
    Read model of one durable recommendation row.

    The analytical payload is the result AS PRODUCED BY ITS ANALYSIS
    RUN. Priority/presentation fields freeze what the prioritisation
    layer showed when such a snapshot exists (acceptance freezes it).
    """

    id: int

    media_id: int

    analysis_run_id: int

    file_observation_id: Optional[int] = None

    opportunity: str = "unknown"

    opportunity_score: Optional[float] = None

    confidence: Optional[float] = None

    estimated_saving_percent: Optional[float] = None

    estimated_saved_bytes: Optional[int] = None

    risk: Optional[str] = None

    opportunity_level: str = "none"

    summary: Optional[str] = None

    priority_score: Optional[float] = None

    rank_at_presentation: Optional[int] = None

    components: dict = field(default_factory=dict)

    rationale: list = field(default_factory=list)

    contributing_rules: list = field(default_factory=list)

    intelligence_identity: Optional[str] = None

    state: str = STATE_PROPOSED

    execution_job_id: Optional[int] = None

    created_at: Optional[str] = None

    updated_at: Optional[str] = None