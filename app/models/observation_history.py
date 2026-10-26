from dataclasses import dataclass
from typing import Optional

from app.models.file_observation import FileObservation
from app.models.analysis_run import AnalysisRun


@dataclass(frozen=True, slots=True)
class MediaLineage:
    """
    Stable NAMOA media lineage identity.

    Distinguishes the lineage (media_items) from the immutable
    filesystem observations (file_observations) that belong to it.

    Carries the fingerprint currently stored on the active media
    lineage, which represents the current filesystem state.
    """

    id: int

    file_path: str

    file_name: str

    status: Optional[str] = None

    file_size_bytes: Optional[int] = None

    file_mtime_ns: Optional[int] = None


@dataclass(frozen=True, slots=True)
class ObservationHistoryEntry:
    """
    One historical filesystem observation and the analysis runs
    executed against that specific observed file state.
    """

    observation: FileObservation

    analysis_runs: tuple[AnalysisRun, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservationHistory:
    """
    Complete immutable observation history for one media lineage.

    Preserves the distinction:

        media_items        = stable lineage identity
        file_observations  = immutable historical observations
        analysis_runs      = intelligence executions per observation
    """

    media: MediaLineage

    observations: tuple[ObservationHistoryEntry, ...] = ()
