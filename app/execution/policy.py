"""
Execution policy validation (Sprint 9).

Every planned execution must pass through validate(); the engine
refuses to run without an explicit allow decision. Policy owns:

- the closed set of permitted operations
- tool availability
- source sanity (exists, regular file, not a symlink)
- in-place replacement rule: destination is always the source path;
  output is staged as a same-directory temporary file so the final
  swap is an atomic rename on one filesystem
- writability of the working directory

Policy deliberately contains no media intelligence and no currentness
logic; it decides whether an approved operation is PERMITTED.
"""

import os
import shutil

from dataclasses import dataclass, field
from typing import Optional

from app.execution.operations import (
    EXECUTABLE_OPERATIONS,
    OPERATION_REMUX_MP4,
)


# The permitted operation set is owned by the closed, versioned
# operation registry (app/execution/operations.py). Policy validates
# against the registry's executable set; a non-executable operation is
# never permitted.
ALLOWED_OPERATIONS = frozenset(EXECUTABLE_OPERATIONS)

FFMPEG_BINARY = "ffmpeg"

EXECUTION_TIMEOUT_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """
    Explicit, inspectable result of policy validation. Persisted on
    the execution record as JSON regardless of outcome.
    """

    allowed: bool

    reasons: tuple = ()

    operation: str = ""

    ffmpeg_path: Optional[str] = None

    checked: tuple = field(default_factory=tuple)

    def to_json(self) -> dict:

        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "operation": self.operation,
            "ffmpeg_path": self.ffmpeg_path,
            "checked": list(self.checked),
        }


def validate(
    *,
    operation,
    source_path,
    destination_path,
) -> PolicyDecision:

    reasons = []

    checked = ["operation"]

    if operation not in ALLOWED_OPERATIONS:

        reasons.append(
            f"operation '{operation}' is not permitted "
            f"(allowed: {sorted(ALLOWED_OPERATIONS)})"
        )

    checked += ["tool_available", "source_exists",
                "source_regular_file", "source_not_symlink",
                "in_place_replacement", "working_dir_writable"]

    ffmpeg_path = shutil.which(FFMPEG_BINARY)

    if ffmpeg_path is None:

        reasons.append("ffmpeg executable not available")

    if not os.path.exists(source_path):

        reasons.append("source does not exist")

    else:

        if not os.path.isfile(source_path):

            reasons.append("source is not a regular file")

        if os.path.islink(source_path):

            reasons.append(
                "source is a symlink; refusing"
            )

    if os.path.abspath(destination_path) != os.path.abspath(
        source_path
    ):

        reasons.append(
            "only in-place replacement of the approved source "
            "is permitted"
        )

    working_dir = os.path.dirname(
        os.path.abspath(source_path)
    ) or "."

    if not os.access(working_dir, os.W_OK):

        reasons.append(
            f"working directory not writable: {working_dir}"
        )

    return PolicyDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        operation=operation,
        ffmpeg_path=ffmpeg_path,
        checked=tuple(checked),
    )
