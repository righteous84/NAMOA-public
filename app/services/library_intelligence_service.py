"""
NAMOA Sprint 7 library-intelligence authority.

Establishes the authoritative library-level read models that answer:

    "What is the current state of the library?"

This service is the first authoritative library-intelligence
implementation on top of the validated application architecture. It
builds exclusively on existing authorities and NEVER reimplements them:

    lineage enumeration       -> MediaRepository (active/missing)
    per-lineage currentness   -> AnalysisValidityService (sole authority)
    current opportunity queue -> OpportunityQueueService (sole boundary)

Currentness therefore continues to come from exactly one authority
(AnalysisValidityService). This service only classifies lineages by
reading that authority's fields verbatim and aggregates the counts.

Everything here is DERIVED at read time. Nothing is persisted, and no
schema change is required: every statistic is computed from the
existing media_items, file_observations, analysis_runs and
opportunity_assessments facts.

Health thresholds (documented policy)
-------------------------------------

    analysis coverage (analysed / active):
        >= 0.90 healthy, >= 0.60 warning, else poor

    stale ratio (stale / active):
        <= 0.10 healthy, <= 0.30 warning, else poor

    opportunity ratio (queue / analysed):
        >= 0.50 healthy, >= 0.20 warning, else poor

    overall health score = 0.6 * coverage + 0.4 * (1 - stale ratio)
        reported alongside the overall status, which is the worst of
        the component statuses (any poor component makes the library
        poor; any warning with no poor makes it a warning)

An empty library is defined as healthy (score 1.0).
"""

from app.models.library_intelligence import (
    ConfidenceBucket,
    ConfidenceDistribution,
    LibraryHealth,
    LibraryLineageStatus,
    LibraryStatistics,
    SavingsBucket,
    SavingsDistribution,
    StorageConsumption,
)

from app.services.analysis_validity_service import (
    REASON_NO_CURRENT_OBSERVATION,
)

# ---------------------------------------------------------
# Documented distribution buckets (fixed and deterministic)
# ---------------------------------------------------------

SAVINGS_BUCKETS = (
    (0.0, 10.0),
    (10.0, 20.0),
    (20.0, 30.0),
    (30.0, 40.0),
    (40.0, 50.0),
    (50.0, None),
)

CONFIDENCE_BUCKETS = (
    (0.0, 0.5),
    (0.5, 0.6),
    (0.6, 0.7),
    (0.7, 0.8),
    (0.8, 0.9),
    (0.9, 1.0),
)

# ---------------------------------------------------------
# Documented health policy thresholds
# ---------------------------------------------------------

COVERAGE_HEALTHY = 0.90
COVERAGE_WARNING = 0.60

STALE_HEALTHY = 0.10
STALE_WARNING = 0.30

OPPORTUNITY_HEALTHY = 0.50
OPPORTUNITY_WARNING = 0.20

HEALTH_HEALTHY = 0.80
HEALTH_WARNING = 0.50



from app.services.filesystem_currentness import (
    STATE_MISSING,
    STATE_PRESENT,
    probe_current_file,
)


