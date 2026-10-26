CREATE TABLE IF NOT EXISTS media_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,

    duration REAL,
    bitrate INTEGER,
    resolution TEXT,
    video_codec TEXT,
    audio_tracks INTEGER,

    analysed_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(media_id) REFERENCES media_items(id) ON DELETE CASCADE
);
