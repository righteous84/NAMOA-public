"""
Explicit migration handlers.

Some migrations require conditional schema reconciliation that
cannot safely be represented as static SQL in SQLite.

Handlers are registered by exact migration filename.

The migration runner remains responsible for:
- migration discovery
- execution order
- migration bookkeeping

This module only contains explicit migration-specific behaviour.
"""

from typing import Callable


def _existing_columns(conn, table_name: str) -> set[str]:
    """
    Return existing column names for a SQLite table.
    """

    cursor = conn.execute(
        f"PRAGMA table_info({table_name})"
    )

    return {row[1] for row in cursor.fetchall()}


def _has_unique_file_path_constraint(conn) -> bool:
    """
    Determine whether media_items currently has a UNIQUE
    constraint/index covering exactly file_path.

    Migration 019 removes the historical inline UNIQUE
    constraint from media_items.file_path so that historical
    missing lineages can coexist with a newer object later
    appearing at the same path.
    """

    cursor = conn.execute(
        """
        PRAGMA index_list(media_items)
        """
    )

    indexes = cursor.fetchall()

    for row in indexes:

        # PRAGMA index_list columns:
        # seq, name, unique, origin, partial

        index_name = row[1]
        is_unique = bool(row[2])
        is_partial = bool(row[4])

        # The Migration 019 replacement index is intentionally
        # UNIQUE(file_path) only for current/non-missing rows.
        # It must not be mistaken for the historical global
        # UNIQUE(file_path) constraint.
        if not is_unique or is_partial:
            continue

        index_columns = conn.execute(
            f"""
            PRAGMA index_info("{index_name}")
            """
        ).fetchall()

        columns = [
            index_row[2]
            for index_row in index_columns
        ]

        if columns == ["file_path"]:
            return True

    return False


def _rebuild_media_items_without_global_path_uniqueness(conn) -> None:
    """
    Rebuild media_items so file_path is no longer globally UNIQUE.

    Historical missing media items must be allowed to retain their
    previous path while a different current media item later owns
    that same path.

    Existing data and IDs are preserved.

    The new uniqueness rule is implemented separately as a partial
    unique index covering all current filesystem owners except
    status='missing'.
    """

    if not _has_unique_file_path_constraint(conn):
        return

    conn.execute(
        "PRAGMA foreign_keys = OFF"
    )

    try:

        conn.execute(
            """
            CREATE TABLE media_items_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,

                file_size_bytes INTEGER NOT NULL,
                duration_seconds REAL,

                media_type TEXT
                    CHECK(
                        media_type IN (
                            'movie',
                            'episode',
                            'unknown'
                        )
                    )
                    DEFAULT 'unknown',

                last_modified DATETIME,
                sha256_hash TEXT,
                last_scanned_at DATETIME,

                status TEXT
                    CHECK(
                        status IN (
                            'active',
                            'missing',
                            'excluded',
                            'processing'
                        )
                    )
                    DEFAULT 'active',

                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP,

                file_mtime_ns INTEGER
            )
            """
        )

        conn.execute(
            """
            INSERT INTO media_items_new (
                id,
                file_path,
                file_name,
                file_size_bytes,
                duration_seconds,
                media_type,
                last_modified,
                sha256_hash,
                last_scanned_at,
                status,
                created_at,
                updated_at,
                file_mtime_ns
            )
            SELECT
                id,
                file_path,
                file_name,
                file_size_bytes,
                duration_seconds,
                media_type,
                last_modified,
                sha256_hash,
                last_scanned_at,
                status,
                created_at,
                updated_at,
                file_mtime_ns
            FROM media_items
            """
        )

        conn.execute(
            """
            DROP TABLE media_items
            """
        )

        conn.execute(
            """
            ALTER TABLE media_items_new
            RENAME TO media_items
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX
                idx_media_items_current_path
            ON media_items(file_path)
            WHERE COALESCE(status, 'active') <> 'missing'
            """
        )

    finally:

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )


