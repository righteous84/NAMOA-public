-- ==========================================================
-- NAMOA Migration 031
-- Persistent Notifications + Scan Progress
-- ==========================================================
--
-- GUI/UX Phase 4 + Phase 5 (Architect instruction
-- NAMOA_GUI_UX_Implementation.md).
--
-- 1. notifications
--    A separate presentation capability for user-facing
--    notifications. It is NOT the domain audit ledger: the
--    recommendation / organisation / execution event ledgers and
--    the media_executions state machine remain the immutable audit
--    record. Notifications are durable, user-facing messages that
--    persist until dismissed and are never read back into any
--    decision or state machine.
--
--    category semantics:
--        information  blue    informational events
--        success      green   approved / completed / saved
--        working      yellow  running / in progress
--        attention    orange  action required
--        error        red     failed
--        neutral      grey    file deleted / replaced (future
--                             lifecycle; reserved treatment)
--
--    reference links (all nullable, "as applicable"):
--        media_id            -> media_items
--        execution_job_id    -> media_executions
--        recommendation_id   -> recommendations
--        scan_id             -> scans
--
-- 2. scans.analysis_started_at
--    Records when the per-file analysis phase began (immediately
--    after filesystem discovery completes), so the GUI can derive
--    an honest approximate ETA from the observed per-file
--    processing rate during the analysis phase only. NULL while
--    discovery is still running.
-- ==========================================================

CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    category TEXT NOT NULL
        CHECK(category IN (
            'information',
            'success',
            'working',
            'attention',
            'error',
            'neutral'
        )),

    title TEXT NOT NULL,

    message TEXT,

    media_id INTEGER,
    execution_job_id INTEGER,
    recommendation_id INTEGER,
    scan_id INTEGER,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    dismissed_at DATETIME,

    FOREIGN KEY(media_id)
        REFERENCES media_items(id),

    FOREIGN KEY(execution_job_id)
        REFERENCES media_executions(id),

    FOREIGN KEY(recommendation_id)
        REFERENCES recommendations(id),

    FOREIGN KEY(scan_id)
        REFERENCES scans(id)
);

CREATE INDEX idx_notifications_active
    ON notifications (dismissed_at, created_at);

ALTER TABLE scans
    ADD COLUMN analysis_started_at DATETIME;