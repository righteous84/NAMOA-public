-- ==========================================================
-- Migration 035
--
-- Phase 11: User Policy and Preferences
--
-- Durable user policy profile history and standing-decision
-- state/history.
--
-- These tables store user decisions as durable application
-- facts. They do not alter analytical results, currentness,
-- approval, or execution authority.
--
-- Policy profiles are append-only snapshots. The newest row
-- for the single current profile is the effective profile.
-- A new row is written for every profile change, including
-- an explicit restoration of defaults.
--
-- Standing decisions are durable per-lineage/per-proposition
-- decisions. The current row is mutable state while the
-- append-only event ledger preserves every refusal/revocation.
-- ==========================================================


-- ----------------------------------------------------------
-- Durable user policy profiles
-- ----------------------------------------------------------

CREATE TABLE user_policy_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    policy_json TEXT NOT NULL,

    semantic_version TEXT NOT NULL,

    actor TEXT NOT NULL,

    reason TEXT,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_policy_profiles_created
    ON user_policy_profiles (created_at, id);


-- ----------------------------------------------------------
-- Standing decisions
--
-- One current decision per lineage + proposition.
-- A refusal suppresses re-presentation.
-- A revocation restores presentation.
-- ----------------------------------------------------------

CREATE TABLE standing_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    media_id INTEGER NOT NULL,

    proposition TEXT NOT NULL,

    state TEXT NOT NULL
        CHECK (state IN (
            'refused',
            'revoked'
        )),

    actor TEXT NOT NULL,

    reason TEXT,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (media_id)
        REFERENCES media_items(id),

    UNIQUE (media_id, proposition)
);

CREATE INDEX idx_standing_decisions_media
    ON standing_decisions (media_id);

CREATE INDEX idx_standing_decisions_state
    ON standing_decisions (state);


-- ----------------------------------------------------------
-- Standing-decision provenance
--
-- Append-only history. The current standing_decisions row is
-- the presentation-state read model; this ledger is the
-- immutable history of every user action.
-- ----------------------------------------------------------

CREATE TABLE standing_decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    standing_decision_id INTEGER NOT NULL,

    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'refused',
            'revoked'
        )),

    actor TEXT NOT NULL,

    reason TEXT,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (standing_decision_id)
        REFERENCES standing_decisions(id)
);


CREATE INDEX idx_standing_decision_events_decision
    ON standing_decision_events (standing_decision_id);

CREATE INDEX idx_standing_decision_events_created
    ON standing_decision_events (created_at, id);