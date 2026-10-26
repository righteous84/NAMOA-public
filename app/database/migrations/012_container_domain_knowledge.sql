-- ==========================================================
-- NAMOA Migration 012
-- Container Domain Knowledge
-- ==========================================================
--
-- Purpose:
-- Adds versioned container interpretation knowledge.
--
-- Experts consume this through KnowledgeService.
-- Optimisation decisions belong in ContainerRule.
--
-- ==========================================================

INSERT INTO knowledge_sets (
    name,
    version,
    description
)
VALUES (
    'container',
    '1.0',
    'Container interpretation knowledge'
);


------------------------------------------------------------
-- MATROSKA
------------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'container',
    'MATROSKA',
    '{
        "supports_multiple_audio": true,
        "supports_multiple_subtitles": true,
        "streaming_friendly": false,
        "remux_friendly": true,
        "confidence": 0.95
    }'
FROM knowledge_sets
WHERE
    name='container'
    AND version='1.0';


------------------------------------------------------------
-- MP4
------------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'container',
    'MP4',
    '{
        "supports_multiple_audio": true,
        "supports_multiple_subtitles": false,
        "streaming_friendly": true,
        "remux_friendly": true,
        "confidence": 0.95
    }'
FROM knowledge_sets
WHERE
    name='container'
    AND version='1.0';


------------------------------------------------------------
-- AVI
------------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'container',
    'AVI',
    '{
        "supports_multiple_audio": false,
        "supports_multiple_subtitles": false,
        "streaming_friendly": false,
        "remux_friendly": false,
        "confidence": 0.90
    }'
FROM knowledge_sets
WHERE
    name='container'
    AND version='1.0';


------------------------------------------------------------
-- MPEGTS
------------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'container',
    'MPEGTS',
    '{
        "supports_multiple_audio": true,
        "supports_multiple_subtitles": false,
        "streaming_friendly": true,
        "remux_friendly": true,
        "confidence": 0.90
    }'
FROM knowledge_sets
WHERE
    name='container'
    AND version='1.0';


------------------------------------------------------------
-- UNKNOWN
------------------------------------------------------------

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'container',
    'UNKNOWN',
    '{
        "confidence": 0.50
    }'
FROM knowledge_sets
WHERE
    name='container'
    AND version='1.0';