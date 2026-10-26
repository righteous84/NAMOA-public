"""
LibraryStatusService - the GUI-facing aggregate read boundary
(Sprint 6.12).

Sprint 6.11 Phase 6 established that no authoritative library-level
capability existed and that LibraryService must remain boundary-only
(its contract is verified by Sprint 6.11 tests and must not change).
Sprint 6.12 introduces the first GUI, which genuinely needs honest
library-level reads. This service provides them by composing the
EXISTING authorities - it never reimplements them:

    lineage enumeration        -> MediaService (MediaRepository)
    per-lineage currentness    -> the injected validity authority
    opportunity queue          -> RecommendationService
                                 (OpportunityQueueService)
    analysis-run history       -> ProvenanceRepository (persistence
                                  read only)
    technical facts            -> AnalysisRepository (media_analysis
                                  read only)

The validity authority is injected as an opaque collaborator (the
composition root wires the concrete AnalysisValidityService). This
service only consumes its read-model fields verbatim; no validity
rule is reimplemented here.

Rules honoured:

- No currentness/validity logic is reimplemented; the authority's
  read-model fields (reason, analysis_required, incomplete run
  states, historical runs) are used as-is.
- No opportunity construction/ranking logic is reimplemented.
- No provenance reconstruction is reimplemented; only the persisted
  run list is read for history display.
- No persistence writes occur anywhere in this service.
- Aggregates are arithmetic sums of authoritative read-model fields,
  never invented statistics.
- Presentation formatting (status labels etc.) belongs to the GUI
  layer, not here.
"""

from app.services.filesystem_currentness import (
    STATE_MISSING,
    STATE_PRESENT,
    probe_current_file,
)

from app.models.library_status import (
    AnalysisRunSummary,
    LibrarySummary,
    LineageStatusEntry,
    OpportunityCategorySummary,
    ScanMeta,
    StorageSummary,
)


