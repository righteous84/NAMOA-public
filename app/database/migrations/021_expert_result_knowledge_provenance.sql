-- ==========================================================
-- Migration 021
--
-- Adds per-Expert knowledge provenance.
--
-- analysis_run_knowledge answers:
--   "Which knowledge sets did this analysis run use?"
--
-- expert_results.knowledge_set_ids_json answers:
--   "Which knowledge sets did this Expert use?"
--
-- The latter is stored as an immutable JSON snapshot because
-- expert_results are provenance records.
-- ==========================================================

ALTER TABLE expert_results
ADD COLUMN knowledge_set_ids_json TEXT NOT NULL DEFAULT '[]';
