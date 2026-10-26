-- ==========================================================
-- NAMOA Migration 010
-- Video Domain Knowledge
-- ==========================================================
--
-- Purpose:
-- Adds versioned resolution intelligence.
--
-- Experts consume this through KnowledgeService.
-- No optimisation decisions belong here.
--
-- ==========================================================


INSERT INTO knowledge_sets (
    name,
    version,
    description
)
VALUES (
    'resolution',
    '1.0',
    'Video resolution classification knowledge'
);



-- ----------------------------------------------------------
-- Resolution Knowledge
--
-- Domain:
--     resolution
--
-- Keys:
--     2160p
--     1080p
--     720p
--     480p
--
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
    AND version = '1.0';



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
    AND version = '1.0';



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
    AND version = '1.0';



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
    AND version = '1.0';