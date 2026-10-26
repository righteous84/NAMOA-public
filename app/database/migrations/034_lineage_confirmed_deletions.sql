-- ==========================================================
-- NAMOA Migration 034
--
-- Lineage confirmed-deletion events (Phase 10).
--
-- Records deliberate, verified destructions of preserved bytes
-- against the affected media lineage, distinct from observed
-- disappearance (media_items.status = 'missing', which means
-- cause unknown).
--
-- Design notes:
--
-- - The lineage itself is NOT marked deleted: the only current
--   producer is the explicit post-success execution deletion of
--   a staging backup, after which the lineage continues with
--   the verified result. Marking the live lineage deleted
--   would corrupt truth.
-- - No observation row is created: file_observations are
--   filesystem scans that feed currentness, and a destruction
--   has no resulting path to observe.
-- - Rows are append-only history. Failed deletions record
--   nothing here (the execution record already carries
--   deletion_failed). Nothing is backfilled.
-- ==========================================================

CREATE TABLE IF NOT EXISTS lineage_confirmed_deletions (
    id INTEGER PRIMARY KEY,
    media_id INTEGER NOT NULL,
    execution_job_id INTEGER NOT NULL,
    source_observation_id INTEGER,
    deleted_path TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    detail TEXT,
    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
);

CREATE INDEX IF NOT EXISTS
    idx_lineage_confirmed_deletions_media
    ON lineage_confirmed_deletions(media_id);
