-- ==========================================================
-- Migration 032
--
-- Phase 6 Execution: requested transformation + result
--
-- Extends media_executions with the immutable requested
-- transformation (what the user approved), the predicted result
-- (what NAMOA expected before execution) and the measured result
-- (what actually happened), plus the structured verification
-- detail. These are all additive nullable JSON snapshots:
--
--   requested_transformation_json
--       What the user actually approved, distinct from the
--       recommendation that caused the approval and from the
--       execution plan generated from it.
--
--   predicted_json
--       Transformation-aware predicted savings (never the old
--       score*50 shortcut).
--
--   measured_json
--       Measured savings derived from the actual source and
--       result observations after successful verified
--       replacement.
--
--   verification_json
--       Structured operation-aware verification outcome (the
--       expectations that were checked and the resulting facts).
--
-- Historical rows remain valid: every column is nullable and no
-- existing data is touched.
-- ==========================================================

ALTER TABLE media_executions
    ADD COLUMN requested_transformation_json TEXT;

ALTER TABLE media_executions
    ADD COLUMN predicted_json TEXT;

ALTER TABLE media_executions
    ADD COLUMN measured_json TEXT;

ALTER TABLE media_executions
    ADD COLUMN verification_json TEXT;