class LibraryIntelligenceService:
    """
    Authoritative library-level intelligence read authority.

    Read-only. Never writes persistence, never scans the filesystem,
    never invokes experts/rules/fusion, and never reimplements
    currentness.
    """

    # Semantic version of the library-intelligence policy.
    # A semantic change (health thresholds, buckets, aggregation
    # semantics) MUST bump this version.
    semantic_version = "1.0.0"

    def __init__(
        self,
        *,
        media_repository,
        analysis_validity_service,
        opportunity_queue_service,
        current_state_provider=None,
    ):

        self.media_repository = media_repository
        self.validity_service = analysis_validity_service
        self.queue_service = opportunity_queue_service

        self.current_state_provider = (
            current_state_provider
            or (
                lambda lineage: probe_current_file(
                    lineage.file_path
                )
            )
        )

    @classmethod
    def policy_values(cls) -> dict:
        """
        The library-intelligence policy values that affect analytical
        meaning, attributable to semantic_version.
        """

        return {
            "coverage_thresholds": {
                "healthy": COVERAGE_HEALTHY,
                "warning": COVERAGE_WARNING,
            },
            "stale_thresholds": {
                "healthy": STALE_HEALTHY,
                "warning": STALE_WARNING,
            },
            "opportunity_thresholds": {
                "healthy": OPPORTUNITY_HEALTHY,
                "warning": OPPORTUNITY_WARNING,
            },
            "health_score_thresholds": {
                "healthy": HEALTH_HEALTHY,
                "warning": HEALTH_WARNING,
            },
            "savings_buckets": list(SAVINGS_BUCKETS),
            "confidence_buckets": list(CONFIDENCE_BUCKETS),
        }

    # ---------------------------------------------------------
    # Per-lineage classification (internal building block)
    # ---------------------------------------------------------

    def get_lineage_statuses(
        self,
    ) -> tuple[LibraryLineageStatus, ...]:
        """
        Classify every lineage (active first, then missing) from the
        validity authority's read model. Missing lineages are included
        so library totals are complete; they never count as analysed.
        """

        lineages = [
            *self.media_repository.get_active_lineages(),
            *self.media_repository.get_missing_lineages(),
        ]

        return tuple(
            self._classify(lineage)
            for lineage in lineages
        )

    def _classify(
        self,
        lineage,
    ) -> LibraryLineageStatus:

        live = self.current_state_provider(lineage)

        if live.state == STATE_PRESENT:

            validity = self.validity_service.get_validity(
                lineage.id,
                current_size_bytes=live.size_bytes,
                current_file_mtime_ns=live.file_mtime_ns,
            )
            effective_status = lineage.status

        elif live.state == STATE_MISSING:

            validity = self.validity_service.get_validity(
                lineage.id,
                current_missing=True,
            )
            effective_status = "missing"

        else:

            validity = self.validity_service.get_validity(
                lineage.id,
                current_unavailable=True,
            )
            effective_status = "unavailable"

        analysis_required = validity.analysis_required

        # A missing or unavailable lineage has no analysable current
        # filesystem state and must never count as analysed.
        is_analysed = (
            effective_status == "active"
            and not analysis_required
        )

        is_stale = (
            analysis_required
            and len(validity.historical_completed_runs) > 0
        )

        is_changed_media = (
            analysis_required
            and validity.reason == REASON_NO_CURRENT_OBSERVATION
        )

        return LibraryLineageStatus(
            media_id=lineage.id,
            media_status=effective_status,
            validity_reason=validity.reason,
            analysis_required=analysis_required,
            is_analysed=is_analysed,
            is_stale=is_stale,
            is_changed_media=is_changed_media,
            is_changed_since_analysis=is_stale,
            valid_run_id=(
                validity.valid_analysis_run.id
                if validity.valid_analysis_run is not None
                else None
            ),
            historical_run_count=len(
                validity.historical_completed_runs
            ),
            file_size_bytes=lineage.file_size_bytes,
            file_name=lineage.file_name,
        )

    # ---------------------------------------------------------
    # Aggregate statistics
    # ---------------------------------------------------------

    def get_statistics(
        self,
    ) -> LibraryStatistics:
        """
        Aggregate library statistics. Every count is derived from
        lineage enumeration plus the validity authority; opportunity
        aggregates come from the current-valid queue boundary.
        """

        statuses = self.get_lineage_statuses()

        active = [
            entry
            for entry in statuses
            if entry.media_status != "missing"
        ]

        missing = [
            entry
            for entry in statuses
            if entry.media_status == "missing"
        ]

        analysed = [
            entry
            for entry in active
            if entry.is_analysed
        ]

        unanalysed = [
            entry
            for entry in active
            if not entry.is_analysed
        ]

        queue = self.queue_service.get_queue()

        active_count = len(active)

        coverage = (
            (len(analysed) / active_count) * 100
            if active_count > 0
            else 0.0
        )

        return LibraryStatistics(
            total_lineages=len(statuses),
            active_lineages=active_count,
            missing_lineages=len(missing),
            analysed_lineages=len(analysed),
            unanalysed_lineages=len(unanalysed),
            stale_analyses=sum(
                1 for entry in active if entry.is_stale
            ),
            changed_media=sum(
                1 for entry in active if entry.is_changed_media
            ),
            changed_since_analysis=sum(
                1
                for entry in active
                if entry.is_changed_since_analysis
            ),
            analysis_coverage_percent=round(coverage, 2),
            opportunity_count=len(queue),
            total_library_bytes=sum(
                entry.file_size_bytes or 0
                for entry in active
            ),
            total_estimated_saved_bytes=sum(
                candidate.estimated_saved_bytes
                for candidate in queue
            ),
        )

    def get_storage_consumption(
        self,
    ) -> StorageConsumption:
        """
        Storage-consumption view: how the library's bytes are
        distributed across analysed, unanalysed and missing lineages,
        and the storage impact of the current opportunity queue.
        """

        statuses = self.get_lineage_statuses()

        active = [
            entry
            for entry in statuses
            if entry.media_status != "missing"
        ]

        missing = [
            entry
            for entry in statuses
            if entry.media_status == "missing"
        ]

        analysed_bytes = sum(
            entry.file_size_bytes or 0
            for entry in active
            if entry.is_analysed
        )

        unanalysed_bytes = sum(
            entry.file_size_bytes or 0
            for entry in active
            if not entry.is_analysed
        )

        missing_bytes = sum(
            entry.file_size_bytes or 0
            for entry in missing
        )

        queue = self.queue_service.get_queue()

        opportunity_bytes = sum(
            candidate.file_size_bytes
            for candidate in queue
        )

        opportunity_saved_bytes = sum(
            candidate.estimated_saved_bytes
            for candidate in queue
        )

        return StorageConsumption(
            total_library_bytes=(
                analysed_bytes + unanalysed_bytes
            ),
            active_lineage_count=len(active),
            missing_lineage_count=len(missing),
            analysed_bytes=analysed_bytes,
            unanalysed_bytes=unanalysed_bytes,
            missing_bytes=missing_bytes,
            opportunity_bytes=opportunity_bytes,
            opportunity_saved_bytes=opportunity_saved_bytes,
            opportunity_saved_percent=(
                (
                    opportunity_saved_bytes
                    / opportunity_bytes
                    * 100
                )
                if opportunity_bytes > 0
                else 0.0
            ),
            library_savings_percent=(
                (
                    opportunity_saved_bytes
                    / (analysed_bytes + unanalysed_bytes)
                    * 100
                )
                if (analysed_bytes + unanalysed_bytes) > 0
                else 0.0
            ),
        )

    def get_savings_distribution(
        self,
    ) -> SavingsDistribution:
        """
        Distribution of estimated savings across the current-valid
        opportunity queue, in fixed labelled buckets.
        """

        queue = self.queue_service.get_queue()

        buckets = [
            SavingsBucket(
                label=_savings_label(lower, upper),
                lower_percent=lower,
                upper_percent=upper,
            )
            for lower, upper in SAVINGS_BUCKETS
        ]

        for candidate in queue:

            saving_percent = (
                candidate.estimated_saving_percent or 0.0
            )

            for bucket in buckets:

                if not _in_savings_bucket(
                    saving_percent,
                    bucket.lower_percent,
                    bucket.upper_percent,
                ):
                    continue

                buckets[buckets.index(bucket)] = SavingsBucket(
                    label=bucket.label,
                    lower_percent=bucket.lower_percent,
                    upper_percent=bucket.upper_percent,
                    count=bucket.count + 1,
                    total_size_bytes=(
                        bucket.total_size_bytes
                        + candidate.file_size_bytes
                    ),
                    total_saved_bytes=(
                        bucket.total_saved_bytes
                        + candidate.estimated_saved_bytes
                    ),
                )
                break

        return SavingsDistribution(
            buckets=tuple(buckets),
            total_opportunities=len(queue),
            total_size_bytes=sum(
                candidate.file_size_bytes
                for candidate in queue
            ),
            total_saved_bytes=sum(
                candidate.estimated_saved_bytes
                for candidate in queue
            ),
        )

    def get_confidence_distribution(
        self,
    ) -> ConfidenceDistribution:
        """
        Distribution of analytical confidence across the current-valid
        opportunity queue. Confidence values are the authoritative
        opportunity-assessment confidences, never re-derived.
        """

        queue = self.queue_service.get_queue()

        buckets = [
            ConfidenceBucket(
                label=_confidence_label(lower, upper),
                lower=lower,
                upper=upper,
            )
            for lower, upper in CONFIDENCE_BUCKETS
        ]

        for candidate in queue:

            confidence = candidate.confidence or 0.0

            for bucket in buckets:

                if not _in_confidence_bucket(
                    confidence,
                    bucket.lower,
                    bucket.upper,
                ):
                    continue

                buckets[buckets.index(bucket)] = ConfidenceBucket(
                    label=bucket.label,
                    lower=bucket.lower,
                    upper=bucket.upper,
                    count=bucket.count + 1,
                    total_size_bytes=(
                        bucket.total_size_bytes
                        + candidate.file_size_bytes
                    ),
                    total_saved_bytes=(
                        bucket.total_saved_bytes
                        + candidate.estimated_saved_bytes
                    ),
                )
                break

        return ConfidenceDistribution(
            buckets=tuple(buckets),
            total_opportunities=len(queue),
            total_size_bytes=sum(
                candidate.file_size_bytes
                for candidate in queue
            ),
            total_saved_bytes=sum(
                candidate.estimated_saved_bytes
                for candidate in queue
            ),
        )

    def get_health(
        self,
    ) -> LibraryHealth:
        """
        Library health indicators derived from the aggregate statistics.
        Thresholds are documented in the module docstring.
        """

        statistics = self.get_statistics()

        active = statistics.active_lineages

        if active == 0:
            return LibraryHealth(
                health_score=1.0,
                status="healthy",
                analysis_coverage=0.0,
                coverage_status="healthy",
                stale_ratio=0.0,
                stale_status="healthy",
                opportunity_ratio=0.0,
                opportunity_status="healthy",
                indicators=(
                    "no active lineages",
                ),
            )

        coverage = statistics.analysed_lineages / active

        stale_ratio = statistics.stale_analyses / active

        analysed = statistics.analysed_lineages

        opportunity_ratio = (
            statistics.opportunity_count / analysed
            if analysed > 0
            else 0.0
        )

        coverage_status = _ratio_status(
            coverage,
            COVERAGE_HEALTHY,
            COVERAGE_WARNING,
        )

        stale_status = _inverse_ratio_status(
            stale_ratio,
            STALE_HEALTHY,
            STALE_WARNING,
        )

        opportunity_status = _ratio_status(
            opportunity_ratio,
            OPPORTUNITY_HEALTHY,
            OPPORTUNITY_WARNING,
        )

        health_score = (
            (0.6 * coverage) + (0.4 * (1.0 - stale_ratio))
        )

        overall_status = _worst_status(
            coverage_status,
            stale_status,
            opportunity_status,
        )

        indicators = _health_indicators(
            statistics,
            coverage,
            stale_ratio,
            opportunity_ratio,
        )

        return LibraryHealth(
            health_score=round(health_score, 4),
            status=overall_status,
            analysis_coverage=round(coverage, 4),
            coverage_status=coverage_status,
            stale_ratio=round(stale_ratio, 4),
            stale_status=stale_status,
            opportunity_ratio=round(opportunity_ratio, 4),
            opportunity_status=opportunity_status,
            indicators=tuple(indicators),
        )


