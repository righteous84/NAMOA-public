-- ==========================================================
-- Migration 027
--
-- Sprint 14 correction:
-- Organisation execution scope claims (concurrency authority)
-- ==========================================================
--
-- Schema change rationale:
--
-- The pre-check concurrency model (query active executions before
-- mutating) is check-then-act and cannot prevent two independent
-- processes from both observing "no conflict" before either claims
-- the execution scope.
--
-- organisation_execution_scopes is the authoritative claim /
-- serialization boundary: an execution claims its source and
-- destination paths atomically in the same transaction that durably
-- persists the EXECUTING lifecycle state. UNIQUE(path) means a second
-- execution claiming an overlapping path fails atomically at the
-- database (IntegrityError) regardless of process interleaving.
--
-- Claims are held from EXECUTING until the execution reaches a
-- terminal state (SUCCEEDED / FAILED), at which point they are
-- released. A single path can therefore be claimed by at most one
-- active execution, which covers:
--
--   same source
--   same destination
--   overlapping source/destination scopes
--   duplicate execution of the same proposal (also enforced by the
--     organisation_executions.proposal_id UNIQUE constraint)
--   stale source state (still revalidated by execution-time
--     preconditions before claiming)
--
-- Rows are management records, not analytical history; they are
-- deleted when the execution becomes terminal.
-- ==========================================================

CREATE TABLE organisation_execution_scopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    execution_id INTEGER NOT NULL,

    path TEXT NOT NULL,

    role TEXT NOT NULL
        CHECK(role IN ('source', 'destination')),

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(path),

    FOREIGN KEY(execution_id)
        REFERENCES organisation_executions(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_org_execution_scopes_execution
    ON organisation_execution_scopes (execution_id);