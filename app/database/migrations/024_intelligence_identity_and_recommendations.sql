-- ==========================================================
-- Migration 024
--
-- Sprint 10 Correction:
-- Intelligence Identity + Recommendation Persistence/Lifecycle
--
-- 1. analysis_runs.intelligence_identity
--    The deterministic sha256 digest of the canonical intelligence
--    identity (component versions, policy values incl. active
--    evidence weighting, and consulted knowledge-set versions).
--    Written at begin_run for every NEW run.
--
--    Historical rows keep NULL: development-era runs are immutable
--    history and are NOT backfilled or fabricated. A NULL identity is
--    treated by applicability evaluation as "identity unrecorded"
--    (not reusable), which honestly reflects that its producing
--    intelligence cannot be established.
--
-- 2. recommendations
--    Durable historical recommendation records produced by analysis
--    runs, replacing the legacy dead table of the same name
--    (0 rows, no code references anywhere in the repository;
--    superseded since Sprint 7 by opportunity_assessments plus the
--    derived prioritisation layer). Retirement is documented here as
--    required before replacement.
--
--    The row preserves the result AS PRODUCED BY THE RUN: analytical
--    fields, rationale, contributing rules, risk, and the producing
--    run/observation/media identities plus the run's intelligence
--    identity digest. Priority/ranking fields are frozen onto the row
--    when a presentation snapshot exists (acceptance freezes what was
--    shown); they are nullable because ranking is a cross-lineage
--    read-layer concept, not a per-run analytical fact.
--
-- 3. recommendation_events
--    Append-only lifecycle ledger. Human decisions (accepted,
--    rejected) and system mirrors of execution state are recorded as
--    historical events; rows are never updated or deleted.
--
-- 4. media_executions.recommendation_id
--    Durable link from an execution job to the recommendation that
--    was accepted. Execution state remains the single execution
--    authority; the recommendation carries a mirror kept current only
--    by ExecutionService at job transition points.
-- ==========================================================

ALTER TABLE analysis_runs
    ADD COLUMN intelligence_identity TEXT;

DROP TABLE IF EXISTS recommendations;

CREATE TABLE recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    media_id INTEGER NOT NULL,
    analysis_run_id INTEGER NOT NULL,
    file_observation_id INTEGER,

    opportunity TEXT NOT NULL,

    opportunity_score REAL,
    confidence REAL,
    estimated_saving_percent REAL,
    estimated_saved_bytes INTEGER,
    risk TEXT,

    priority_score REAL,
    rank_at_presentation INTEGER,
    components_json TEXT,
    rationale_json TEXT,
    contributing_rules_json TEXT,

    intelligence_identity TEXT,

    state TEXT NOT NULL DEFAULT 'proposed'
        CHECK(state IN (
            'proposed',
            'accepted',
            'rejected',
            'queued',
            'executing',
            'completed',
            'failed'
        )),

    execution_job_id INTEGER,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE,

    FOREIGN KEY(analysis_run_id)
        REFERENCES analysis_runs(id)
);

CREATE INDEX idx_recommendations_media
    ON recommendations (media_id);

CREATE INDEX idx_recommendations_run
    ON recommendations (analysis_run_id);

CREATE INDEX idx_recommendations_state
    ON recommendations (state);

CREATE TABLE recommendation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    recommendation_id INTEGER NOT NULL,

    event_type TEXT NOT NULL
        CHECK(event_type IN (
            'proposed',
            'accepted',
            'rejected',
            'queued',
            'state_changed',
            'superseded'
        )),

    previous_state TEXT,
    new_state TEXT,

    execution_job_id INTEGER,

    actor TEXT NOT NULL DEFAULT 'system',

    detail TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(recommendation_id)
        REFERENCES recommendations(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_recommendation_events_recommendation
    ON recommendation_events (recommendation_id);

ALTER TABLE media_executions
    ADD COLUMN recommendation_id INTEGER;
