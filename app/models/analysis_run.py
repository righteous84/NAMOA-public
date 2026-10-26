from dataclasses import dataclass
from typing import Optional


@dataclass
class AnalysisRun:
    """
    Provenance record representing a single execution of the
    NAMOA intelligence pipeline.

    Each AnalysisRun captures:

        - the stable media lineage identity
        - the exact filesystem observation analysed
        - the configuration snapshot used
        - execution lifecycle
        - completion state
        - any failure information

    This model is a transport object only and contains no
    persistence or business logic.
    """

    id: Optional[int] = None

    media_id: Optional[int] = None
    file_observation_id: Optional[int] = None
    configuration_snapshot_id: Optional[int] = None

    # Deterministic digest of the canonical intelligence identity that
    # produced this run. NULL only for runs recorded before the
    # correction sprint (immutable development-era history; never
    # backfilled).
    intelligence_identity: Optional[str] = None

    status: str = "pending"

    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    error_message: Optional[str] = None

    created_at: Optional[str] = None