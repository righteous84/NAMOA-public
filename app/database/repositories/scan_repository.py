from app.models.scan import Scan
from app.models.scan import ScanItem


class ScanRepository:
    """
    Persistence boundary for the durable Scan identity/history layer.

    Owns:

    - scans      one durable identity per scan invocation
    - scan_items per-file grouping records referencing the existing
                 authoritative media/observation/analysis records

    A Scan is a grouping/identity boundary, not an owner of
    intelligence semantics. This repository never writes analysis,
    recommendation, observation, or provenance data; it only
    references the existing rows through scan_items.

    Database connection lifecycle and transactions are owned by the
    caller.
    """

    def __init__(self, connection):
        self.connection = connection

    def begin_scan(
        self,
        *,
        target_scope: str,
    ) -> int:
        """
        Open a new Scan invocation for `target_scope` in the running
        state and return its durable identity.

        Each invocation produces a distinct Scan row; repeated scans
        of the same target never reuse a previous Scan identity.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO scans (
                target_scope,
                status,
                started_at
            )
            VALUES (?, 'running', CURRENT_TIMESTAMP)
            """,
            (target_scope,),
        )

        return cursor.lastrowid

    def record_item(
        self,
        scan_id: int,
        *,
        media_id: int | None = None,
        file_observation_id: int | None = None,
        analysis_run_id: int | None = None,
        outcome: str,
    ) -> int:
        """
        Record how the Scan treated one discovered file.

        `outcome` is one of:

            analysed   a new AnalysisRun was performed and completed
            reused     an existing applicable analysis was reused
                       (no fake run is created for scan association)
            failed     processing this file failed during the scan
            skipped    discovered but not analysed

        The row references existing authoritative records; it never
        duplicates their data.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO scan_items (
                scan_id,
                media_id,
                file_observation_id,
                analysis_run_id,
                outcome
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                media_id,
                file_observation_id,
                analysis_run_id,
                outcome,
            ),
        )

        return cursor.lastrowid

    def set_counts(
        self,
        scan_id: int,
        *,
        files_discovered: int,
        files_analysed: int,
        files_reused: int,
        files_failed: int,
        files_skipped: int,
    ) -> None:
        """
        Record the useful scan counts on the Scan row.

        Counts are maintained by the canonical pipeline which owns the
        per-file outcomes; they are a scan-level summary, not
        duplicated intelligence data.
        """

        self.connection.execute(
            """
            UPDATE scans
            SET
                files_discovered = ?,
                files_analysed = ?,
                files_reused = ?,
                files_failed = ?,
                files_skipped = ?
            WHERE id = ?
            """,
            (
                files_discovered,
                files_analysed,
                files_reused,
                files_failed,
                files_skipped,
                scan_id,
            ),
        )

    def set_discovered(
        self,
        scan_id: int,
        files_discovered: int,
    ) -> None:
        """
        Record the discovered file count as soon as filesystem
        discovery completes, so the analysis phase has a known
        denominator for honest progress.
        """

        self.connection.execute(
            """
            UPDATE scans
            SET files_discovered = ?
            WHERE id = ?
            """,
            (files_discovered, scan_id),
        )

    def mark_analysis_started(
        self,
        scan_id: int,
    ) -> None:
        """
        Record when the per-file analysis phase began (immediately
        after discovery). Used for the honest approximate ETA.
        """

        self.connection.execute(
            """
            UPDATE scans
            SET analysis_started_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND analysis_started_at IS NULL
            """,
            (scan_id,),
        )

    def increment_counts(
        self,
        scan_id: int,
        *,
        analysed: int = 0,
        reused: int = 0,
        failed: int = 0,
        skipped: int = 0,
    ) -> None:
        """
        Increment the durable scan counts after each per-file outcome,
        so the status read reflects real recorded work while the scan
        is still running (honest incremental progress).
        """

        self.connection.execute(
            """
            UPDATE scans
            SET
                files_analysed = files_analysed + ?,
                files_reused = files_reused + ?,
                files_failed = files_failed + ?,
                files_skipped = files_skipped + ?
            WHERE id = ?
            """,
            (analysed, reused, failed, skipped, scan_id),
        )

    def complete_scan(
        self,
        scan_id: int,
    ) -> None:
        """
        Transition the Scan to its successful terminal state.

        The pipeline treats per-file failures as non-fatal: the scan
        reaches its normal terminal outcome while files_failed records
        the partial failures. A Scan is only ever 'failed' when the
        invocation itself failed before completion.
        """

        self.connection.execute(
            """
            UPDATE scans
            SET
                status = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (scan_id,),
        )

    def fail_scan(
        self,
        scan_id: int,
        error_message: str,
    ) -> None:
        """
        Transition the Scan to its failed terminal state when the
        invocation failed before completion.
        """

        self.connection.execute(
            """
            UPDATE scans
            SET
                status = 'failed',
                completed_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE id = ?
            """,
            (error_message, scan_id),
        )

    _SCAN_SELECT_COLUMNS = """
        SELECT
            id,
            target_scope,
            status,
            started_at,
            completed_at,
            analysis_started_at,
            files_discovered,
            files_analysed,
            files_reused,
            files_failed,
            files_skipped,
            error_message,
            created_at
        FROM scans
    """

    def _scan_from_row(self, row) -> Scan:

        return Scan(
            id=row[0],
            target_scope=row[1],
            status=row[2],
            started_at=row[3],
            completed_at=row[4],
            analysis_started_at=row[5],
            files_discovered=row[6],
            files_analysed=row[7],
            files_reused=row[8],
            files_failed=row[9],
            files_skipped=row[10],
            error_message=row[11],
            created_at=row[12],
        )

    def get_scan(
        self,
        scan_id: int,
    ) -> Scan | None:
        """
        Retrieve one Scan by its durable identity.
        """

        row = self.connection.execute(
            self._SCAN_SELECT_COLUMNS + """
            WHERE id = ?
            """,
            (scan_id,),
        ).fetchone()

        if row is None:
            return None

        return self._scan_from_row(row)

    def get_latest_completed_scan(
        self,
        target_scope: str,
    ) -> Scan | None:
        """
        Retrieve the most recently completed Scan for a target scope.

        This is the authoritative "latest/current completed scan"
        query: scan identity is read from the persisted Scan record,
        never reconstructed from timestamps as a heuristic.
        """

        row = self.connection.execute(
            self._SCAN_SELECT_COLUMNS + """
            WHERE target_scope = ?
              AND status = 'completed'
            ORDER BY id DESC
            LIMIT 1
            """,
            (target_scope,),
        ).fetchone()

        if row is None:
            return None

        return self._scan_from_row(row)

    def get_scans_for_target(
        self,
        target_scope: str,
    ) -> list[Scan]:
        """
        Retrieve the historical Scans for a target scope, newest
        first. Historical scans are immutable identity records and are
        never modified by later scans.
        """

        rows = self.connection.execute(
            self._SCAN_SELECT_COLUMNS + """
            WHERE target_scope = ?
            ORDER BY id DESC
            """,
            (target_scope,),
        ).fetchall()

        return [
            self._scan_from_row(row)
            for row in rows
        ]

    _SCAN_ITEM_SELECT_COLUMNS = """
        SELECT
            id,
            scan_id,
            media_id,
            file_observation_id,
            analysis_run_id,
            outcome,
            created_at
        FROM scan_items
    """

    def _scan_item_from_row(self, row) -> ScanItem:

        return ScanItem(
            id=row[0],
            scan_id=row[1],
            media_id=row[2],
            file_observation_id=row[3],
            analysis_run_id=row[4],
            outcome=row[5],
            created_at=row[6],
        )

    def get_scan_items(
        self,
        scan_id: int,
    ) -> list[ScanItem]:
        """
        Retrieve every per-file grouping record for a Scan in
        deterministic order.
        """

        rows = self.connection.execute(
            self._SCAN_ITEM_SELECT_COLUMNS + """
            WHERE scan_id = ?
            ORDER BY id
            """,
            (scan_id,),
        ).fetchall()

        return [
            self._scan_item_from_row(row)
            for row in rows
        ]