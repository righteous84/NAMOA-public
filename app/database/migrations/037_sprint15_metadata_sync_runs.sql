-- ==========================================================
-- Migration 037
--
-- Sprint 15 productisation:
-- Provider metadata synchronisation run ledger
-- ==========================================================
--
-- Schema change rationale:
--
-- Metadata sync is an explicit operator action whose
-- latest known status must survive page refreshes and
-- restarts. This standalone ledger records one row per
-- sync run (provider, timestamps, state, honest
-- counters, error text). It has no foreign keys and
-- touches no existing table, so upgrade paths that
-- exclude other Sprint 15 tables are unaffected. Only
-- counts and error-type text are stored here; payloads
-- stay in metadata_observations and credentials never
-- reach this table.
--
-- 1. metadata_sync_runs
--    Append-only per-run records; the latest row per
--    provider is the displayed "last sync" state.
-- ==========================================================

CREATE TABLE metadata_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    provider TEXT NOT NULL
        CHECK(provider IN (
            'jellyfin',
            'radarr',
            'sonarr'
        )),

    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    finished_at DATETIME,

    state TEXT NOT NULL DEFAULT 'running'
        CHECK(state IN (
            'running',
            'succeeded',
            'failed'
        )),

    total_items INTEGER NOT NULL DEFAULT 0,

    inspected INTEGER NOT NULL DEFAULT 0,

    matched INTEGER NOT NULL DEFAULT 0,

    updated INTEGER NOT NULL DEFAULT 0,

    unchanged INTEGER NOT NULL DEFAULT 0,

    unmatched INTEGER NOT NULL DEFAULT 0,

    needs_review INTEGER NOT NULL DEFAULT 0,

    error_count INTEGER NOT NULL DEFAULT 0,

    error_text TEXT NOT NULL DEFAULT '',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_metadata_sync_runs_provider
    ON metadata_sync_runs (provider, id DESC);