def _create_file_observations(conn) -> None:
    """
    Create the immutable historical filesystem observation table.

    Each row records what NAMOA observed about a filesystem object
    at a particular point in time.

    Identity evidence is persisted rather than reconstructed later.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_observations (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            media_id INTEGER NOT NULL,

            observed_at DATETIME NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            file_path TEXT NOT NULL,
            file_name TEXT,
            file_extension TEXT,

            size_bytes INTEGER NOT NULL,
            file_mtime_ns INTEGER NOT NULL,

            filesystem_device TEXT,
            filesystem_inode INTEGER,

            sha256_hash TEXT,

            identity_match_method TEXT NOT NULL,

            identity_evidence_json TEXT NOT NULL
                DEFAULT '{}',

            created_at DATETIME NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(media_id)
                REFERENCES media_items(id)
                ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_file_observations_media_id
        ON file_observations(media_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_file_observations_observed_at
        ON file_observations(observed_at)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_file_observations_sha256
        ON file_observations(sha256_hash)
        WHERE sha256_hash IS NOT NULL
        """
    )


def _add_analysis_run_observation_link(conn) -> None:
    """
    Add the explicit link from an AnalysisRun to the exact
    FileObservation it analysed.

    Nullable initially because historical AnalysisRuns predate
    FileObservation and must remain intact.
    """

    columns = _existing_columns(
        conn,
        "analysis_runs",
    )

    if "file_observation_id" not in columns:

        conn.execute(
            """
            ALTER TABLE analysis_runs
            ADD COLUMN file_observation_id INTEGER
            """
        )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_analysis_runs_file_observation_id
        ON analysis_runs(file_observation_id)
        """
    )


def handle_006_reconcile_media_analysis(conn) -> None:
    """
    Migration 006 reconciliation.

    Ensures media_analysis contains the columns that exist in the
    current live database but were not correctly captured through
    migrations.

    Required columns:

        duration      REAL
        bitrate       REAL
        video_codec   TEXT
        audio_tracks  INTEGER

    Existing columns are preserved.
    Missing columns are added individually.
    """

    required_columns = [
        ("duration", "REAL"),
        ("bitrate", "REAL"),
        ("video_codec", "TEXT"),
        ("audio_tracks", "INTEGER"),
    ]

    existing_columns = _existing_columns(
        conn,
        "media_analysis",
    )

    for column_name, column_type in required_columns:

        if column_name in existing_columns:
            continue

        conn.execute(
            f"""
            ALTER TABLE media_analysis
            ADD COLUMN {column_name} {column_type}
            """
        )


def handle_008_analysis_output_provenance_lineage(conn) -> None:
    """
    Migration 008.

    Adds provenance lineage links between intelligence outputs
    and the AnalysisRun that produced them.

    media_analysis:
        analysis_run_id INTEGER

    opportunity_assessments:
        analysis_run_id INTEGER
    """

    media_analysis_columns = _existing_columns(
        conn,
        "media_analysis",
    )

    if "analysis_run_id" not in media_analysis_columns:

        conn.execute(
            """
            ALTER TABLE media_analysis
            ADD COLUMN analysis_run_id INTEGER
            """
        )

    opportunity_columns = _existing_columns(
        conn,
        "opportunity_assessments",
    )

    if "analysis_run_id" not in opportunity_columns:

        conn.execute(
            """
            ALTER TABLE opportunity_assessments
            ADD COLUMN analysis_run_id INTEGER
            """
        )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_media_analysis_analysis_run_id
        ON media_analysis(analysis_run_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_opportunity_assessments_analysis_run_id
        ON opportunity_assessments(analysis_run_id)
        """
    )


