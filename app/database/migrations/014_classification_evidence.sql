-- ==========================================================
-- NAMOA Migration 014
-- Classification Evidence Provenance
-- ==========================================================
--
-- Stores every piece of evidence generated during an
-- AnalysisRun.
--
-- Evidence is not intelligence.
--
-- It records:
--
--   "What did the system observe?"
--
-- Interpretation remains owned by Experts.
--
-- ==========================================================


CREATE TABLE IF NOT EXISTS classification_evidence (

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
);



CREATE INDEX IF NOT EXISTS idx_classification_evidence_run

ON classification_evidence(
    analysis_run_id
);



CREATE INDEX IF NOT EXISTS idx_classification_evidence_domain

ON classification_evidence(
    domain
);