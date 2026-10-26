"""
NAMOA Sprint 7 library-intelligence read models.

Authoritative library-level read models produced by
LibraryIntelligenceService (app/services/library_intelligence_service.py).

These models answer:

    "What is the current state of the library?"

at the library level. They are DERIVED views over existing persisted
facts and existing authorities:

- lineage enumeration       -> MediaRepository (active/missing)
- per-lineage currentness   -> AnalysisValidityService (sole authority)
- current opportunity queue -> OpportunityQueueService (sole boundary)

Nothing here is persisted. Library-level currentness is never stored;
it is always re-derived from AnalysisValidityService at read time.

Model semantics
---------------

analysed_lineages        active lineages with a valid completed analysis
                         for the current filesystem state
unanalysed_lineages      active lineages requiring (re-)analysis
stale_analyses           active lineages requiring analysis that have at
                         least one historical completed analysis: a prior
                         conclusion exists but is no longer current
changed_media            active lineages requiring analysis whose current
                         fingerprint matches no observation: the physical
                         file changed beyond the last recorded observation
changed_since_analysis   active lineages whose current fingerprint differs
                         from the fingerprint of every completed analysis.
                         In the current fingerprint-based validity model
                         this is identical to stale_analyses: a stale
                         analysis exists exactly when the current state
                         differs from an analysed state, meaning the file
                         changed since that analysis. Both fields are kept
                         because the roadmap tracks the analytical and the
                         physical concern separately.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class LibraryLineageStatus:
    """
    One media lineage classified by the library-intelligence authority
    from the validity authority's read model. Used as the internal
    building block for aggregate statistics and exposed for
    transparency. All classification fields are derived from
    AnalysisValidityService fields verbatim; no validity rule is
    reimplemented.
    """

    media_id: int

    media_status: str = ""

    validity_reason: str = ""

    analysis_required: bool = False

    is_analysed: bool = False

    is_stale: bool = False

    is_changed_media: bool = False

    is_changed_since_analysis: bool = False

    valid_run_id: Optional[int] = None

    historical_run_count: int = 0

    file_size_bytes: Optional[int] = None

    file_name: Optional[str] = None


@dataclass(frozen=True, slots=True)
class LibraryStatistics:
    """
    Aggregate library statistics derived from lineage enumeration and
    the validity authority. Every count is derived, never invented.
    """

    total_lineages: int = 0

    active_lineages: int = 0

    missing_lineages: int = 0

    analysed_lineages: int = 0

    unanalysed_lineages: int = 0

    stale_analyses: int = 0

    changed_media: int = 0

    changed_since_analysis: int = 0

    analysis_coverage_percent: float = 0.0

    opportunity_count: int = 0

    total_library_bytes: int = 0

    total_estimated_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class StorageConsumption:
    """
    Storage-consumption view over the library. Bytes are sums of
    authoritative lineage and queue fields; percentages are derived
    arithmetic over those sums.
    """

    total_library_bytes: int = 0

    active_lineage_count: int = 0

    missing_lineage_count: int = 0

    analysed_bytes: int = 0

    unanalysed_bytes: int = 0

    missing_bytes: int = 0

    opportunity_bytes: int = 0

    opportunity_saved_bytes: int = 0

    opportunity_saved_percent: float = 0.0

    library_savings_percent: float = 0.0


@dataclass(frozen=True, slots=True)
class SavingsBucket:
    """
    One savings bucket (estimated_saving_percent range) over the
    current-valid opportunity queue.
    """

    label: str

    lower_percent: float

    upper_percent: Optional[float]

    count: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class SavingsDistribution:
    """
    Distribution of estimated savings across the current-valid
    opportunity queue. Buckets are fixed, labelled, and deterministic.
    """

    buckets: tuple[SavingsBucket, ...] = ()

    total_opportunities: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ConfidenceBucket:
    """
    One confidence bucket (0..1 range) over the current-valid
    opportunity queue.
    """

    label: str

    lower: float

    upper: float

    count: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ConfidenceDistribution:
    """
    Distribution of analytical confidence across the current-valid
    opportunity queue. Confidence values are the authoritative
    opportunity-assessment confidences; nothing is re-derived.
    """

    buckets: tuple[ConfidenceBucket, ...] = ()

    total_opportunities: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class LibraryHealth:
    """
    Library health indicators derived from authoritative aggregate
    facts. Thresholds are documented policy decisions (see the
    LibraryIntelligenceService docstring) and are deliberately simple,
    deterministic and explainable.

    An empty library is defined as healthy (score 1.0): there is no
    stale or unanalysed media to be unhealthy about.
    """

    health_score: float = 0.0

    status: str = "unknown"

    analysis_coverage: float = 0.0

    coverage_status: str = "unknown"

    stale_ratio: float = 0.0

    stale_status: str = "unknown"

    opportunity_ratio: float = 0.0

    opportunity_status: str = "unknown"

    indicators: tuple[str, ...] = ()