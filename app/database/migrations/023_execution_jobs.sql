-- ==========================================================
-- Migration 023
--
-- Execution Jobs (Sprint 9 Execution Engine)
--
-- media_executions records the full execution lifecycle for
-- explicitly approved optimisations:
--
--   approved -> planned -> running -> verifying -> replacing
--       -> succeeded
--
-- with honest failure/interrupt states:
--
--   failed_execution      FFmpeg failed; original untouched
--   failed_verification   output invalid; original untouched
--   failed_replacement    replacement failed; original restored
--   interrupted           process died mid-sequence; recoverable
--   rolled_back           succeeded job reverted to original bytes
--   recovered             interruption resolved by recovery
--
-- Persistence is justified by correctness and safety requirements:
-- approvals must be inspectable/attributable across processes, an
-- interrupted replacement must be detectable and recoverable, and
-- execution history must be preserved. This table adds no analysis
-- semantics and never rewrites historical provenance.
--
-- plan_json / policy_json are immutable snapshots of what was
-- approved and what the policy decision permitted.
--
-- source_sha256 records the approved original content for
-- execution-specific integrity: recovery classifies filesystem
-- reality against it, and destructive rollback refuses when the
-- live result no longer matches this execution. It is NOT a media
-- currentness authority; canonical currentness remains the existing
-- size+mtime fingerprint model owned by AnalysisValidityService.
-- ==========================================================

CREATE TABLE media_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    media_id INTEGER NOT NULL,
    opportunity TEXT,
    analysis_run_id INTEGER,

    source_path TEXT NOT NULL,
    source_size_bytes INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    source_inode INTEGER,
    source_sha256 TEXT,

    approved_by TEXT NOT NULL DEFAULT 'human',
    approved_at TEXT NOT NULL,

    plan_json TEXT,
    policy_json TEXT,

    state TEXT NOT NULL DEFAULT 'approved',

    temp_output_path TEXT,
    backup_path TEXT,
    output_sha256 TEXT,
    result_observation_id INTEGER,

    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_media_executions_media_id
    ON media_executions (media_id);

CREATE INDEX idx_media_executions_state
    ON media_executions (state);
