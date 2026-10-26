-- ==========================================================
-- Migration 029
--
-- Opportunity assessment and recommendation semantics columns
--
-- Extends the persisted analytical output with the structured
-- semantics introduced by the intelligence relationship work:
--
--   opportunity_assessments
--       opportunity_level        none / weak / meaningful / strong
--       priority_label           human-facing label
--       expected_saved_bytes     absolute expected storage saving
--       benefit                  benefit category
--       cost                     cost category
--       preservation_reasons_json  structured reasons not to optimise
--       suppressed_signals_json    signals suppressed by fusion and why
--
--   recommendations
--       opportunity_level        level carried from the assessment
--       summary                  one-line human-readable summary
--
-- New columns are nullable so historical rows remain valid and are
-- never backfilled or rewritten. NULL opportunity_level on a
-- historical row means "opportunity level not recorded by that
-- run's intelligence", mirroring the existing NULL
-- intelligence_identity semantics.
-- ==========================================================

ALTER TABLE opportunity_assessments
    ADD COLUMN opportunity_level TEXT;

ALTER TABLE opportunity_assessments
    ADD COLUMN priority_label TEXT;

ALTER TABLE opportunity_assessments
    ADD COLUMN expected_saved_bytes INTEGER;

ALTER TABLE opportunity_assessments
    ADD COLUMN benefit TEXT;

ALTER TABLE opportunity_assessments
    ADD COLUMN cost TEXT;

ALTER TABLE opportunity_assessments
    ADD COLUMN preservation_reasons_json TEXT;

ALTER TABLE opportunity_assessments
    ADD COLUMN suppressed_signals_json TEXT;

ALTER TABLE recommendations
    ADD COLUMN opportunity_level TEXT;

ALTER TABLE recommendations
    ADD COLUMN summary TEXT;