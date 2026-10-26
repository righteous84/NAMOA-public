-- ==========================================================
-- Migration 041
--
-- Phase 15E: Preference review lifecycle
--
-- Durable review state for preference suggestions: suggestion rows
-- with a closed status lifecycle, accepted preference example
-- evidence, and an append-only review event ledger.
--
-- These tables store user review decisions as durable application
-- facts. They do not alter analytical results, optimisation
-- authority, execution authority, or any existing table. Suggestion
-- rows reference assessment and rule data; they never copy
-- OpportunityAssessment payloads. Statuses follow the closed
-- lifecycle enforced by the review domain layer; the CHECK
-- constraints below mirror that vocabulary at the schema level.
--
-- Reversibility: history is append-only (review events are never
-- updated or deleted); acceptances and rejections are terminal
-- states reached only through explicit transitions, each with its
-- own event row, so any decision reconstructs fully.
-- ==========================================================


-- ----------------------------------------------------------
-- Preference suggestions under review
--
-- One row per deterministic suggestion identity. Regeneration is
-- idempotent on suggestion_id: identical active suggestions are
-- never duplicated; changed rules or facts supersede the stale
-- row rather than rewriting it.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS preference_suggestions (
    suggestion_id TEXT PRIMARY KEY,

    media_id TEXT NOT NULL,

    analysis_fingerprint TEXT NOT NULL,

    matched_rule_id TEXT NOT NULL,

    rule_version TEXT NOT NULL,

    derivation_version TEXT NOT NULL,

    source_example_ids_json TEXT NOT NULL DEFAULT '[]',

    proposed_answer TEXT,

    coverage_state TEXT NOT NULL,

    reason TEXT NOT NULL DEFAULT '',

    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN (
            'proposed',
            'accepted',
            'rejected',
            'superseded'
        )),

    computed_at TEXT NOT NULL DEFAULT '',

    superseded_by TEXT,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_preference_suggestions_media
    ON preference_suggestions (media_id);

CREATE INDEX IF NOT EXISTS idx_preference_suggestions_status
    ON preference_suggestions (status);


-- ----------------------------------------------------------
-- Preference review provenance
--
-- Append-only history. Every review transition appends exactly one
-- row with actor attribution; rows are never updated or deleted.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS preference_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    suggestion_id TEXT NOT NULL,

    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'proposed',
            'accepted',
            'rejected',
            'changed',
            'superseded',
            'reopened'
        )),

    previous_status TEXT,

    new_status TEXT,

    actor TEXT NOT NULL DEFAULT 'system',

    detail TEXT,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (suggestion_id)
        REFERENCES preference_suggestions (suggestion_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_preference_review_events_suggestion
    ON preference_review_events (suggestion_id);

CREATE INDEX IF NOT EXISTS idx_preference_review_events_created
    ON preference_review_events (created_at);


-- ----------------------------------------------------------
-- Accepted preference examples
--
-- Explicit preference evidence produced by acceptance. Rows are
-- immutable: corrections insert new rows, never update. Each row
-- links back to the accepting suggestion for full reconstruction.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS preference_examples (
    example_id TEXT PRIMARY KEY,

    facts_json TEXT NOT NULL DEFAULT '{}',

    answer TEXT NOT NULL,

    source_suggestion_id TEXT,

    actor TEXT NOT NULL DEFAULT 'system',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (source_suggestion_id)
        REFERENCES preference_suggestions (suggestion_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_preference_examples_answer
    ON preference_examples (answer);
