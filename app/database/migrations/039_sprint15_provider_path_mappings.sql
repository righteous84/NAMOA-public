-- ==========================================================
-- Migration 039
--
-- Sprint 15 final correction: explicit provider-root to
-- local-root mappings for metadata association.
-- ==========================================================
--
-- Background:
--
-- Provider libraries (Radarr, Sonarr, Jellyfin) report
-- paths in the provider container namespace (for example
-- /Movies/Sing (2016)/Sing.2016.mkv) while NAMOA lineages
-- live in the host namespace (for example
-- /mnt/media_drv1/Movies/Sing (2016)/...mkv). Exact
-- canonical paths therefore never agree, and global
-- identical-tail suffix matching is unsafe (it guesses
-- across unrelated roots such as Movies vs Movies-KIDS).
--
-- This standalone table records explicit, reviewable,
-- per-provider root relationships:
--
--     provider root /Movies
--     local root    /mnt/media_drv1/Movies
--
-- so /Movies/Sing (2016)/Sing.2016.mkv maps
-- deterministically to
-- /mnt/media_drv1/Movies/Sing (2016)/Sing.2016.mkv
-- only because the relationship is known. One provider
-- root may map to several local roots (multiple
-- drives); matching then requires exactly one lineage
-- hit across all mapped candidates, and several hits
-- stay needs-review instead of a guess.
--
-- No foreign keys; touches no existing table; applies
-- cleanly on fresh and legacy databases.
-- ==========================================================

CREATE TABLE IF NOT EXISTS provider_path_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    provider TEXT NOT NULL
        CHECK(provider IN (
            'jellyfin',
            'radarr',
            'sonarr'
        )),

    provider_root TEXT NOT NULL,

    local_root TEXT NOT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- One provider root may map onto several local roots
-- (several drives holding the same library split). The
-- pair is unique; matching requires exactly one lineage
-- hit across all mapped candidates, and several hits
-- stay needs-review instead of a guess.
CREATE UNIQUE INDEX IF NOT EXISTS
    idx_provider_path_mappings_unique
    ON provider_path_mappings (
        provider, provider_root, local_root
    );

CREATE INDEX IF NOT EXISTS
    idx_provider_path_mappings_provider
    ON provider_path_mappings (provider);