def handle_019_file_observation_lineage(conn) -> None:
    """
    Migration 019.

    Establishes the first durable filesystem lineage layer.

    Responsibilities:

    1. Remove the global UNIQUE constraint from media_items.file_path.
    2. Replace it with current-owner path uniqueness.
    3. Create file_observations.
    4. Link AnalysisRuns to the exact FileObservation they analysed.

    Historical media rows are preserved exactly, including their
    existing primary keys.
    """

    _rebuild_media_items_without_global_path_uniqueness(
        conn
    )

    _create_file_observations(
        conn
    )

    _add_analysis_run_observation_link(
        conn
    )

    # Validate that the rebuilt schema has not introduced broken
    # foreign-key relationships.
    violations = conn.execute(
        """
        PRAGMA foreign_key_check
        """
    ).fetchall()

    if violations:

        raise RuntimeError(
            "Migration 019 produced foreign-key violations: "
            f"{violations}"
        )


def handle_038_metadata_sync_runs_needs_review(conn) -> None:
    """
    Migration 038.

    Adds the needs_review counter to metadata_sync_runs
    for databases that applied the earlier 037 revision
    before the column existed. Existing rows keep their
    data and receive the default 0.

    Fresh databases already have the column (037 creates
    the full schema), so the change is applied only when
    the column is actually missing. Both upgrade paths
    converge on the same final schema.
    """

    columns = _existing_columns(
        conn,
        "metadata_sync_runs",
    )

    if "needs_review" not in columns:

        conn.execute(
            """
            ALTER TABLE metadata_sync_runs
            ADD COLUMN needs_review INTEGER NOT NULL
            DEFAULT 0
            """
        )


MIGRATION_HANDLERS: dict[str, Callable] = {
    "006_reconcile_media_analysis.sql":
        handle_006_reconcile_media_analysis,

    "008_add_analysis_run_lineage.sql":
        handle_008_analysis_output_provenance_lineage,

    "019_file_observation_lineage.sql":
        handle_019_file_observation_lineage,

    "038_sprint15_metadata_sync_runs_needs_review.sql":
        handle_038_metadata_sync_runs_needs_review,
}


