class MediaService:
    """
    Application boundary for media / lineage read workflows.

    Delegates to existing authorities; it never reimplements lineage,
    identity, existence, or provenance logic:

        lineage reads        -> MediaRepository
        observation history  -> ProvenanceQueryService

    "Not found" raises ValueError, matching the application-layer
    convention and the existing ProvenanceQueryService behaviour.
    """

    def __init__(
        self,
        *,
        media_repository,
        provenance_query_service,
    ):

        self.media_repository = media_repository
        self.provenance_query_service = provenance_query_service

    def get_active_lineages(self):
        """
        Application-facing read of the current active media lineages.

        Delegates to MediaRepository; returns the existing
        MediaLineage read models unchanged.
        """

        return self.media_repository.get_active_lineages()

    def get_media_item(
        self,
        media_id,
    ):
        """
        Retrieve one media lineage.

        Delegates to MediaRepository; raises ValueError when the
        lineage does not exist.
        """

        lineage = self.media_repository.get_media_item(
            media_id
        )

        if lineage is None:
            raise ValueError(
                f"Media lineage {media_id} not found"
            )

        return lineage

    def get_missing_lineages(self):
        """
        Application-facing read of the missing media lineages.

        Delegates to MediaRepository; returns the existing
        MediaLineage read models unchanged.
        """

        return self.media_repository.get_missing_lineages()

    def get_last_scanned_at(self):
        """
        Application-facing read of the most recent recorded scan
        timestamp.

        Delegates to MediaRepository; returns None when no lineage
        has ever been scanned.
        """

        return self.media_repository.get_last_scanned_at()

    def get_observation_history(
        self,
        media_id,
    ):
        """
        Retrieve the observation history for one media lineage.

        Delegates to ProvenanceQueryService (the provenance
        reconstruction authority); returns the existing
        ObservationHistory read model unchanged.
        """

        return (
            self.provenance_query_service
            .get_observation_history(
                media_id
            )
        )
