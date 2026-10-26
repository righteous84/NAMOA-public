-- ==========================================================
-- Securestack Media Optimizer
-- Migration 001 - Initial Schema
-- ==========================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------
-- Migration tracking table
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_name TEXT NOT NULL UNIQUE,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------
-- Media items (core library)
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,

    file_size_bytes INTEGER NOT NULL,
    duration_seconds REAL,

    media_type TEXT CHECK(media_type IN ('movie', 'episode', 'unknown')) DEFAULT 'unknown',

    last_modified DATETIME,
    sha256_hash TEXT,
    last_scanned_at DATETIME,

    status TEXT CHECK(status IN ('active', 'missing', 'excluded', 'processing')) DEFAULT 'active',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------
-- Streams (video/audio/subtitle tracks)
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,

    stream_type TEXT CHECK(stream_type IN ('video', 'audio', 'subtitle', 'attachment')),

    codec TEXT,
    language TEXT,

    width INTEGER,
    height INTEGER,

    bitrate INTEGER,
    channels INTEGER,

    hdr_format TEXT,

    FOREIGN KEY(media_id) REFERENCES media_items(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Analysis results
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,

    container TEXT,
    overall_bitrate INTEGER,

    resolution TEXT,
    is_hdr INTEGER DEFAULT 0,

    efficiency_score REAL,
    quality_flags TEXT,

    analysed_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id) REFERENCES media_items(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Recommendations engine output
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,

    recommendation_type TEXT,

    target_resolution TEXT,
    target_codec TEXT,

    expected_size_bytes INTEGER,
    expected_savings_bytes INTEGER,

    confidence REAL,
    reason TEXT,

    status TEXT DEFAULT 'pending',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id) REFERENCES media_items(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Tag system (future-proofing for genres/categories)
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS media_tags (
    media_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,

    PRIMARY KEY (media_id, tag_id),

    FOREIGN KEY(media_id) REFERENCES media_items(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
