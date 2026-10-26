-- ==========================================================
-- NAMOA Migration 011
-- HDR Domain Knowledge
-- ==========================================================

INSERT INTO knowledge_sets (
    name,
    version,
    description
)
VALUES (
    'hdr',
    '1.0',
    'HDR interpretation knowledge'
);


INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'hdr',
    'HDR10',
    '{"type":"static_hdr","display_relevance":"high","confidence":0.95}'
FROM knowledge_sets
WHERE
    name='hdr'
    AND version='1.0';



INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'hdr',
    'DOLBY_VISION',
    '{"type":"dynamic_hdr","display_relevance":"high","confidence":0.95}'
FROM knowledge_sets
WHERE
    name='hdr'
    AND version='1.0';



INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'hdr',
    'HLG',
    '{"type":"broadcast_hdr","display_relevance":"medium","confidence":0.9}'
FROM knowledge_sets
WHERE
    name='hdr'
    AND version='1.0';



INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'hdr',
    'SDR',
    '{"type":"standard_dynamic_range","display_relevance":"low","confidence":0.95}'
FROM knowledge_sets
WHERE
    name='hdr'
    AND version='1.0';



INSERT INTO knowledge_entries (
    knowledge_set_id,
    domain,
    knowledge_key,
    value_json
)
SELECT
    id,
    'hdr',
    'UNKNOWN',
    '{"type":"unknown","display_relevance":"unknown","confidence":0.5}'
FROM knowledge_sets
WHERE
    name='hdr'
    AND version='1.0';