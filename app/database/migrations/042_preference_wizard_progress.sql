-- ==========================================================
-- Migration 042
--
-- Phase 16 correction: durable Preferences Wizard progress.
--
-- The Preferences Wizard previously held its position only in a
-- process-local in-memory session map (`_SESSIONS`). A browser
-- restart, a service recreation, or a process restart therefore
-- lost all knowledge of which logical media items the user had
-- already answered, and "Continue Preferences Wizard" restarted
-- at the same first item unless a review suggestion had already
-- been accepted.
--
-- This migration adds the minimum durable state required to make
-- Wizard continuation genuine:
--
--   preference_wizard_progress
--       One row per logical media item (media identity, i.e. the
--       active lineage id as text) that the Wizard has durably
--       answered, with the explicit answer the user gave. It is
--       keyed by logical media identity, never by an observation
--       id, so a new filesystem observation for an optimised file
--       keeps the same Wizard decision. It carries no preference
--       authority: it records progress only. Accepted preferences
--       remain owned exclusively by preference_examples /
--       preference_suggestions and the review lifecycle.
--
--   preference_wizard_state
--       A single-row state record: the last completed logical
--       media item, whether the user intentionally stopped,
--       whether the current eligible population is complete, and
--       when the user last explicitly reset the Wizard. It is a
--       cursor/flag record only.
--
-- Both tables are additive and isolated. They do not alter any
-- existing table, do not change analysis, currentness, review,
-- acceptance, policy, or execution authority, and can be dropped
-- without affecting any accepted preference or media fact.
--
-- Reset semantics: `Reset Wizard` deletes rows from
-- preference_wizard_progress and resets preference_wizard_state.
-- It deliberately never touches preference_suggestions,
-- preference_review_events, preference_examples, media
-- observations, lineage, or execution history.
-- ==========================================================


CREATE TABLE IF NOT EXISTS preference_wizard_progress (
    media_id TEXT PRIMARY KEY,

    answer TEXT NOT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_preference_wizard_progress_updated
    ON preference_wizard_progress (updated_at);


CREATE TABLE IF NOT EXISTS preference_wizard_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),

    last_media_id TEXT,

    stopped INTEGER NOT NULL DEFAULT 0,

    completed INTEGER NOT NULL DEFAULT 0,

    reset_at DATETIME,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