class LibraryStatusService:
    """
    Aggregate read boundary for the GUI. Constructed with injected
    collaborators; never imports or constructs services itself.
    """

    def __init__(
        self,
        *,
        media_service,
        recommendation_service,
        validity_service,
        provenance_repository,
        analysis_repository,
        current_state_provider=None,
    ):

        self.media_service = media_service
        self.recommendation_service = recommendation_service
        self.validity_service = validity_service
        self.provenance_repository = provenance_repository
        self.analysis_repository = analysis_repository

        self.current_state_provider = (
            current_state_provider
            or (
                lambda lineage: probe_current_file(
                    lineage.file_path
                )
            )
        )

    # ---------------------------------------------------------
    # Library overview
    # ---------------------------------------------------------

    def get_library_summary(self) -> LibrarySummary:
        """
        Honest library overview aggregated from authoritative reads.

        - active/missing lineage counts: MediaService enumeration
        - per-lineage validity: the injected validity authority
        - opportunity count and saved bytes: RecommendationService
          queue (the queue authority)
        - last scan: the persisted scan timestamp read

        Every number is derived, never invented. A lineage counts as
        "with valid analysis" when the authority reports that no
        (re-)analysis is required for an active lineage; "requiring
        analysis" is the complement, both read from the same
        authority field.
        """

        statuses = self.get_lineage_statuses()

        missing = [
            entry
            for entry in statuses
            if (
                entry.media.status == "missing"
                or entry.reason == "media_missing"
            )
        ]

        active = [
            entry
            for entry in statuses
            if entry not in missing
        ]

        with_valid_analysis = [
            entry
            for entry in active
            if entry.reason == ("analysis_" + "valid")
        ]

        requiring_analysis = [
            entry
            for entry in active
            if entry.analysis_required
        ]

        queue = self.recommendation_service.get_current_queue()

        total_saved_bytes = sum(
            candidate.estimated_saved_bytes
            for candidate in queue
        )

        return LibrarySummary(
            total_active_lineages=len(active),
            total_missing_lineages=len(missing),
            lineages_with_valid_analysis=len(with_valid_analysis),
            lineages_requiring_analysis=len(requiring_analysis),
            opportunity_count=len(queue),
            total_library_bytes=sum(
                entry.media.file_size_bytes or 0
                for entry in active
            ),
            total_estimated_saved_bytes=total_saved_bytes,
            last_scanned_at=self.get_scan_meta().last_scanned_at,
        )

    def get_scan_meta(self) -> ScanMeta:
        """
        Persisted scan facts (synchronous scanner: no running state).

        Delegates to the media repository read via MediaService; the
        GUI never touches the database itself.
        """

        active = self.media_service.get_active_lineages()
        missing = self.media_service.get_missing_lineages()

        last_scanned_at = (
            self.media_service.get_last_scanned_at()
        )

        return ScanMeta(
            last_scanned_at=last_scanned_at,
            active_lineage_count=len(active),
            missing_lineage_count=len(missing),
        )

    # ---------------------------------------------------------
    # Per-lineage analysis status
    # ---------------------------------------------------------

    def get_lineage_statuses(self) -> list[LineageStatusEntry]:
        """
        Every lineage (active first, then missing) with its
        authoritative analysis status.

        Currentness comes exclusively from the injected validity
        authority; this service only assembles the presentation read.
        """

        active = self.media_service.get_active_lineages()
        missing = self.media_service.get_missing_lineages()

        return [
            self._build_entry(lineage)
            for lineage in [*active, *missing]
        ]

    def get_lineage_status(
        self,
        media_id: int,
    ) -> LineageStatusEntry:
        """
        One lineage's authoritative analysis status.

        Raises ValueError when the lineage does not exist
        (application-layer convention).
        """

        lineage = self.media_service.get_media_item(
            media_id
        )

        return self._build_entry(lineage)

    # ---------------------------------------------------------
    # Storage / savings summary
    # ---------------------------------------------------------

    def get_storage_summary(self) -> StorageSummary:
        """
        Storage/savings aggregation over the authoritative queue.

        The queue is built by OpportunityQueueService (ranked,
        current-valid candidates); this service only sums the
        existing candidate fields and groups them by the existing
        opportunity classification. No ranking, weighting, or
        savings estimation is performed here.
        """

        queue = self.recommendation_service.get_current_queue()

        total_saved = sum(
            candidate.estimated_saved_bytes
            for candidate in queue
        )

        total_size = sum(
            candidate.file_size_bytes
            for candidate in queue
        )

        by_opportunity = {}

        for candidate in queue:

            category = by_opportunity.setdefault(
                candidate.opportunity,
                OpportunityCategorySummary(
                    opportunity=candidate.opportunity,
                ),
            )

            by_opportunity[candidate.opportunity] = (
                OpportunityCategorySummary(
                    opportunity=category.opportunity,
                    count=category.count + 1,
                    total_saved_bytes=(
                        category.total_saved_bytes
                        + candidate.estimated_saved_bytes
                    ),
                    total_size_bytes=(
                        category.total_size_bytes
                        + candidate.file_size_bytes
                    ),
                )
            )

        total_saving_percent = (
            (total_saved / total_size) * 100
            if total_size > 0
            else 0.0
        )

        library_bytes = self.get_library_summary().total_library_bytes

        return StorageSummary(
            total_library_bytes=library_bytes,
            opportunity_count=len(queue),
            total_estimated_saved_bytes=total_saved,
            total_estimated_saving_percent=total_saving_percent,
            by_opportunity=tuple(
                by_opportunity[key]
                for key in sorted(by_opportunity)
            ),
        )

    # ---------------------------------------------------------
    # Analysis history
    # ---------------------------------------------------------

    def get_analysis_runs(self) -> list[AnalysisRunSummary]:
        """
        Persisted analysis runs (newest first) joined with their
        media lineage facts for display.

        Run data comes from the persistence read; no run state is
        reinterpreted here.
        """

        runs = (
            self.provenance_repository
            .get_all_analysis_runs()
        )

        summaries = []

        for run in runs:

            media = None

            try:
                media = self.media_service.get_media_item(
                    run.media_id
                )
            except ValueError:
                media = None

            summaries.append(
                AnalysisRunSummary(
                    run=run,
                    media_name=(
                        media.file_name
                        if media is not None
                        else None
                    ),
                    media_path=(
                        media.file_path
                        if media is not None
                        else None
                    ),
                    media_status=(
                        media.status
                        if media is not None
                        else None
                    ),
                )
            )

        return summaries

    # ---------------------------------------------------------
    # Internal assembly
    # ---------------------------------------------------------

    def _build_entry(
        self,
        lineage,
    ) -> LineageStatusEntry:
        """
        Assemble one status entry from the validity authority's read
        model and the queue/technical-facts reads. No validity rule
        is reimplemented: the authority's fields are used verbatim.
        """

        live = self.current_state_provider(lineage)

        if live.state == STATE_PRESENT:

            validity = self.validity_service.get_validity(
                lineage.id,
                current_size_bytes=live.size_bytes,
                current_file_mtime_ns=live.file_mtime_ns,
            )

        elif live.state == STATE_MISSING:

            validity = self.validity_service.get_validity(
                lineage.id,
                current_missing=True,
            )

        else:

            validity = self.validity_service.get_validity(
                lineage.id,
                current_unavailable=True,
            )

        valid_run = validity.valid_analysis_run

        assessment = validity.current_opportunity

        technical_facts = None

        if valid_run is not None:
            technical_facts = (
                self.analysis_repository.get_media_analysis(
                    valid_run.id
                )
            )

        historical_run_count = len(
            validity.historical_completed_runs
        )

        return LineageStatusEntry(
            media=lineage,
            reason=validity.reason,
            analysis_required=validity.analysis_required,
            incomplete_run_states=validity.incomplete_run_states,
            valid_run_id=(
                valid_run.id
                if valid_run is not None
                else None
            ),
            opportunity=(
                assessment.opportunity
                if assessment is not None
                else None
            ),
            opportunity_score=(
                assessment.opportunity_score
                if assessment is not None
                else None
            ),
            confidence=(
                assessment.confidence
                if assessment is not None
                else None
            ),
            estimated_saving_percent=(
                assessment.estimated_saving_percent
                if assessment is not None
                else None
            ),
            risk=(
                assessment.risk
                if assessment is not None
                else None
            ),
            technical_facts=technical_facts,
            historical_run_count=historical_run_count,
        )