def handle_020_analysis_run_states(conn):
    """
    Expand analysis_runs lifecycle states to include 'abandoned'.

    SQLite rewrites foreign-key references to analysis_runs as
    analysis_runs_old when the parent table is renamed.

    Therefore every dependent table must also be rebuilt so its
    foreign key points to the new analysis_runs table.
    """

    conn.execute("PRAGMA foreign_keys = OFF")

    # ----------------------------------------------------------
    # Preserve dependent table definitions/data before the
    # analysis_runs rebuild.
    # ----------------------------------------------------------

    dependent_tables = [
        "input_snapshots",
        "analysis_run_knowledge",
        "classification_evidence",
        "expert_results",
        "decision_signals",
    ]

    # Rename dependent tables first so their foreign keys do not
    # become permanently attached to analysis_runs_old.
    for table in dependent_tables:
        conn.execute(
            f'ALTER TABLE "{table}" RENAME TO "{table}_old"'
        )

    # ----------------------------------------------------------
    # Rebuild analysis_runs with the expanded state constraint.
    # ----------------------------------------------------------

    conn.execute("""
        ALTER TABLE analysis_runs
        RENAME TO analysis_runs_old
    """)

    conn.execute("""
        CREATE TABLE analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            media_id INTEGER NOT NULL,

            configuration_snapshot_id INTEGER NOT NULL,

            status TEXT NOT NULL
                CHECK(status IN (
                    'pending',
                    'running',
                    'completed',
                    'failed',
                    'cancelled',
                    'abandoned'
                ))
                DEFAULT 'pending',

            started_at DATETIME,
            completed_at DATETIME,

            error_message TEXT,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            file_observation_id INTEGER,

            FOREIGN KEY(media_id)
                REFERENCES media_items(id)
                ON DELETE CASCADE,

            FOREIGN KEY(configuration_snapshot_id)
                REFERENCES configuration_snapshots(id)
        )
    """)

    conn.execute("""
        INSERT INTO analysis_runs (
            id,
            media_id,
            configuration_snapshot_id,
            status,
            started_at,
            completed_at,
            error_message,
            created_at,
            file_observation_id
        )
        SELECT
            id,
            media_id,
            configuration_snapshot_id,
            status,
            started_at,
            completed_at,
            error_message,
            created_at,
            file_observation_id
        FROM analysis_runs_old
    """)

    conn.execute("DROP TABLE analysis_runs_old")

    # ----------------------------------------------------------
    # Rebuild dependent tables with FKs pointing to analysis_runs.
    # ----------------------------------------------------------

    conn.execute("""
        CREATE TABLE input_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            analysis_run_id INTEGER NOT NULL,

            file_path TEXT NOT NULL,
            file_name TEXT,
            file_extension TEXT,

            size_bytes INTEGER,
            file_hash TEXT,

            raw_scanner_json TEXT NOT NULL,

            captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            file_mtime_ns INTEGER,

            FOREIGN KEY(analysis_run_id)
                REFERENCES analysis_runs(id)
                ON DELETE CASCADE
        )
    """)

    conn.execute("""
        INSERT INTO input_snapshots
        SELECT * FROM input_snapshots_old
    """)

    conn.execute("DROP TABLE input_snapshots_old")

    conn.execute("""
        CREATE TABLE analysis_run_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            analysis_run_id INTEGER NOT NULL,

            knowledge_set_id INTEGER NOT NULL,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(analysis_run_id)
                REFERENCES analysis_runs(id)
                ON DELETE CASCADE,

            FOREIGN KEY(knowledge_set_id)
                REFERENCES knowledge_sets(id)
        )
    """)

    conn.execute("""
        INSERT INTO analysis_run_knowledge
        SELECT * FROM analysis_run_knowledge_old
    """)

    conn.execute("DROP TABLE analysis_run_knowledge_old")

    conn.execute("""
        CREATE TABLE classification_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            analysis_run_id INTEGER NOT NULL,

            domain TEXT NOT NULL,

            value TEXT NOT NULL,

            confidence REAL NOT NULL,

            source TEXT NOT NULL,

            evidence_id TEXT,

            matched_text TEXT,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(analysis_run_id)
                REFERENCES analysis_runs(id)
                ON DELETE CASCADE
        )
    """)

    conn.execute("""
        INSERT INTO classification_evidence
        SELECT * FROM classification_evidence_old
    """)

    conn.execute("DROP TABLE classification_evidence_old")

    conn.execute("""
        CREATE TABLE expert_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            analysis_run_id INTEGER NOT NULL,

            expert_name TEXT NOT NULL,

            confidence REAL NOT NULL,

            observations_json TEXT NOT NULL,

            notes TEXT NOT NULL,

            expert_data_json TEXT NOT NULL,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(analysis_run_id)
                REFERENCES analysis_runs(id)
                ON DELETE CASCADE
        )
    """)

    conn.execute("""
        INSERT INTO expert_results
        SELECT * FROM expert_results_old
    """)

    conn.execute("DROP TABLE expert_results_old")

    conn.execute("""
        CREATE TABLE decision_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            analysis_run_id INTEGER NOT NULL,

            rule_name TEXT NOT NULL,

            signal_type TEXT NOT NULL,

            opportunity_score REAL NOT NULL,

            confidence REAL NOT NULL,

            reasoning_json TEXT NOT NULL,

            signal_data_json TEXT NOT NULL,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(analysis_run_id)
                REFERENCES analysis_runs(id)
                ON DELETE CASCADE
        )
    """)

    conn.execute("""
        INSERT INTO decision_signals
        SELECT * FROM decision_signals_old
    """)

    conn.execute("DROP TABLE decision_signals_old")

    # ----------------------------------------------------------
    # Restore indexes.
    # ----------------------------------------------------------

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_analysis_runs_media_id
        ON analysis_runs(media_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_analysis_runs_file_observation_id
        ON analysis_runs(file_observation_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_input_snapshots_analysis_run_id
        ON input_snapshots(analysis_run_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_classification_evidence_run
        ON classification_evidence(analysis_run_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_expert_results_run
        ON expert_results(analysis_run_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_decision_signals_run
        ON decision_signals(analysis_run_id)
    """)

    conn.execute("PRAGMA foreign_keys = ON")

MIGRATION_HANDLERS['020_analysis_run_states.sql'] = handle_020_analysis_run_states
