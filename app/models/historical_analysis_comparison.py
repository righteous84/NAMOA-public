from dataclasses import dataclass
from typing import Any, Optional

from app.models.analysis_run import AnalysisRun
from app.models.file_observation import FileObservation


@dataclass(frozen=True, slots=True)
class AnalysisDifference:
    """
    One meaningful persisted difference between two analyses.
    """

    category: str

    key: str

    before: Any

    after: Any

    summary: str


@dataclass(frozen=True, slots=True)
class HistoricalAnalysisComparison:
    """
    Read-only comparison of two persisted historical analyses of
    the same media lineage.

    This is a read model. It never recalculates intelligence and
    never mutates either analysis.
    """

    run_a: AnalysisRun

    run_b: AnalysisRun

    media_id: int

    same_observation: bool

    observation_a: Optional[FileObservation] = None

    observation_b: Optional[FileObservation] = None

    differences: tuple[AnalysisDifference, ...] = ()
