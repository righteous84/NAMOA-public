from app.models.analysis_validity import AnalysisValidity


REASON_MEDIA_MISSING = "media_missing"
REASON_NO_CURRENT_OBSERVATION = "no_current_observation"
REASON_NO_COMPLETED_ANALYSIS = "no_completed_analysis"
REASON_ANALYSIS_VALID = "analysis_valid"
REASON_FILESYSTEM_UNAVAILABLE = "filesystem_unavailable"


class AnalysisValidityService:
    """
    Read-only domain service that derives whether a media lineage
    currently has a valid completed analysis for its current
    filesystem state.

    Validity is DERIVED, never persisted.

    The validity key is the existing filesystem fingerprint:

        size_bytes + file_mtime_ns

    which is the same fingerprint used by
    MediaRepository.sync_media() for change detection.

    Currentness means:

        current filesystem state == fingerprint of a completed analysis

    NOT:

        latest observation ID == analysis observation ID

    This service:

    - never scans the filesystem
    - never modifies media_items / file_observations / analysis_runs
    - never creates observations or runs
    - never changes run status
    - never invokes experts / rules / fusion
    - never recomputes opportunities

    It owns the domain interpretation only. Repositories remain
    persistence-oriented.
    """

    def __init__(
        self,
        *,
        media_repository,
        provenance_repository,
        analysis_repository,
    ):

        self.media_repository = media_repository
        self.provenance_repository = provenance_repository
        self.analysis_repository = analysis_repository


    def get_validity(
        self,
        media_id: int,
        *,
        current_size_bytes: int | None = None,
        current_file_mtime_ns: int | None = None,
        current_missing: bool = False,
        current_unavailable: bool = False,
    ) -> AnalysisValidity:
        """
        Derive current analysis validity for a media lineage.

        The fingerprint being evaluated is resolved as follows:

        1. If the caller supplies current_size_bytes / and/or
           current_file_mtime_ns, those values ARE the evaluated
           fingerprint - the persisted media fingerprint is never
           silently substituted when a caller-supplied value is
           present.
        2. Otherwise the fingerprint stored on the active media
           lineage is used.

        This distinction matters: Phase 2 will pass the freshly
        scanned filesystem fingerprint here so that currentness is
        evaluated against the actual filesystem state rather than
        against whatever fingerprint happens to be persisted.

        Raises:
            ValueError: if the media lineage does not exist.
        """

        media = self.media_repository.get_media_item(
            media_id
        )

        if media is None:
            raise ValueError(
                f"Media lineage {media_id} not found"
            )

        # --------------------------------------------------
        # Missing media: no current filesystem analysis state.
        # --------------------------------------------------

        if media.status == "missing" or current_missing:
            return self._build_validity(
                media_id=media_id,
                media_status="missing",
                current_size_bytes=None,
                current_file_mtime_ns=None,
                current_observation=None,
                valid_analysis_run=None,
                current_opportunity=None,
                analysis_required=False,
                reason=REASON_MEDIA_MISSING,
                incomplete_run_states=(),
                historical_completed_runs=(),
            )

        if current_unavailable:

            observations = (
                self.media_repository
                .get_file_observations(media_id)
            )

            return self._build_validity(
                media_id=media_id,
                media_status=media.status,
                current_size_bytes=None,
                current_file_mtime_ns=None,
                current_observation=None,
                valid_analysis_run=None,
                current_opportunity=None,
                analysis_required=False,
                reason=REASON_FILESYSTEM_UNAVAILABLE,
                incomplete_run_states=(),
                historical_completed_runs=(
                    self._historical_completed_runs(
                        media_id,
                        observations,
                        None,
                        None,
                    )
                ),
            )

        # --------------------------------------------------
        # Resolve the current filesystem fingerprint.
        # --------------------------------------------------

        fp_size = (
            current_size_bytes
            if current_size_bytes is not None
            else media.file_size_bytes
        )

        fp_mtime = (
            current_file_mtime_ns
            if current_file_mtime_ns is not None
            else media.file_mtime_ns
        )

        # --------------------------------------------------
        # Resolve the current observation.
        #
        # The current observation is the highest-id FileObservation
        # belonging to the lineage whose size_bytes + file_mtime_ns
        # exactly match the fingerprint being evaluated. It is NOT a
        # global MAX(id) - only matching observations qualify.
        #
        # Observations arrive ordered by id ascending, so taking the
        # last matching observation is equivalent to selecting the
        # highest id among matches.
        # --------------------------------------------------

        observations = (
            self.media_repository
            .get_file_observations(
                media_id
            )
        )

        current_observation = None

        for observation in observations:

            if (
                observation.size_bytes == fp_size
                and observation.file_mtime_ns == fp_mtime
            ):

                if (
                    current_observation is None
                    or observation.id > current_observation.id
                ):
                    current_observation = observation

        if current_observation is None:
            return self._build_validity(
                media_id=media_id,
                media_status=media.status,
                current_size_bytes=fp_size,
                current_file_mtime_ns=fp_mtime,
                current_observation=None,
                valid_analysis_run=None,
                current_opportunity=None,
                analysis_required=True,
                reason=REASON_NO_CURRENT_OBSERVATION,
                incomplete_run_states=(),
                historical_completed_runs=self._historical_completed_runs(
                    media_id,
                    observations,
                    fp_size,
                    fp_mtime,
                ),
            )

        # --------------------------------------------------
        # Resolve the valid/current completed analysis.
        #
        # Any completed run linked to an observation whose
        # fingerprint matches the current fingerprint qualifies.
        # Among qualifying completed runs the highest run id is
        # selected deterministically.
        # --------------------------------------------------

        completed_runs = []
        incomplete_run_states = set()

        for observation in observations:

            if not (
                observation.size_bytes == fp_size
                and observation.file_mtime_ns == fp_mtime
            ):
                continue

            for run in (
                self.provenance_repository
                .get_analysis_runs_by_observation(
                    observation.id
                )
            ):

                if run.status == "completed":
                    completed_runs.append(run)
                else:
                    incomplete_run_states.add(
                        run.status
                    )

        valid_run = (
            max(
                completed_runs,
                key=lambda run: run.id,
            )
            if completed_runs
            else None
        )

        # --------------------------------------------------
        # Current opportunity from the valid run only.
        # --------------------------------------------------

        current_opportunity = None

        if valid_run is not None:
            current_opportunity = (
                self.analysis_repository
                .get_opportunity_assessment(
                    valid_run.id
                )
            )

        analysis_required = valid_run is None

        reason = (
            REASON_ANALYSIS_VALID
            if valid_run is not None
            else REASON_NO_COMPLETED_ANALYSIS
        )

        return self._build_validity(
            media_id=media_id,
            media_status=media.status,
            current_size_bytes=fp_size,
            current_file_mtime_ns=fp_mtime,
            current_observation=current_observation,
            valid_analysis_run=valid_run,
            current_opportunity=current_opportunity,
            analysis_required=analysis_required,
            reason=reason,
            incomplete_run_states=tuple(
                sorted(incomplete_run_states)
            ),
            historical_completed_runs=self._historical_completed_runs(
                media_id,
                observations,
                fp_size,
                fp_mtime,
            ),
        )


    def requires_analysis(
        self,
        media_id: int,
        *,
        current_size_bytes: int | None = None,
        current_file_mtime_ns: int | None = None,
    ) -> bool:
        """
        Convenience wrapper returning whether the lineage currently
        requires a (re-)analysis.
        """

        return self.get_validity(
            media_id,
            current_size_bytes=current_size_bytes,
            current_file_mtime_ns=current_file_mtime_ns,
        ).analysis_required


    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------

    @staticmethod
    def _build_validity(
        *,
        media_id: int,
        media_status,
        current_size_bytes: int | None,
        current_file_mtime_ns: int | None,
        current_observation,
        valid_analysis_run,
        current_opportunity,
        analysis_required: bool,
        reason: str,
        incomplete_run_states: tuple[str, ...],
        historical_completed_runs: tuple,
    ) -> AnalysisValidity:

        return AnalysisValidity(
            media_id=media_id,
            media_status=media_status,
            current_observation=current_observation,
            current_size_bytes=current_size_bytes,
            current_file_mtime_ns=current_file_mtime_ns,
            valid_analysis_run=valid_analysis_run,
            current_opportunity=current_opportunity,
            analysis_required=analysis_required,
            reason=reason,
            incomplete_run_states=incomplete_run_states,
            historical_completed_runs=historical_completed_runs,
        )


    def _historical_completed_runs(
        self,
        media_id: int,
        observations,
        fp_size: int | None,
        fp_mtime: int | None,
    ) -> tuple:

        historical = []

        for observation in observations:

            if (
                observation.size_bytes == fp_size
                and observation.file_mtime_ns == fp_mtime
            ):
                continue

            for run in (
                self.provenance_repository
                .get_analysis_runs_by_observation(
                    observation.id
                )
            ):

                if run.status == "completed":
                    historical.append(run)

        return tuple(
            sorted(
                historical,
                key=lambda run: run.id,
            )
        )
