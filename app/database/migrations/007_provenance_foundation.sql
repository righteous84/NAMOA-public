-- ==========================================================
-- NAMOA Migration 007
-- Provenance Foundation (Sprint 5.2 Phase 1)
--
-- Introduces the provenance anchor (analysis_runs) and its
-- two Phase 1 child records: configuration_snapshots and
-- input_snapshots.
--
-- Additive only. No existing table is altered. No Python
-- migration handler is required for this migration.
--
-- Ownership:
--   media_items          -> owned by MediaRepository (unchanged)
--   configuration_snapshots,
--   analysis_runs,
--   input_snapshots       -> owned by ProvenanceRepository
-- ==========================================================

-- ----------------------------------------------------------
-- Configuration Snapshot
--
-- Captures the runtime configuration that produced a single
-- AnalysisRun. Stored as one generic JSON payload rather than
-- individual columns per configuration concern, so future
-- configuration areas (decision rules, experts, pipeline
-- settings, environment, etc.) do not require schema changes.
--
-- One AnalysisRun owns exactly one ConfigurationSnapshot.
-- Snapshots are immutable and are NOT deduplicated in Phase 1:
-- provenance clarity is favoured over storage efficiency here.
-- Content-hash based deduplication is left as a future
-- optimisation, not part of this migration.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS configuration_snapshots (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Generic configuration payload, e.g.:
    -- {
    --     "decision_rules": {...},
    --     "rule_weights": {...},
    --     "experts": {...},
    --     "pipeline": {...},
    --     "environment": {...}
    -- }
    configuration_json TEXT NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------
-- Analysis Run
--
-- The provenance anchor. A single media item may have many
-- analysis runs over time; each run is an independent,
-- explainable historical record and is never overwritten once
-- completed.
--
-- Lifecycle: pending -> running -> (completed | failed | cancelled)
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis_runs (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    media_id INTEGER NOT NULL,

    configuration_snapshot_id INTEGER NOT NULL,

    status TEXT NOT NULL
        CHECK(status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
        DEFAULT 'pending',

    started_at DATETIME,
    completed_at DATETIME,

    error_message TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE,

    FOREIGN KEY(configuration_snapshot_id)
        REFERENCES configuration_snapshots(id)
);

-- ----------------------------------------------------------
-- Input Snapshot
--
-- Captures what entered a given AnalysisRun. Structured
-- columns hold the fields already known to exist on the
-- scanner output; raw_scanner_json preserves the full scanner
-- payload verbatim so nothing beyond the structured fields is
-- lost, without assuming or redesigning the scanner's shape.
--
-- file_hash is populated only when the scanner already
-- provides one; no hash is computed as part of this migration
-- or its consuming code.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS input_snapshots (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    analysis_run_id INTEGER NOT NULL,

    file_path TEXT NOT NULL,
    file_name TEXT,
    file_extension TEXT,

    size_bytes INTEGER,
    file_hash TEXT,

    raw_scanner_json TEXT NOT NULL,

    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(analysis_run_id)
        REFERENCES analysis_runs(id)
        ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Indexes
--
-- analysis_runs.media_id is the expected lookup path for
-- "all runs for this file"; input_snapshots.analysis_run_id
-- for the 1:1 join back to its run.
-- ----------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_analysis_runs_media_id
    ON analysis_runs(media_id);

CREATE INDEX IF NOT EXISTS idx_input_snapshots_analysis_run_id
    ON input_snapshots(analysis_run_id);