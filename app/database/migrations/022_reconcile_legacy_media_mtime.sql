-- ==========================================================
-- NAMOA Migration 022
-- Legacy Media Mtime Unknown Representation Reconciliation
-- ==========================================================
--
-- Purpose
-- -------
-- One-time historical data reconciliation for the WU-C
-- representation defect:
--
--     media_items.file_mtime_ns IS NULL
--         -> media_items.file_mtime_ns = 0
--
-- Background
-- ----------
--
-- Migration 018 added the nullable column
-- media_items.file_mtime_ns before the repository boundary
-- canonicalised unknown mtimes.
--
-- The canonical unknown-mtime representation is:
--
--     UNKNOWN_FILE_MTIME_NS = 0
--
-- as defined in app/database/repositories/media_repository.py,
-- which since Sprint 7 persists 0 identically to media_items and
-- file_observations and never writes NULL.
--
-- Historical rows written between migration 018 and that
-- correction can carry NULL on media_items while their same-
-- lineage observation records the identical scan event with the
-- canonical value 0. Under exact persisted-fingerprint
-- comparison in AnalysisValidityService this NULL-vs-0 drift
-- produces false no_current_observation / changed_media results.
--
-- Scope and guard
-- ---------------
--
-- Only rows satisfying ALL of the following are reconciled:
--
--     media_items.file_mtime_ns IS NULL
--     media_items.status = 'active'
--     a same-lineage file_observations row exists with
--         file_mtime_ns = 0
--         and size_bytes equal to the media row's
--         file_size_bytes
--
-- This is the qualification predicate established by the
-- Sprint 7 WU-C investigation. Rows without a confirming
-- zero-mtime observation are left untouched because their NULL
-- cannot be proven to represent the canonical unknown state.
--
-- Immutability
-- ------------
--
-- file_observations are immutable evidence and are NOT
-- rewritten by this migration; they are read only through the
-- EXISTS guard. Analysis runs, analysis results, provenance,
-- paths, sizes, statuses, identity and all other fields and
-- tables are untouched. Only the single field
-- media_items.file_mtime_ns changes, and only for qualifying
-- legacy rows.
--
-- Idempotency
-- -----------
--
-- The migration is naturally idempotent: after application no
-- qualifying NULL rows remain, so re-execution matches zero
-- rows. Application on an already-repaired database is a safe
-- no-op that restores migration-history continuity.
--
-- Historical Contract
-- -------------------
--
-- This is a one-time historical reconciliation. Future schema or
-- data evolution must occur through new migrations rather than
-- modifying this migration.
--
-- ==========================================================

UPDATE media_items
SET file_mtime_ns = 0
WHERE file_mtime_ns IS NULL
  AND status = 'active'
  AND EXISTS (
      SELECT 1
      FROM file_observations o
      WHERE o.media_id = media_items.id
        AND o.file_mtime_ns = 0
        AND o.size_bytes = media_items.file_size_bytes
  );
