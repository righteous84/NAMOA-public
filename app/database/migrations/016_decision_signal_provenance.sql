-- ==========================================================
-- NAMOA Migration 016
-- Decision Signal Provenance
-- ==========================================================

CREATE TABLE IF NOT EXISTS decision_signals (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    analysis_run_id INTEGER NOT NULL,

    rule_name TEXT NOT NULL,

    signal_type TEXT NOT NULL,

    opportunity_score REAL NOT NULL,

    confidence REAL NOT NULL,

    reasoning_json TEXT NOT NULL,

    signal_data_json TEXT NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(analysis_run_id)
        REFERENCES analysis_runs(id)
        ON DELETE CASCADE
);


CREATE INDEX IF NOT EXISTS idx_decision_signals_run
ON decision_signals(
    analysis_run_id
);


CREATE INDEX IF NOT EXISTS idx_decision_signals_rule
ON decision_signals(
    rule_name
);