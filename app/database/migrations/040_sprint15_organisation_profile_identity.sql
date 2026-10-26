-- 040_sprint15_organisation_profile_identity.sql
--
-- Sprint 15 correction: an organisation profile is one
-- saved configuration, not a version-management
-- system. The profile name is the unique identity;
-- editing a profile updates its single stored row.
--
-- This rebuilds organisation_profiles keeping the
-- latest row per name (original ids preserved, so
-- existing decision-run profile_id references keep
-- their meaning alongside the stored digest), drops
-- the version column nothing consumes, and enforces
-- UNIQUE(name) so the same name can never appear
-- twice in the profile list.

CREATE TABLE organisation_profiles_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL UNIQUE,

    payload_json TEXT NOT NULL DEFAULT '{}',

    digest TEXT NOT NULL DEFAULT '',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO organisation_profiles_new (
    id,
    name,
    payload_json,
    digest,
    created_at,
    updated_at
)
SELECT
    id,
    name,
    payload_json,
    digest,
    created_at,
    updated_at
FROM organisation_profiles
WHERE id IN (
    SELECT MAX(id)
    FROM organisation_profiles
    GROUP BY name
);

DROP TABLE organisation_profiles;

ALTER TABLE organisation_profiles_new
    RENAME TO organisation_profiles;
