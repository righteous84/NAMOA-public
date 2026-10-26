-- ==========================================================
-- NAMOA Migration 005
-- Opportunity Assessment Persistence
-- ==========================================================

CREATE TABLE IF NOT EXISTS opportunity_assessments (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    media_id INTEGER NOT NULL,

    opportunity TEXT NOT NULL,

    score REAL NOT NULL DEFAULT 0.0,

    confidence REAL NOT NULL DEFAULT 0.0,

    estimated_saving_percent REAL NOT NULL DEFAULT 0.0,

    risk TEXT DEFAULT 'unknown',

    evidence_json TEXT,

    reasoning_json TEXT,

    contributing_rules_json TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE
);