-- ==========================================================
-- NAMOA Migration 013
-- Source Domain Knowledge
-- ==========================================================

INSERT INTO knowledge_sets (
    name,
    version,
    description
)
VALUES (
    'source',
    '1.0',
    'Video source intelligence'
);

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'source',
    'WEB-DL',
    json('{
        "quality_rank":0.82,
        "lossless":false,
        "confidence":0.92
    }')
FROM knowledge_sets
WHERE name='source'
AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'source',
    'WEBRIP',
    json('{
        "quality_rank":0.70,
        "lossless":false,
        "confidence":0.85
    }')
FROM knowledge_sets
WHERE name='source'
AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'source',
    'BLURAY',
    json('{
        "quality_rank":0.95,
        "lossless":false,
        "confidence":0.96
    }')
FROM knowledge_sets
WHERE name='source'
AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'source',
    'REMUX',
    json('{
        "quality_rank":1.00,
        "lossless":true,
        "confidence":0.99
    }')
FROM knowledge_sets
WHERE name='source'
AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'source',
    'DVD',
    json('{
        "quality_rank":0.45,
        "lossless":false,
        "confidence":0.85
    }')
FROM knowledge_sets
WHERE name='source'
AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'source',
    'HDTV',
    json('{
        "quality_rank":0.55,
        "lossless":false,
        "confidence":0.82
    }')
FROM knowledge_sets
WHERE name='source'
AND version='1.0';