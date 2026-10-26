"""Organisation execution lifecycle read models (Sprint 14).

The organisation execution is a SEPARATE execution domain from
optimisation execution. It consumes an already-approved
organisation proposal and performs a deterministic, verified
move/rename. This module owns only the execution lifecycle state
machine and the read model; the safety, concurrency and
reconciliation authority lives in OrganisationExecutionService.
"""

from dataclasses import dataclass, field
from typing import Optional


# Lifecycle states (Sprint 14). These map to the Architect-approved
# lifecycle exactly:
#
#   PROPOSED -> APPROVED -> PRECONDITION_VERIFIED -> EXECUTING
#     -> VERIFYING -> OBSERVATION_PERSISTENCE
#     -> PROVENANCE_PERSISTENCE -> SUCCEEDED
#
# Failure / interruption states preserve uncertainty:
#
#   FAILED, INTERRUPTED, RECOVERY_REQUIRED
STATE_PROPOSED = "proposed"
STATE_APPROVED = "approved"
STATE_PRECONDITION_VERIFIED = "precondition_verified"
STATE_EXECUTING = "executing"
STATE_VERIFYING = "verifying"
STATE_OBSERVATION_PERSISTENCE = "observation_persistence"
STATE_PROVENANCE_PERSISTENCE = "provenance_persistence"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_INTERRUPTED = "interrupted"
STATE_RECOVERY_REQUIRED = "recovery_required"

TERMINAL_STATES = frozenset(
    {STATE_SUCCEEDED, STATE_FAILED}
)

ACTIVE_STATES = frozenset(
    {
        STATE_PROPOSED,
        STATE_APPROVED,
        STATE_PRECONDITION_VERIFIED,
        STATE_EXECUTING,
        STATE_VERIFYING,
        STATE_OBSERVATION_PERSISTENCE,
        STATE_PROVENANCE_PERSISTENCE,
        STATE_INTERRUPTED,
        STATE_RECOVERY_REQUIRED,
    }
)

# SUCCEEDED means the filesystem operation completed, was verified,
# a new filesystem observation was persisted for the SAME media
# identity, execution-authorised continuity was persisted, and the
# execution record + provenance were persisted. A filesystem API
# returning successfully is never sufficient for SUCCEEDED by itself.

ALLOWED_TRANSITIONS = {
    STATE_PROPOSED: {STATE_PROPOSED, STATE_APPROVED, STATE_FAILED},
    STATE_APPROVED: {
        STATE_APPROVED,
        STATE_PRECONDITION_VERIFIED,
        STATE_FAILED,
    },
    STATE_PRECONDITION_VERIFIED: {
        STATE_PRECONDITION_VERIFIED,
        STATE_EXECUTING,
        STATE_FAILED,
        STATE_RECOVERY_REQUIRED,
    },
    STATE_EXECUTING: {
        STATE_EXECUTING,
        STATE_VERIFYING,
        STATE_FAILED,
        STATE_INTERRUPTED,
        STATE_RECOVERY_REQUIRED,
    },
    STATE_VERIFYING: {
        STATE_VERIFYING,
        STATE_OBSERVATION_PERSISTENCE,
        STATE_FAILED,
        STATE_INTERRUPTED,
        STATE_RECOVERY_REQUIRED,
    },
    STATE_OBSERVATION_PERSISTENCE: {
        STATE_OBSERVATION_PERSISTENCE,
        STATE_PROVENANCE_PERSISTENCE,
        STATE_FAILED,
        STATE_RECOVERY_REQUIRED,
    },
    STATE_PROVENANCE_PERSISTENCE: {
        STATE_PROVENANCE_PERSISTENCE,
        STATE_SUCCEEDED,
        STATE_FAILED,
        STATE_RECOVERY_REQUIRED,
    },
    STATE_INTERRUPTED: {
        STATE_INTERRUPTED,
        STATE_RECOVERY_REQUIRED,
        STATE_FAILED,
    },
    STATE_RECOVERY_REQUIRED: {
        STATE_RECOVERY_REQUIRED,
        STATE_SUCCEEDED,
        STATE_FAILED,
        STATE_APPROVED,
        STATE_VERIFYING,
    },
    STATE_SUCCEEDED: {STATE_SUCCEEDED},
    STATE_FAILED: {STATE_FAILED},
}


def assert_transition(current: str, new: str) -> None:

    allowed = ALLOWED_TRANSITIONS.get(current)

    if allowed is None:
        raise ValueError(
            f"unknown organisation execution state '{current}'"
        )

    if new not in allowed:
        raise ValueError(
            f"illegal organisation execution state transition "
            f"'{current}' -> '{new}'"
        )


@dataclass(frozen=True, slots=True)
class OrganisationExecutionRecord:
    """
    Read model of one durable organisation execution lifecycle record.

    It is never an authority on its own: the proposal approval and
    the filesystem safety checks are interpreted by
    OrganisationExecutionService against persisted state and
    deterministic filesystem reality.
    """

    id: int

    proposal_id: int

    decision_run_id: int

    media_id: int

    intent: str = ""

    source_path: str = ""

    source_observation_id: Optional[int] = None

    source_size_bytes: Optional[int] = None

    source_mtime_ns: Optional[int] = None

    destination_path: str = ""

    state: str = STATE_PROPOSED

    error: Optional[str] = None

    result_observation_id: Optional[int] = None

    continuity_id: Optional[int] = None

    actor: str = "human"

    created_at: Optional[str] = None

    updated_at: Optional[str] = None
