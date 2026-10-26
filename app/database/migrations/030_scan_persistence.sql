-- ==========================================================
-- NAMOA Migration 030
-- Scan Persistence Foundation
-- ==========================================================
--
-- Gives the existing operational Scan boundary (ScanService +
-- canonical pipeline with a scan_root) a durable identity and
-- historical boundary.
--
-- A Scan is a grouping/identity boundary for one bounded invocation
-- of the scanning workflow against a target scope. It is NOT an
-- owner of intelligence semantics: it does not duplicate analysis,
-- recommendation, observation, execution, or provenance data.
--
--   scans
--       One row per scan invocation.
--
--       target_scope     the scanned path (the pipeline's scan_root)
--       status           running / completed / failed
--       started_at       when the invocation began
--       completed_at     when it reached a terminal state
--       files_*          useful scan counts (discovered, analysed,
--                        reused, failed, skipped)
--       error_message    recorded only when the scan failed
--
--   scan_items
--       One row per file the scan encountered, recording how the
--       scan treated that file. This is the scan's grouping
--       relationship to the existing authoritative records; it
--       references (never duplicates) the media lineage, the exact
--       file observation, and the analysis run involved.
--
--       outcome
--           analysed   a NEW analysis run was performed and completed
--                      during this scan (scan_items.analysis_run_id
--                      references it)
--           reused     an existing applicable analysis was reused:
--                      no fake AnalysisRun is created merely for scan
--                      association (scan_items.analysis_run_id
--                      references the historical run that was reused)
--           failed     processing this file failed during the scan
--                      (references the run when one was begun)
--           skipped    the file was discovered but not analysed
--                      (e.g. non-video / unreadable content)
--
-- Repeated scans of the same target produce distinct scans rows;
-- historical Scan A is never modified when Scan B occurs.
-- ==========================================================

CREATE TABLE scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    target_scope TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'running'
        CHECK(status IN (
            'running',
            'completed',
            'failed'
        )),

    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,

    files_discovered INTEGER NOT NULL DEFAULT 0,
    files_analysed INTEGER NOT NULL DEFAULT 0,
    files_reused INTEGER NOT NULL DEFAULT 0,
    files_failed INTEGER NOT NULL DEFAULT 0,
    files_skipped INTEGER NOT NULL DEFAULT 0,

    error_message TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_scans_target_scope
    ON scans (target_scope);

CREATE INDEX idx_scans_status
    ON scans (status);

CREATE TABLE scan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    scan_id INTEGER NOT NULL,

    media_id INTEGER,
    file_observation_id INTEGER,
    analysis_run_id INTEGER,

    outcome TEXT NOT NULL
        CHECK(outcome IN (
            'analysed',
            'reused',
            'failed',
            'skipped'
        )),

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(scan_id)
        REFERENCES scans(id)
        ON DELETE CASCADE,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id),

    FOREIGN KEY(file_observation_id)
        REFERENCES file_observations(id),

    FOREIGN KEY(analysis_run_id)
        REFERENCES analysis_runs(id)
);

CREATE INDEX idx_scan_items_scan
    ON scan_items (scan_id);

CREATE INDEX idx_scan_items_media
    ON scan_items (media_id);

CREATE INDEX idx_scan_items_run
    ON scan_items (analysis_run_id);