# ---------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------


def _savings_label(lower, upper):
    if upper is None:
        return f"{lower:g}%+"
    return f"{lower:g}-{upper:g}%"


def _confidence_label(lower, upper):
    return f"{lower:.1f}-{upper:.1f}"


def _in_savings_bucket(value, lower, upper):
    if upper is None:
        return value >= lower
    return lower <= value < upper


def _in_confidence_bucket(value, lower, upper):
    if value == 1.0 and upper == 1.0:
        return True
    return lower <= value < upper


def _ratio_status(value, healthy_at, warning_at):
    if value >= healthy_at:
        return "healthy"
    if value >= warning_at:
        return "warning"
    return "poor"


def _inverse_ratio_status(value, healthy_at, warning_at):
    if value <= healthy_at:
        return "healthy"
    if value <= warning_at:
        return "warning"
    return "poor"


_STATUS_ORDER = {
    "healthy": 0,
    "warning": 1,
    "poor": 2,
}


def _worst_status(*statuses):
    """
    The overall health status is the worst of the component statuses:
    any poor component makes the library poor, any warning component
    (with no poor) makes it a warning.
    """

    return max(
        statuses,
        key=lambda status: _STATUS_ORDER.get(status, 0),
    )


def _health_indicators(
    statistics,
    coverage,
    stale_ratio,
    opportunity_ratio,
):
    indicators = []

    if coverage < COVERAGE_WARNING:
        indicators.append(
            "analysis coverage is low"
        )
    elif coverage < COVERAGE_HEALTHY:
        indicators.append(
            "analysis coverage is moderate"
        )

    if stale_ratio > STALE_WARNING:
        indicators.append(
            "stale analysis ratio is high"
        )
    elif stale_ratio > STALE_HEALTHY:
        indicators.append(
            "stale analysis ratio is elevated"
        )

    if opportunity_ratio < OPPORTUNITY_WARNING:
        indicators.append(
            "few analysed lineages present an opportunity"
        )
    elif opportunity_ratio < OPPORTUNITY_HEALTHY:
        indicators.append(
            "opportunity ratio is moderate"
        )

    return indicators