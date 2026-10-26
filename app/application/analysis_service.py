import os


class AnalysisService:
    """
    Application boundary for the analysis workflow.

    Delegates to the canonical analysis pipeline
    (app.database.pipeline.save_to_db). Analysis lifecycle,
    file-observation/lineage anchoring, failure/abandoned-run
    semantics, currentness gating, and provenance behaviour are owned
    by the pipeline's existing authorities; nothing is duplicated
    here.
    """

    def __init__(
        self,
        *,
        analysis_pipeline,
        media_service=None,
        user_policy_service=None,
    ):

        self.analysis_pipeline = analysis_pipeline

        # Optional collaborator used only by the targeted-analysis
        # workflow to resolve a lineage identity and its current
        # filesystem path through the application boundary.
        self.media_service = media_service

        self.user_policy_service = user_policy_service

    def _get_effective_policy(self):
        if self.user_policy_service is None:
            return None

        return self.user_policy_service.get_effective_policy()

    def analyze(
        self,
        files,
        *,
        database_path=None,
        scan_root=None,
        excluded_paths=None,
    ):
        """
        Application-facing analysis of the given scanned files.

        Delegates to the existing canonical analysis pipeline and
        returns its enriched result list unchanged.

        - each file's media lineage and file observation are resolved
          by the pipeline (identity is never resolved here)
        - the currentness/validity gate is the pipeline's existing
          authority, evaluated against the freshly scanned fingerprint
        - analysis-run lifecycle (started/completed/failed) and
          provenance are persisted by the pipeline's authorities
        - intelligence (evidence, knowledge, experts, decision rules,
          fusion) is owned by the pipeline's analysis engine
        - when scan_root is supplied the pipeline performs its
          authoritative existence reconciliation

        This service implements none of that itself. Files must carry
        the same keys the pipeline consumes (path, name, extension,
        size_bytes, file_mtime_ns).
        """

        user_policy = self._get_effective_policy()

        return self.analysis_pipeline(
            files,
            database_path=database_path,
            scan_root=scan_root,
            excluded_paths=excluded_paths,
            user_policy=user_policy,
        )

    def analyze_lineage(
        self,
        media_id,
        *,
        database_path=None,
    ):
        """
        Targeted analysis/revalidation of ONE media lineage.

        Resolves the lineage through MediaService, stats its current
        filesystem path, builds the scanner-shaped record, and
        delegates to the canonical analysis pipeline. The pipeline's
        validity gate (AnalysisValidityService) decides whether a new
        analysis run is required; an already-valid current analysis
        skips exactly as it would during a full scan.

        Deliberate boundaries:

        - scan_root is intentionally NOT supplied: targeted analysis
          never performs filesystem existence reconciliation, so a
          failed or skipped request cannot mutate lineage state.
        - excluded_paths resolution stays with the pipeline
          (configured exclusions remain respected).
        - currentness is never evaluated here; there is no way to
          force analysis past a valid gate through this workflow.

        Raises ValueError (application-facing honest errors) when the
        lineage does not exist, is not active, or its current path is
        not accessible on disk.
        """

        if self.media_service is None:

            raise RuntimeError(
                "AnalysisService requires media_service for "
                "targeted analysis"
            )

        lineage = self.media_service.get_media_item(media_id)

        if lineage.status != "active":

            raise ValueError(
                f"Media lineage {media_id} is "
                f"'{lineage.status}'; targeted analysis requires "
                f"an active lineage"
            )

        path = lineage.file_path

        try:

            stat = os.stat(path)

        except OSError as error:

            raise ValueError(
                f"Current path of media lineage {media_id} is "
                f"not accessible: {path}"
            ) from error

        name = lineage.file_name or os.path.basename(path)

        record = {
            "path": path,
            "name": name,
            "size_bytes": stat.st_size,
            "file_mtime_ns": stat.st_mtime_ns,
            "extension": os.path.splitext(path)[1].lower(),
            "filesystem_device": stat.st_dev,
            "filesystem_inode": stat.st_ino,
        }

        return self.analyze(
            [record],
            database_path=database_path,
        )