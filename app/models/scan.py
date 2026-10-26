from dataclasses import dataclass
from typing import Optional


@dataclass
class Scan:
    """
    Durable identity record for one bounded scan invocation.

    A Scan groups the files an invocation of the scanning workflow
    encountered against a target scope. It carries only scan-level
    facts (scope, lifecycle, terminal status, useful counts). It does
    not own or duplicate intelligence semantics: the per-file detail
    lives in ScanItem references to the existing authoritative
    observation/analysis records.

    This model is a transport object only and contains no persistence
    or business logic.
    """

    id: Optional[int] = None

    target_scope: Optional[str] = None

    status: str = "running"

    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # When the per-file analysis phase began (immediately after
    # filesystem discovery completed). NULL while discovery is still
    # running. Used for the honest approximate analysis ETA.
    analysis_started_at: Optional[str] = None

    files_discovered: int = 0
    files_analysed: int = 0
    files_reused: int = 0
    files_failed: int = 0
    files_skipped: int = 0

    error_message: Optional[str] = None

    created_at: Optional[str] = None


@dataclass
class ScanItem:
    """
    One file encountered by a Scan, and how the scan treated it.

    References (never duplicates) the media lineage, the exact file
    observation, and the analysis run involved. The outcome makes the
    distinction explicit between:

        analysed   new analysis performed during this scan
        reused     existing applicable analysis reused (no fake run)
        failed     processing failed during this scan
        skipped    discovered but not analysed

    This model is a transport object only and contains no persistence
    or business logic.
    """

    id: Optional[int] = None

    scan_id: Optional[int] = None

    media_id: Optional[int] = None
    file_observation_id: Optional[int] = None
    analysis_run_id: Optional[int] = None

    outcome: Optional[str] = None

    created_at: Optional[str] = None