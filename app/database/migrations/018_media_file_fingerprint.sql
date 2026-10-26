-- ==========================================================
-- NAMOA Migration 018
-- Media File State Fingerprint
-- ==========================================================
--
-- Adds the filesystem modification timestamp to the persisted
-- media state and to every provenance InputSnapshot.
--
-- File identity/change detection now uses:
--
--     size_bytes
--     file_mtime_ns
--
-- This allows NAMOA to detect files whose contents/state changed
-- without relying on file size alone.
--
-- SHA-256 hashing is intentionally not introduced here.
-- ==========================================================


ALTER TABLE media_items
ADD COLUMN file_mtime_ns INTEGER;


ALTER TABLE input_snapshots
ADD COLUMN file_mtime_ns INTEGER;