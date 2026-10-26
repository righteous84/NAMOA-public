-- ==========================================================
-- Migration 033
--
-- Phase 6 Execution: source observation linkage + deletion
-- lifecycle
--
-- Extends media_executions with:
--
--   source_observation_id
--       The exact file observation approved for execution. It
--       refers to the observation that produced the current-valid
--       analysis; it is never manufactured merely to satisfy a
--       foreign key. Establishes explicit identity continuity:
--       source_observation_id -> result_observation_id.
--
--   delete_original_requested
--       Explicit user choice to delete the preserved original
--       after successful verified replacement. Defaults to false.
--       Deletion is a separate file-lifecycle action, never an
--       implicit consequence of optimisation.
--
--   deletion_state
--       deleting_original / original_deleted / deletion_failed.
--
--   original_deleted_at
--       Timestamp when the preserved original was deleted.
--
-- All columns are additive; existing rows remain valid and are
-- never rewritten.
-- ==========================================================

ALTER TABLE media_executions
    ADD COLUMN source_observation_id INTEGER;

ALTER TABLE media_executions
    ADD COLUMN delete_original_requested INTEGER NOT NULL DEFAULT 0;

ALTER TABLE media_executions
    ADD COLUMN deletion_state TEXT;

ALTER TABLE media_executions
    ADD COLUMN original_deleted_at TEXT;

CREATE INDEX idx_media_executions_state_media
    ON media_executions (state, media_id);