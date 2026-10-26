import json

from app.models.analysis_run import AnalysisRun
from app.models.configuration_snapshot import ConfigurationSnapshot
from app.models.knowledge_usage import KnowledgeUsage
from app.models.input_snapshot import InputSnapshot


class ProvenanceRepository:
    """
    Persistence boundary for NAMOA provenance.

    Owns:

    - configuration_snapshots
    - analysis_runs
    - input_snapshots

    AnalysisRun is explicitly linked to the exact
    FileObservation that was analysed.

    This repository does not:

    - run analysis
    - make decisions
    - modify MediaContext
    - save analysis results

    Database connection lifecycle and transactions are owned
    by the caller.
    """

    def __init__(self, connection):
        self.connection = connection


    def record_file_observation(
        self,
        *,
        media_id: int,
        scanner_input: dict,
        identity_match_method: str,
        identity_evidence: dict | None = None,
    ) -> int:
        """
        Persist one immutable filesystem observation.

        The observation records exactly what the scanner saw
        at this point in time.

        Transaction/commit lifecycle remains owned by the caller.
        """

        if identity_evidence is None:
            identity_evidence = {}

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO file_observations (
                media_id,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_mtime_ns,
                filesystem_device,
                filesystem_inode,
                sha256_hash,
                identity_match_method,
                identity_evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                scanner_input.get("path"),
                scanner_input.get("name"),
                scanner_input.get("extension"),
                scanner_input.get("size_bytes"),
                scanner_input.get("file_mtime_ns"),
                scanner_input.get("filesystem_device"),
                scanner_input.get("filesystem_inode"),
                scanner_input.get("file_hash"),
                identity_match_method,
                json.dumps(identity_evidence),
            ),
        )

        return cursor.lastrowid

    def begin_run(
        self,
        *,
        media_id: int,
        file_observation_id: int,
        configuration: dict,
        scanner_input: dict,
        intelligence_identity: str | None = None,
    ) -> int:
        """
        Create the complete provenance foundation for one
        analysis execution.

        Creates:

        ConfigurationSnapshot
        AnalysisRun
        InputSnapshot

        The AnalysisRun is explicitly anchored to the exact
        FileObservation that was analysed and carries the canonical
        intelligence identity digest of the context that produced it.
        """

        cursor = self.connection.cursor()

        # -------------------------
        # Configuration Snapshot
        # -------------------------

        cursor.execute(
            """
            INSERT INTO configuration_snapshots (
                configuration_json
            )
            VALUES (?)
            """,
            (
                json.dumps(configuration),
            ),
        )

        configuration_id = cursor.lastrowid

        # -------------------------
        # Analysis Run
        # -------------------------

        cursor.execute(
            """
            INSERT INTO analysis_runs (
                media_id,
                configuration_snapshot_id,
                file_observation_id,
                intelligence_identity,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                media_id,
                configuration_id,
                file_observation_id,
                intelligence_identity,
                "pending",
            ),
        )

        run_id = cursor.lastrowid

        # -------------------------
        # Input Snapshot
        # -------------------------

        cursor.execute(
            """
            INSERT INTO input_snapshots (
                analysis_run_id,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_hash,
                file_mtime_ns,
                raw_scanner_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                scanner_input.get("path"),
                scanner_input.get("name"),
                scanner_input.get("extension"),
                scanner_input.get("size_bytes"),
                scanner_input.get("file_hash"),
                scanner_input.get("file_mtime_ns"),
                json.dumps(scanner_input),
            ),
        )

        return run_id

    def record_knowledge_usage(
        self,
        analysis_run_id: int,
        knowledge_usage: set[KnowledgeUsage],
    ) -> None:

        if not knowledge_usage:
            return

        self.connection.executemany(
            """
            INSERT INTO analysis_run_knowledge (
                analysis_run_id,
                knowledge_set_id
            )
            VALUES (?, ?)
            """,
            [
                (
                    analysis_run_id,
                    usage.knowledge_set_id,
                )
                for usage in knowledge_usage
            ],
        )

    def record_intelligence_identity(
        self,
        analysis_run_id: int,
        intelligence_identity: str,
    ) -> None:
        """
        Persist the canonical intelligence identity digest for a run.

        Invoked by the pipeline once the run's consulted knowledge
        sets are known, so the digest covers exactly the relevant
        knowledge versions. Runs are never re-attributed afterwards.
        """

        self.connection.execute(
            """
            UPDATE analysis_runs
            SET intelligence_identity = ?
            WHERE id = ?
            """,
            (
                intelligence_identity,
                analysis_run_id,
            ),
        )

    def start_run(
        self,
        analysis_run_id: int,
    ) -> None:

        self.connection.execute(
            """
            UPDATE analysis_runs
            SET
                status = ?,
                started_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "running",
                analysis_run_id,
            ),
        )

    def complete_run(
        self,
        analysis_run_id: int,
    ) -> None:

        self.connection.execute(
            """
            UPDATE analysis_runs
            SET
                status = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "completed",
                analysis_run_id,
            ),
        )

    def fail_run(
        self,
        analysis_run_id: int,
        error_message: str,
    ) -> None:

        self.connection.execute(
            """
            UPDATE analysis_runs
            SET
                status = ?,
                completed_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE id = ?
            """,
            (
                "failed",
                error_message,
                analysis_run_id,
            ),
        )

    def cancel_run(
        self,
        analysis_run_id: int,
        reason: str,
    ) -> None:

        self.connection.execute(
            """
            UPDATE analysis_runs
            SET
                status = ?,
                completed_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE id = ?
            """,
            (
                "cancelled",
                reason,
                analysis_run_id,
            ),
        )

    def abandon_run(
        self,
        analysis_run_id: int,
        reason: str,
    ) -> None:

        self.connection.execute(
            """
            UPDATE analysis_runs
            SET
                status = ?,
                completed_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE id = ?
            """,
            (
                "abandoned",
                reason,
                analysis_run_id,
            ),
        )

    def find_stale_runs(
        self,
        hours: int = 24,
    ):

        return self.connection.execute(
            """
            SELECT
                id,
                media_id,
                started_at,
                status
            FROM analysis_runs
            WHERE status = ?
            AND started_at < datetime(
                'now',
                ?
            )
            """,
            (
                "running",
                f"-{hours} hours",
            ),
        ).fetchall()

    _RUN_SELECT_COLUMNS = """
        SELECT
            id,
            media_id,
            file_observation_id,
            configuration_snapshot_id,
            intelligence_identity,
            status,
            started_at,
            completed_at,
            error_message,
            created_at
        FROM analysis_runs
    """

    def _run_from_row(self, row) -> AnalysisRun:

        return AnalysisRun(
            id=row[0],
            media_id=row[1],
            file_observation_id=row[2],
            configuration_snapshot_id=row[3],
            intelligence_identity=row[4],
            status=row[5],
            started_at=row[6],
            completed_at=row[7],
            error_message=row[8],
            created_at=row[9],
        )

    def get_analysis_run(
        self,
        analysis_run_id: int,
    ) -> AnalysisRun | None:
        """
        Retrieve an AnalysisRun provenance record.
        """

        row = self.connection.execute(
            self._RUN_SELECT_COLUMNS + """
            WHERE id = ?
            """,
            (
                analysis_run_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return self._run_from_row(row)

    def get_knowledge_usage(
        self,
        analysis_run_id: int,
    ) -> list[KnowledgeUsage]:

        rows = self.connection.execute(
            """
            SELECT
                knowledge_set_id
            FROM analysis_run_knowledge
            WHERE analysis_run_id = ?
            ORDER BY id
            """,
            (
                analysis_run_id,
            ),
        ).fetchall()

        return [
            KnowledgeUsage(
                knowledge_set_id=row[0]
            )
            for row in rows
        ]

    def get_file_observation(
        self,
        file_observation_id: int,
    ):
        """
        Retrieve a single immutable FileObservation.

        Returns None when the observation does not exist.
        """

        from app.models.file_observation import (
            FileObservation
        )

        row = self.connection.execute(
            """
            SELECT
                id,
                media_id,
                observed_at,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_mtime_ns,
                filesystem_device,
                filesystem_inode,
                sha256_hash,
                identity_match_method,
                identity_evidence_json,
                created_at
            FROM file_observations
            WHERE id = ?
            """,
            (
                file_observation_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return FileObservation(
            id=row[0],
            media_id=row[1],
            observed_at=row[2],
            file_path=row[3],
            file_name=row[4],
            file_extension=row[5],
            size_bytes=row[6],
            file_mtime_ns=row[7],
            filesystem_device=row[8],
            filesystem_inode=row[9],
            sha256_hash=row[10],
            identity_match_method=row[11],
            identity_evidence=json.loads(
                row[12] or "{}"
            ),
            created_at=row[13],
        )

    def get_configuration_snapshot(
        self,
        configuration_snapshot_id: int,
    ) -> dict:
        """
        Retrieve the immutable configuration snapshot for a run.

        Returns an empty dict when the snapshot does not exist.
        The snapshot contains the intelligence version manifest, policy
        values, and Git revision that produced the run.
        """

        row = self.connection.execute(
            """
            SELECT configuration_json
            FROM configuration_snapshots
            WHERE id = ?
            """,
            (configuration_snapshot_id,),
        ).fetchone()

        if row is None:
            return {}

        try:
            return json.loads(row[0] or "{}")
        except ValueError:
            return {}

    def get_analysis_runs_by_observation(
        self,
        file_observation_id: int,
    ) -> list[AnalysisRun]:
        """
        Retrieve all analysis runs executed against one immutable
        observation, in deterministic run order.
        """
        rows = self.connection.execute(
            self._RUN_SELECT_COLUMNS + """
            WHERE file_observation_id = ?
            ORDER BY id
            """,
            (
                file_observation_id,
            ),
        ).fetchall()

        return [
            self._run_from_row(row)
            for row in rows
        ]

    def get_all_analysis_runs(
        self,
    ) -> list[AnalysisRun]:
        """
        Retrieve every persisted analysis run, newest first.

        This is a persistence read used to assemble the analysis
        history view; run interpretation is never performed here.
        """

        rows = self.connection.execute(
            self._RUN_SELECT_COLUMNS + """
            ORDER BY id DESC
            """
        ).fetchall()

        return [
            self._run_from_row(row)
            for row in rows
        ]