class LibraryService:
    """
    Application boundary for library-level workflows.

    Sprint 6.11 Phase 6 established that no authoritative library-level
    capability existed and left this service as an intentionally empty
    boundary. Sprint 7 introduces that capability:
    LibraryIntelligenceService (app/services/library_intelligence_service.py),
    the authoritative library-intelligence authority built on the
    existing MediaRepository / AnalysisValidityService /
    OpportunityQueueService authorities.

    This service therefore now orchestrates that authority: every
    workflow is a thin delegation to LibraryIntelligenceService, and
    no library intelligence, currentness, aggregation, or persistence
    logic is reimplemented here.

    Application-layer conventions preserved:
    - collaborators injected keyword-only (no service locator)
    - read models returned unchanged
    - dependency direction strictly downward
    - domain errors propagated
    """

    def __init__(
        self,
        *,
        library_intelligence_service,
    ):

        self.library_intelligence_service = (
            library_intelligence_service
        )

    def get_lineage_statuses(self):
        """
        Classified per-lineage library status derived from the
        validity authority (via LibraryIntelligenceService).
        """

        return (
            self.library_intelligence_service
            .get_lineage_statuses()
        )

    def get_statistics(self):
        """
        Authoritative library statistics (active/missing/analysed/
        unanalysed/stale/coverage/opportunity aggregates).
        """

        return (
            self.library_intelligence_service
            .get_statistics()
        )

    def get_storage_consumption(self):
        """
        Authoritative storage-consumption view of the library.
        """

        return (
            self.library_intelligence_service
            .get_storage_consumption()
        )

    def get_savings_distribution(self):
        """
        Authoritative savings distribution over the current-valid
        opportunity queue.
        """

        return (
            self.library_intelligence_service
            .get_savings_distribution()
        )

    def get_confidence_distribution(self):
        """
        Authoritative confidence distribution over the current-valid
        opportunity queue.
        """

        return (
            self.library_intelligence_service
            .get_confidence_distribution()
        )

    def get_library_health(self):
        """
        Authoritative library health indicators.
        """

        return (
            self.library_intelligence_service
            .get_health()
        )