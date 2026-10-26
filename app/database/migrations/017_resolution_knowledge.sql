-- ==========================================================
-- NAMOA Migration 017
-- Resolution Knowledge v2
-- ==========================================================
--
-- Purpose:
-- Introduces the next version of resolution-domain knowledge
-- following the provenance architecture established in
-- migrations 014-016.
--
-- Knowledge is append-only:
--
--   resolution 1.0 = migration 010
--   resolution 2.0 = migration 017
--
-- Historical AnalysisRuns retain the knowledge-set version
-- they actually consulted.
--
-- Experts consume this through KnowledgeService.
-- Optimisation decisions do not belong in this migration.
--
-- ==========================================================


INSERT INTO knowledge_sets (
    name,
    version,
    description
)
VALUES (
    'resolution',
    '2.0',
    'Version 2 resolution classification knowledge'
);


-- ----------------------------------------------------------
-- 2160p
-- ----------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'resolution',
    '2160p',
    '{
        "category": "ultra_hd",
        "storage_factor": 4,
        "display_relevance": "high",
        "confidence": 0.95
    }'
FROM knowledge_sets
WHERE
    name = 'resolution'
    AND version = '2.0';


-- ----------------------------------------------------------
-- 1080p
-- ----------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'resolution',
    '1080p',
    '{
        "category": "full_hd",
        "storage_factor": 2,
        "display_relevance": "high",
        "confidence": 0.95
    }'
FROM knowledge_sets
WHERE
    name = 'resolution'
    AND version = '2.0';


-- ----------------------------------------------------------
-- 720p
-- ----------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'resolution',
    '720p',
    '{
        "category": "hd",
        "storage_factor": 1,
        "display_relevance": "medium",
        "confidence": 0.90
    }'
FROM knowledge_sets
WHERE
    name = 'resolution'
    AND version = '2.0';


-- ----------------------------------------------------------
-- 480p
-- ----------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'resolution',
    '480p',
    '{
        "category": "sd",
        "storage_factor": 0.5,
        "display_relevance": "low",
        "confidence": 0.90
    }'
FROM knowledge_sets
WHERE
    name = 'resolution'
    AND version = '2.0';