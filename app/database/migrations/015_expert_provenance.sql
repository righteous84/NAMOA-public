-- ==========================================================
-- NAMOA Migration 015
-- Expert Result Provenance
-- ==========================================================
--
-- Stores immutable snapshots produced by Experts during an
-- AnalysisRun.
--
-- Expert Results represent the interpretation of previously
-- collected evidence.
--
-- They answer:
--
--     "What conclusions did each Expert reach?"
--
-- DecisionSignals remain runtime-only and are intentionally
-- excluded from this migration.
--
-- ==========================================================


CREATE TABLE IF NOT EXISTS expert_results (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    analysis_run_id INTEGER NOT NULL,

    expert_name TEXT NOT NULL,

    confidence REAL NOT NULL,

    observations_json TEXT NOT NULL,

    notes TEXT NOT NULL,

    expert_data_json TEXT NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(analysis_run_id)
        REFERENCES analysis_runs(id)
        ON DELETE CASCADE
);



CREATE INDEX IF NOT EXISTS idx_expert_results_run

ON expert_results(
    analysis_run_id
);



CREATE INDEX IF NOT EXISTS idx_expert_results_expert

ON expert_results(
    expert_name
);