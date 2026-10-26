"""
NAMOA library-status read models.

Aggregate read models produced by the application layer for the
GUI (Sprint 6.12). Each model is a plain presentation read over
existing authoritative reads:

- lineage enumeration       -> MediaRepository (via MediaService)
- per-lineage currentness   -> AnalysisValidityService
- opportunity queue         -> OpportunityQueueService (via RecommendationService)
- analysis runs             -> ProvenanceRepository
- technical facts           -> AnalysisRepository (media_analysis)

These models contain no intelligence and no persistence logic.
"""

from dataclasses import dataclass
from typing import Optional

from app.models.analysis_run import AnalysisRun
from app.models.media_analysis_record import MediaAnalysisRecord
from app.models.observation_history import MediaLineage


@dataclass(frozen=True, slots=True)
class ScanMeta:
    """
    Honest scan-state facts available from persisted data.

    Scanning is synchronous in the current architecture; there is no
    running-scan state and no scan history table. The only persisted
    scan fact is the most recent scan timestamp recorded on active
    media lineages.
    """

    last_scanned_at: Optional[str] = None

    active_lineage_count: int = 0

    missing_lineage_count: int = 0


@dataclass(frozen=True, slots=True)
class LineageStatusEntry:
    """
    One media lineage together with its authoritative analysis
    status derived from AnalysisValidityService.
    """

    media: MediaLineage

    # Authoritative fields from the validity read model.
    reason: str = ""

    analysis_required: bool = False

    incomplete_run_states: tuple[str, ...] = ()

    valid_run_id: Optional[int] = None

    opportunity: Optional[str] = None

    opportunity_score: Optional[float] = None

    confidence: Optional[float] = None

    estimated_saving_percent: Optional[float] = None

    risk: Optional[str] = None

    # Technical facts of the current valid run, when one exists.
    technical_facts: Optional[MediaAnalysisRecord] = None

    historical_run_count: int = 0


@dataclass(frozen=True, slots=True)
class LibrarySummary:
    """
    Honest library overview aggregated from authoritative reads.

    Every count is derived by enumerating existing lineage/run reads
    and their authoritative validity - nothing is invented.
    """

    total_active_lineages: int = 0

    total_missing_lineages: int = 0

    lineages_with_valid_analysis: int = 0

    lineages_requiring_analysis: int = 0

    opportunity_count: int = 0

    total_library_bytes: int = 0

    total_estimated_saved_bytes: int = 0

    last_scanned_at: Optional[str] = None


@dataclass(frozen=True, slots=True)
class OpportunityCategorySummary:
    """
    Savings aggregation for one opportunity type from the
    authoritative opportunity queue.
    """

    opportunity: str

    count: int = 0

    total_saved_bytes: int = 0

    total_size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class StorageSummary:
    """
    Storage/savings aggregation over the authoritative queue.

    Values are arithmetic sums of existing read-model fields
    (OptimisationCandidate.estimated_saved_bytes etc.), never
    re-ranked or re-derived intelligence.
    """

    total_library_bytes: int = 0

    opportunity_count: int = 0

    total_estimated_saved_bytes: int = 0

    total_estimated_saving_percent: float = 0.0

    by_opportunity: tuple[OpportunityCategorySummary, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisRunSummary:
    """
    One persisted analysis run joined with its media lineage facts
    for display. Read-only.
    """

    run: AnalysisRun

    media_name: Optional[str] = None

    media_path: Optional[str] = None

    media_status: Optional[str] = None
