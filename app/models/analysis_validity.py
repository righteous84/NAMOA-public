from dataclasses import dataclass
from typing import Optional

from app.models.analysis_run import AnalysisRun
from app.models.file_observation import FileObservation
from app.models.opportunity_assessment import OpportunityAssessment


@dataclass(frozen=True, slots=True)
class AnalysisValidity:
    """
    Derived read model describing whether a media lineage currently
    has a valid completed analysis for its current filesystem state.

    This model is NEVER persisted.

    Currentness is derived, not stored. The validity key is the
    filesystem fingerprint:

        size_bytes + file_mtime_ns

    which is the same fingerprint used by
    MediaRepository.sync_media() for change detection.

    "Valid analysis" means: a completed AnalysisRun whose observation
    fingerprint matches the current filesystem observation's
    fingerprint. It does NOT require an opportunity to exist.

    Currentness therefore means:

        current filesystem state == fingerprint of a completed analysis

    not:

        latest observation ID == analysis observation ID
    """

    media_id: int

    # Current lineage state
    media_status: Optional[str] = None

    # Current filesystem observation (highest-id observation whose
    # fingerprint matches the fingerprint stored on the active
    # media lineage). None when no observation matches.
    current_observation: Optional[FileObservation] = None

    # Current filesystem fingerprint (from the active media lineage).
    current_size_bytes: Optional[int] = None
    current_file_mtime_ns: Optional[int] = None

    # Deterministically selected valid/current completed run, if any.
    valid_analysis_run: Optional[AnalysisRun] = None

    # Current opportunity assessment persisted for the valid run,
    # if one exists. Absence of an opportunity does NOT invalidate
    # a completed analysis.
    current_opportunity: Optional[OpportunityAssessment] = None

    # Whether NAMOA currently requires a (re-)analysis for this
    # lineage's current filesystem state.
    analysis_required: bool = False

    # Machine-readable reason for the current state. One of:
    #   media_missing
    #   no_current_observation
    #   no_completed_analysis
    #   analysis_valid
    #   filesystem_unavailable
    reason: str = ""

    # Statuses of non-completed runs linked to current-fingerprint
    # observations (e.g. abandoned, failed, pending, running).
    # Helps distinguish why no completed analysis is current.
    incomplete_run_states: tuple[str, ...] = ()

    # Completed runs linked to observations whose fingerprint does
    # NOT match the current fingerprint. Historical only - never
    # presented as current intelligence.
    historical_completed_runs: tuple[AnalysisRun, ...] = ()
