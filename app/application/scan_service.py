from app.database.db import get_connection

from app.database.repositories.scan_repository import (
    ScanRepository,
)


class ScanService:
    """
    Application boundary for library scanning workflows.

    Orchestrates the existing scanner and persistence pipeline:

        scanner   -> app.scanner.scanner.scan_directory
        pipeline  -> app.database.pipeline.save_to_db

    The scanner discovers files; the pipeline persists them and, when
    scan_root is supplied, performs the authoritative filesystem
    existence reconciliation. This service passes the scanned path
    through as scan_root so reconciliation is preserved.

    The Scan is a grouping/identity boundary for the invocation. When
    a `scan_repository` is supplied, this service opens one durable
    Scan identity for the invocation, hands it to the pipeline (which
    records one scan_items grouping row per encountered file), and
    finalises the Scan's terminal state. It never owns intelligence
    semantics and never duplicates analysis/observation/provenance
    data.

    GUI/UX Phase 5 additions (honest background progress):

    - start_scan() opens a durable Scan identity without running the
      pipeline, so the GUI can start the scan and poll its status.
    - scan_with_report() accepts an already-begun scan_id and records
      files_discovered + analysis_started_at as soon as discovery
      completes, and the pipeline maintains the per-file counts
      incrementally, so the status read reflects real recorded work.
    - get_scan_status() reads the durable scan's current state.
    - scan-completed / scan-failed notifications are emitted
      best-effort via the injected NotificationService.

    This service never implements filesystem scanning, exclusion,
    reconciliation, lineage identity, or missing-file logic itself.
    """

    def __init__(
        self,
        *,
        scanner,
        pipeline,
        scan_repository=None,
        notification_service=None,
        user_policy_service=None,
        preference_state_provider=None,
    ):

        self.scanner = scanner

        self.pipeline = pipeline

        # When None, scan persistence is disabled entirely and the
        # pipeline is invoked exactly as before (no scan_id), so
        # existing callers/tests that construct this service without a
        # repository keep their previous behaviour.
        self.scan_repository = scan_repository

        self.notification_service = notification_service

        self.user_policy_service = user_policy_service

        # Optional zero-or-one-argument callable returning an
        # accepted-preference input (or None) for the scan at hand.
        # When None (the default), no preference state is resolved
        # and the pipeline is invoked exactly as before, so all
        # existing callers keep their previous behaviour.
        self.preference_state_provider = preference_state_provider

    def _get_preference_state(self, database_path):
        """
        Resolve accepted preference inputs for one scan, or None
        when no provider is wired. A None result (or no provider)
        means the pipeline runs exactly as without preferences.
        The provider contract is a callable taking database_path
        and returning accepted preference state or None.
        """

        provider = self.preference_state_provider

        if provider is None:
            return None

        return provider(database_path)

        # Optional zero-or-one-argument callable returning an
        # accepted-preference input (or None) for the scan at hand.
        # When None (the default), no preference state is resolved
        # and the pipeline is invoked exactly as before, so all
        # existing callers keep their previous behaviour.

    def _begin_scan(
        self,
        path,
        database_path,
    ):
        """
        Open one durable Scan identity for the invocation.

        The Scan row is committed on a dedicated connection so the
        pipeline (which manages its own connection) can reference it.
        """

        if self.scan_repository is None:
            return None

        connection = get_connection(database_path)

        scan_id = ScanRepository(
            connection
        ).begin_scan(
            target_scope=path,
        )

        connection.commit()

        connection.close()

        return scan_id

    def _finalise_scan(
        self,
        scan_id,
        database_path,
        status,
        error_message=None,
    ):
        """
        Transition the Scan to its terminal state.

        `completed` reflects a normal invocation outcome (per-file
        failures are non-fatal and are captured in scan counts/items).
        `failed` reflects an invocation that failed before completion.
        """

        if scan_id is None:
            return

        connection = get_connection(database_path)

        repository = ScanRepository(connection)

        if status == "completed":

            repository.complete_scan(scan_id)

        else:

            repository.fail_scan(
                scan_id,
                error_message,
            )

        connection.commit()

        connection.close()

    def _mark_analysis_phase(
        self,
        scan_id,
        files_discovered,
        database_path,
    ):
        """
        Record the discovered count and the analysis-phase start
        immediately after filesystem discovery completes, so honest
        incremental progress has a known denominator.
        """

        if scan_id is None:
            return

        connection = get_connection(database_path)

        repository = ScanRepository(connection)

        repository.set_discovered(
            scan_id,
            files_discovered,
        )

        repository.mark_analysis_started(scan_id)

        connection.commit()

        connection.close()

    def _get_effective_policy(self):
        if self.user_policy_service is None:
            return None

        return self.user_policy_service.get_effective_policy()

    def _notify(
        self,
        category,
        title,
        message,
        *,
        scan_id=None,
    ):
        """
        Best-effort notification emission. A notification write must
        never fail the scan.
        """

        if self.notification_service is None:
            return

        try:

            self.notification_service.create(
                category=category,
                title=title,
                message=message,
                scan_id=scan_id,
            )

        except Exception:

            from app.utils.logger import logger

            logger.warning(
                "notification write skipped (best-effort): "
                f"{category} {title}"
            )

    def start_scan(
        self,
        path,
        *,
        database_path=None,
    ) -> int:
        """
        Open a durable Scan identity for `path` WITHOUT running the
        pipeline. Returns the scan id the caller can poll with
        get_scan_status.

        Raises RuntimeError when scan persistence is not wired.
        """

        if self.scan_repository is None:

            raise RuntimeError(
                "start_scan requires scan persistence (a "
                "scan_repository) to be wired"
            )

        return self._begin_scan(
            path,
            database_path,
        )

    def get_scan_status(
        self,
        scan_id: int,
        *,
        database_path=None,
    ):
        """
        The durable Scan's current state (running/partial counts or
        terminal). Read through the injected repository (same database
        as the service graph), so the progress the pipeline commits is
        visible to the polling GUI.
        """

        if self.scan_repository is None:
            return None

        return self.scan_repository.get_scan(scan_id)

    def scan(
        self,
        path,
        *,
        database_path=None,
        excluded_paths=None,
    ):
        """
        Perform an application-facing scan of `path`.

        Returns the enriched persistence results from the existing
        pipeline unchanged.

        - the scanner discovers the files at `path`
        - the pipeline persists them and reconciles the filesystem
          existence lifecycle under `path` (scan_root)
        - an empty successful scan remains authoritative: absent
          active lineages under `path` become missing
        - exclusion handling is delegated to the existing pipeline
          (`excluded_paths=None` lets the pipeline resolve the
          repository's configured exclusions)

        When scan persistence is enabled, the Scan is marked failed if
        the invocation fails before completion; otherwise it completes
        with the pipeline's honest per-file outcomes.
        """

        scan_id = self._begin_scan(
            path,
            database_path,
        )

        try:

            files = self.scanner(path)

            self._mark_analysis_phase(
                scan_id,
                len(files),
                database_path,
            )

            user_policy = self._get_effective_policy()

            preference_state = self._get_preference_state(
                database_path
            )

            enriched = self._run_pipeline(
                files,
                path,
                database_path,
                excluded_paths,
                scan_id,
                user_policy,
                preference_state,
            )

        except Exception as exc:

            self._finalise_scan(
                scan_id,
                database_path,
                "failed",
                str(exc),
            )

            self._notify(
                "error",
                "Scan failed",
                f"{path}: {exc}",
                scan_id=scan_id,
            )

            raise

        self._finalise_scan(
            scan_id,
            database_path,
            "completed",
        )

        self._notify(
            "success",
            "Scan complete",
            f"{path}: {len(files)} files discovered",
            scan_id=scan_id,
        )

        return enriched

    def scan_with_report(
        self,
        path,
        *,
        database_path=None,
        excluded_paths=None,
        scan_id=None,
    ):
        """
        Perform an application-facing scan of `path` and report
        honest counts alongside the enriched results.

        Identical orchestration to `scan` (same scanner and pipeline,
        same authoritative reconciliation via scan_root); this method
        additionally returns:

        - files_discovered: number of files the scanner returned
        - persisted_count:   number of enriched results the pipeline
                             returned (files for which a new analysis
                             was executed and persisted)
        - scan_id:           the durable Scan identity for this
                             invocation, when scan persistence is
                             enabled (None otherwise)

        `scan_id` may be supplied by a caller that already opened the
        Scan identity (GUI/UX Phase 5 background scans); when omitted
        a fresh identity is opened exactly as before.

        The pipeline is synchronous: there is no running-scan state
        and no progress percentage. Files the pipeline skips (e.g.
        unreadable or non-video content) are neither counted as
        discovered nor as persisted; this is an honest reflection of
        the existing pipeline's reporting.
        """

        if scan_id is None:

            scan_id = self._begin_scan(
                path,
                database_path,
            )

        try:

            files = self.scanner(path)

            self._mark_analysis_phase(
                scan_id,
                len(files),
                database_path,
            )

            user_policy = self._get_effective_policy()

            preference_state = self._get_preference_state(
                database_path
            )

            enriched = self._run_pipeline(
                files,
                path,
                database_path,
                excluded_paths,
                scan_id,
                user_policy,
                preference_state,
            )

        except Exception as exc:

            self._finalise_scan(
                scan_id,
                database_path,
                "failed",
                str(exc),
            )

            self._notify(
                "error",
                "Scan failed",
                f"{path}: {exc}",
                scan_id=scan_id,
            )

            raise

        self._finalise_scan(
            scan_id,
            database_path,
            "completed",
        )

        self._notify(
            "success",
            "Scan complete",
            f"{path}: {len(files)} files discovered",
            scan_id=scan_id,
        )

        return {
            "path": path,
            "files_discovered": len(files),
            "persisted_count": len(enriched),
            "scan_id": scan_id,
            "enriched": enriched,
        }

    def _run_pipeline(
        self,
        files,
        path,
        database_path,
        excluded_paths,
        scan_id,
        user_policy,
        preference_state=None,
    ):
        """
        Invoke the canonical pipeline, passing the durable Scan
        identity through only when scan persistence is enabled so the
        pipeline's call signature remains unchanged for existing
        callers that do not participate in scan recording. Accepted
        preference state is forwarded only when present, so pipeline
        fakes and callers that do not know the keyword keep working
        exactly as before.
        """

        pipeline_kwargs = {}

        if preference_state is not None:
            pipeline_kwargs["preference_state"] = preference_state

        if scan_id is not None:

            return self.pipeline(
                files,
                database_path=database_path,
                scan_root=path,
                excluded_paths=excluded_paths,
                scan_id=scan_id,
                user_policy=user_policy,
                **pipeline_kwargs,
            )

        return self.pipeline(
            files,
            database_path=database_path,
            scan_root=path,
            excluded_paths=excluded_paths,
            user_policy=user_policy,
            **pipeline_kwargs,
        )