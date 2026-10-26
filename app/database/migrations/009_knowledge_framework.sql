-- ==========================================================
-- NAMOA Migration 009
-- Knowledge Framework Foundation
-- ==========================================================
--
-- Purpose
-- -------
-- Introduces the versioned Knowledge Framework.
--
-- Knowledge is an independent intelligence layer consumed
-- by Experts through KnowledgeService.
--
-- Knowledge is append-only:
--
--   - existing knowledge versions are never modified
--   - new knowledge creates new versions
--   - historical AnalysisRuns record the knowledge versions
--     used during execution
--
-- ----------------------------------------------------------
-- Schema Changes
-- ----------------------------------------------------------
--
-- knowledge_sets
--
-- Defines versioned collections of knowledge.
--
-- knowledge_entries
--
-- Stores individual knowledge items belonging to a
-- knowledge set.
--
-- analysis_run_knowledge
--
-- Links AnalysisRuns to the knowledge versions used.
--
-- ----------------------------------------------------------
-- Provenance Contract
-- ----------------------------------------------------------
--
-- An AnalysisRun can now permanently identify:
--
--   Configuration Snapshot
--   Input Snapshot
--   Knowledge Versions
--   Expert Outputs
--   Opportunity Assessment
--
-- ----------------------------------------------------------
-- Design Notes
-- ----------------------------------------------------------
--
-- Knowledge payloads are stored generically as JSON.
--
-- Domain-specific interpretation belongs in Experts,
-- not in this schema.
--
-- Examples:
--
--   domain:
--       video_codec
--
--   key:
--       HEVC
--
--   value:
--       {
--          "efficiency_rating": 0.85
--       }
--
-- Future domains:
--
--   audio
--   container
--   storage
--   hardware
--
-- ----------------------------------------------------------


-- ----------------------------------------------------------
-- Knowledge Sets
--
-- Represents a versioned knowledge package.
--
-- New versions create new rows.
-- Existing rows are historical records.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_sets (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,

    version TEXT NOT NULL,

    description TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(name, version)
);


-- ----------------------------------------------------------
-- Knowledge Entries
--
-- Individual knowledge records belonging to a knowledge set.
--
-- JSON payload keeps the schema generic and prevents domain
-- coupling inside the database layer.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_entries (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    knowledge_set_id INTEGER NOT NULL,

    domain TEXT NOT NULL,

    knowledge_key TEXT NOT NULL,

    value_json TEXT NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(knowledge_set_id)
        REFERENCES knowledge_sets(id)
        ON DELETE CASCADE,

    UNIQUE(
        knowledge_set_id,
        domain,
        knowledge_key
    )
);


-- ----------------------------------------------------------
-- Analysis Run Knowledge
--
-- Provenance link between an AnalysisRun and the knowledge
-- versions consulted during execution.
--
-- This table is append-only.
--
-- It allows historical reproduction:
--
-- "Which knowledge did this analysis use?"
--
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis_run_knowledge (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    analysis_run_id INTEGER NOT NULL,

    knowledge_set_id INTEGER NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(analysis_run_id)
        REFERENCES analysis_runs(id)
        ON DELETE CASCADE,

    FOREIGN KEY(knowledge_set_id)
        REFERENCES knowledge_sets(id)
);


-- ----------------------------------------------------------
-- Indexes
--
-- Expected access patterns:
--
--   - retrieve knowledge entries by domain/key
--   - retrieve knowledge used by an analysis run
-- ----------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_knowledge_entries_lookup

    ON knowledge_entries(
        domain,
        knowledge_key
    );


CREATE INDEX IF NOT EXISTS idx_analysis_run_knowledge_run

    ON analysis_run_knowledge(
        analysis_run_id
    );