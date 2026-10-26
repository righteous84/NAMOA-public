"""Execution-layer read models (Sprint 9)."""

from dataclasses import dataclass, field
from typing import Optional


TERMINAL_STATES = frozenset(
    {
        "succeeded",
        "rolled_back",
        "failed_execution",
        "failed_verification",
        "failed_replacement",
        "recovered",
        "original_deleted",
    }
)

ACTIVE_STATES = frozenset(
    {
        "approved",
        "planned",
        "running",
        "verifying",
        "replacing",
        "deleting_original",
    }
)

# Explicit lifecycle. Any state may be rewritten to ITSELF (field
# updates without progression). Anything not listed here is illegal
# and must be rejected by the persistence layer.
#
#   approved  -> planned            (policy-approved plan frozen)
#   planned   -> running            (engine picked the job up)
#   running   -> verifying | failed_execution | interrupted
#   verifying -> replacing | failed_verification | interrupted
#   replacing -> succeeded | failed_replacement | interrupted
#   interrupted -> recovered        (filesystem reality resolved)
#   succeeded -> rolled_back        (destructive revert of the swap)
#   succeeded -> deleting_original (explicit delete-original action)
#   deleting_original -> original_deleted | deletion_failed
#   deletion_failed -> deleting_original (explicit retry after recheck)
#   original_deleted is terminal; rollback is never offered after it.

ALLOWED_TRANSITIONS = {
    "approved": {"approved", "planned"},
    "planned": {"planned", "running", "interrupted"},
    "running": {
        "running",
        "verifying",
        "failed_execution",
        "interrupted",
        "recovered",
    },
    "verifying": {
        "verifying",
        "replacing",
        "failed_verification",
        "failed_execution",
        "interrupted",
        "recovered",
    },
    "replacing": {
        "replacing",
        "succeeded",
        "failed_replacement",
        "interrupted",
        "recovered",
    },
    "interrupted": {"interrupted", "recovered"},
    "succeeded": {
        "succeeded",
        "rolled_back",
        "deleting_original",
    },
    "deleting_original": {
        "deleting_original",
        "original_deleted",
        "deletion_failed",
    },
    "deletion_failed": {
        "deletion_failed",
        "deleting_original",
    },
    "rolled_back": {"rolled_back"},
    "failed_execution": {"failed_execution"},
    "failed_verification": {"failed_verification"},
    "failed_replacement": {"failed_replacement"},
    "recovered": {"recovered"},
    "original_deleted": {"original_deleted"},
}


def assert_transition(current, new):

    """
    Raise ValueError unless new is reachable from current (including
    remaining in the same state).
    """

    allowed = ALLOWED_TRANSITIONS.get(current)

    if allowed is None:

        raise ValueError(
            f"unknown execution state '{current}'"
        )

    if new not in allowed:

        raise ValueError(
            f"illegal execution state transition "
            f"'{current}' -> '{new}'"
        )


@dataclass(frozen=True, slots=True)
class ExecutionJob:
    """
    Read model of one execution lifecycle record.

    This is the application-facing view over a media_executions row.
    It is never an authority: approval/policy/plan facts live in the
    database and are interpreted by ExecutionService.
    """

    id: int

    media_id: int

    opportunity: Optional[str] = None

    analysis_run_id: Optional[int] = None

    source_path: str = ""

    source_size_bytes: Optional[int] = None

    source_mtime_ns: Optional[int] = None

    source_inode: Optional[int] = None

    source_sha256: Optional[str] = None

    approved_by: str = "human"

    state: str = "approved"

    plan: dict = field(default_factory=dict)

    policy_decision: dict = field(default_factory=dict)

    backup_path: Optional[str] = None

    temp_output_path: Optional[str] = None

    output_sha256: Optional[str] = None

    result_observation_id: Optional[int] = None

    # Durable link to the accepted recommendation record (migration
    # 024). The job remains the single execution authority; this is
    # the navigable relationship, not a second state owner.
    recommendation_id: Optional[int] = None

    # The exact file observation approved for execution (migration
    # 033). Referenced, never manufactured: it is the observation that
    # produced the current-valid analysis.
    source_observation_id: Optional[int] = None

    # Explicit user choice to delete the preserved original after
    # successful verified replacement (migration 033). Default false;
    # deletion is a separate file-lifecycle action, never an implicit
    # consequence of optimisation.
    delete_original_requested: bool = False

    deletion_state: Optional[str] = None

    original_deleted_at: Optional[str] = None

    # Immutable approved transformation (migration 032), distinct from
    # the recommendation and from the plan.
    requested_transformation: dict = field(default_factory=dict)

    # Predicted savings snapshot (migration 032); never the old
    # score*50 shortcut.
    predicted: dict = field(default_factory=dict)

    # Measured savings snapshot (migration 032), derived from the
    # actual source and result observations after verified success.
    measured: dict = field(default_factory=dict)

    # Structured verification outcome (migration 032): expectations
    # checked and the resulting facts.
    verification: dict = field(default_factory=dict)

    error: Optional[str] = None


def build_plan(
    *,
    media_id,
    operation,
    source_path,
    source_size_bytes,
    source_mtime_ns,
    argv,
    expected,
    planning=None,
    source_inode=None,
    operation_version=None,
):
    """
    Deterministic execution-plan snapshot frozen between approval and
    execution. Stored as JSON on the job row.

    `planning` carries the planning/cost semantics (for example the
    encoding-speed preference resolution from EncodingSpeedPolicy) as
    a versioned, attributable section. It is optional so pre-planning
    callers and historical plans remain valid.

    `source_inode` strengthens the source fingerprint used by the
    plan/record integrity check. `operation_version` records the
    operation-definition semantic version that produced the plan.
    """

    plan = {
        "media_id": media_id,
        "operation": operation,
        "source_path": source_path,
        "source_fingerprint": {
            "size_bytes": source_size_bytes,
            "mtime_ns": source_mtime_ns,
            "inode": source_inode,
        },
        "argv": list(argv),
        "verification": dict(expected),
    }

    if planning is not None:
        plan["planning"] = dict(planning)

    if operation_version is not None:
        plan["operation_version"] = str(operation_version)

    return plan


def plan_from_json(payload) -> dict:

    if not isinstance(payload, dict):

        raise ValueError("execution plan is not available")

    required = (
        "media_id",
        "operation",
        "source_path",
        "source_fingerprint",
        "argv",
        "verification",
    )

    for key in required:

        if key not in payload:

            raise ValueError(
                f"execution plan missing '{key}'"
            )

    return payload
