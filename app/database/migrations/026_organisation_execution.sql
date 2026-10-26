-- ==========================================================
-- Migration 026
--
-- Sprint 14: Library Organisation Execution & Safety
-- ==========================================================
--
-- Schema change rationale:
--
-- Organisation execution is a SEPARATE execution domain from
-- optimisation execution. It consumes an already-approved
-- organisation proposal (Sprint 13) and performs a safe,
-- deterministic move / rename of the authorised source to the
-- validated destination, then verifies, records a new filesystem
-- observation for the SAME media identity, establishes explicit
-- execution-authorised identity continuity, and persists the
-- execution record as the authoritative history of the filesystem
-- operation.
--
-- It deliberately does NOT reuse the optimisation `media_executions`
-- table: that table's plan/FFmpeg/replacement/rollback vocabulary is
-- optimisation-specific and is semantically inappropriate for a
-- move/rename. Reusing the existing execution REPOSITORY pattern
-- (durable row + append-only event ledger) while keeping
-- organisation-specific operation semantics is exactly the
-- Architect-approved boundary.
--
-- 1. organisation_executions
--    The durable execution lifecycle record for one approved
--    organisation proposal. proposal_id is UNIQUE so the same
--    approved proposal can never be executed more than once
--    (idempotency / duplicate-execution protection at the
--    persistence boundary). It snapshots the authoritative
--    source observation context and the intended destination.
--
-- 2. organisation_execution_events
--    Append-only lifecycle ledger over executions. Rows are never
--    updated or deleted.
--
-- 3. organisation_execution_continuity
--    The explicit execution-authorised identity-continuity record:
--    the resulting observation (O2) is declared continuous with the
--    source observation (O1) of the SAME media identity, and the
--    authority for that continuity is this organisation execution.
--    This is a narrow, execution-scoped linkage; normal scanning
--    and duplicate detection never create or recreate it.
--
-- No historical data is backfilled: organisation execution history
-- begins with the first Sprint 14 execution.
-- ==========================================================

CREATE TABLE organisation_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    proposal_id INTEGER NOT NULL UNIQUE,

    decision_run_id INTEGER NOT NULL,

    media_id INTEGER NOT NULL,

    intent TEXT NOT NULL,

    source_path TEXT NOT NULL,

    source_observation_id INTEGER,

    source_size_bytes INTEGER,

    source_mtime_ns INTEGER,

    destination_path TEXT NOT NULL,

    state TEXT NOT NULL DEFAULT 'proposed'
        CHECK(state IN (
            'proposed',
            'approved',
            'precondition_verified',
            'executing',
            'verifying',
            'observation_persistence',
            'provenance_persistence',
            'succeeded',
            'failed',
            'interrupted',
            'recovery_required'
        )),

    error TEXT,

    result_observation_id INTEGER,

    continuity_id INTEGER,

    actor TEXT NOT NULL DEFAULT 'human',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(proposal_id)
        REFERENCES organisation_proposals(id),

    FOREIGN KEY(decision_run_id)
        REFERENCES organisation_decision_runs(id),

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_org_executions_proposal
    ON organisation_executions (proposal_id);

CREATE INDEX idx_org_executions_media
    ON organisation_executions (media_id);

CREATE INDEX idx_org_executions_state
    ON organisation_executions (state);

CREATE INDEX idx_org_executions_source
    ON organisation_executions (source_path);

CREATE INDEX idx_org_executions_destination
    ON organisation_executions (destination_path);

CREATE TABLE organisation_execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    execution_id INTEGER NOT NULL,

    event_type TEXT NOT NULL,

    previous_state TEXT,

    new_state TEXT,

    actor TEXT NOT NULL DEFAULT 'system',

    detail TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(execution_id)
        REFERENCES organisation_executions(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_org_execution_events_execution
    ON organisation_execution_events (execution_id);

CREATE TABLE organisation_execution_continuity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    execution_id INTEGER NOT NULL,

    media_id INTEGER NOT NULL,

    source_observation_id INTEGER NOT NULL,

    result_observation_id INTEGER NOT NULL,

    authority TEXT NOT NULL DEFAULT 'organisation_execution',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(execution_id)
        REFERENCES organisation_executions(id)
        ON DELETE CASCADE,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id)
        ON DELETE CASCADE,

    FOREIGN KEY(source_observation_id)
        REFERENCES file_observations(id),

    FOREIGN KEY(result_observation_id)
        REFERENCES file_observations(id)
);

CREATE INDEX idx_org_execution_continuity_execution
    ON organisation_execution_continuity (execution_id);

CREATE INDEX idx_org_execution_continuity_media
    ON organisation_execution_continuity (media_id);
