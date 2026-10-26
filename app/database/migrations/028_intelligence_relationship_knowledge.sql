-- ==========================================================
-- Migration 028
--
-- Intelligence relationship knowledge
--
-- Adds maintained, versioned semantic meaning used by the
-- Decision Rules to determine whether an optimisation is
-- worthwhile, rather than treating each property independently.
--
-- Knowledge versions are immutable. Every set below is created as a
-- NEW set (or new version) so previous knowledge versions remain
-- preserved and attributable.
--
-- Sets introduced:
--
--   video_codec            v1.0  (consumed by CodecExpert and
--                                 CodecRule)
--   audio                  v1.0  (consumed by AudioExpert and
--                                 AudioRule)
--   codec_efficiency       v1.0  (codec conversion relationships,
--                                 consumed by CodecRule)
--   audio_efficiency       v1.0  (audio conversion relationships,
--                                 consumed by AudioRule)
--   bitrate_suitability    v1.0  (expected bitrate ranges by
--                                 codec/resolution, consumed by
--                                 BitrateRule)
--
-- Semantic definitions (documented meaning of every value):
--
--   compression_efficiency
--       Relative video storage footprint at comparable quality,
--       where H.264 = 1.0. Below 1.0 = more efficient (less
--       storage); above 1.0 = less efficient (more storage). A
--       relative comparison aid, not an absolute quality measure.
--
--   efficient_targets
--       Codec(s) that could provide materially better compression
--       efficiency for the current codec. An empty list means no
--       codec-conversion proposition is defensible.
--
--   lossless
--       Whether the audio representation is mathematically lossless
--       (true), lossy (false), or unknown (null).
--
--   storage_footprint
--       Relative audio-track storage footprint category
--       (low / moderate / high).
--
--   efficient_lossy_target
--       The efficient lossy audio codec that a conversion could
--       target, or null when no conversion proposition is
--       defensible.
--
--   expected_storage_reduction
--       Category of expected storage reduction (small / moderate /
--       substantial) for the conversion relationship.
--
--   storage_reduction_low / storage_reduction_high
--       A RANGE (fraction, 0-1) bounding the expected reduction.
--       A range, not a false precision.
--
--   quality_risk
--       Expected quality risk of the transformation
--       (low / medium / high).
--
--   encoding_cost
--       Expected computational cost of the transformation
--       (low / moderate / high).
--
--   typical_bitrate_bps
--       Typical good-quality bitrate for the codec and resolution.
--
--   excess_reference_bps
--       Bitrate above which excess bitrate is indicated (materially
--       higher than necessary for the represented quality).
--
--   justified_high_bitrate_bps
--       Bitrate that could be justified by a high-value source or
--       deliberate quality intent; above this, reduction would
--       require substantial justification.
-- ==========================================================


-- ----------------------------------------------------------
-- video_codec v1.0
-- ----------------------------------------------------------

INSERT INTO knowledge_sets (name, version, description)
VALUES ('video_codec', '1.0', 'Video codec efficiency intelligence');

-- H264
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'H264', json('{
    "family": "avc",
    "generation": "modern",
    "compression_efficiency": 1.0,
    "efficient_targets": ["HEVC"],
    "notes": "H.264 (AVC). HEVC conversion may improve compression efficiency.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- HEVC
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'HEVC', json('{
    "family": "hevc",
    "generation": "modern",
    "compression_efficiency": 0.55,
    "efficient_targets": [],
    "notes": "HEVC (H.265). Already an efficient modern codec; no codec conversion opportunity.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- VP9
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'VP9', json('{
    "family": "vp9",
    "generation": "modern",
    "compression_efficiency": 0.60,
    "efficient_targets": ["AV1"],
    "notes": "VP9. AV1 may offer further compression efficiency.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- AV1
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'AV1', json('{
    "family": "av1",
    "generation": "modern",
    "compression_efficiency": 0.50,
    "efficient_targets": [],
    "notes": "AV1. State-of-the-art efficiency; no codec conversion opportunity.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- MPEG4
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'MPEG4', json('{
    "family": "mpeg4",
    "generation": "legacy",
    "compression_efficiency": 1.8,
    "efficient_targets": ["HEVC"],
    "notes": "MPEG-4 Part 2 (ASP). Legacy codec; HEVC conversion likely worthwhile.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- MPEG2
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'MPEG2', json('{
    "family": "mpeg2",
    "generation": "legacy",
    "compression_efficiency": 2.0,
    "efficient_targets": ["HEVC"],
    "notes": "MPEG-2. Legacy codec; HEVC conversion likely worthwhile.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- MPEG2VIDEO (ffprobe name for MPEG-2)
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'MPEG2VIDEO', json('{
    "family": "mpeg2",
    "generation": "legacy",
    "compression_efficiency": 2.0,
    "efficient_targets": ["HEVC"],
    "notes": "MPEG-2. Legacy codec; HEVC conversion likely worthwhile.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- MPEG1VIDEO
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'MPEG1VIDEO', json('{
    "family": "mpeg1",
    "generation": "legacy",
    "compression_efficiency": 2.2,
    "efficient_targets": ["HEVC"],
    "notes": "MPEG-1. Legacy codec; HEVC conversion likely worthwhile.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';

-- UNKNOWN
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'video_codec', 'UNKNOWN', json('{
    "family": "unknown",
    "generation": "unknown",
    "compression_efficiency": 1.0,
    "efficient_targets": [],
    "notes": "Unknown codec; no codec conversion proposition is defensible.",
    "confidence": 0.50
}')
FROM knowledge_sets WHERE name='video_codec' AND version='1.0';


-- ----------------------------------------------------------
-- audio v1.0
-- ----------------------------------------------------------

INSERT INTO knowledge_sets (name, version, description)
VALUES ('audio', '1.0', 'Audio representation intelligence');

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'AAC', json('{
    "lossless": false,
    "compression_efficiency": 1.0,
    "storage_footprint": "low",
    "efficient_lossy_target": null,
    "notes": "AAC. Efficient lossy representation; no conversion proposition.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'OPUS', json('{
    "lossless": false,
    "compression_efficiency": 0.9,
    "storage_footprint": "low",
    "efficient_lossy_target": null,
    "notes": "Opus. Very efficient lossy representation.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'AC3', json('{
    "lossless": false,
    "compression_efficiency": 1.6,
    "storage_footprint": "moderate",
    "efficient_lossy_target": "OPUS",
    "notes": "AC-3 (Dolby Digital). Lossy; Opus may be more storage-efficient.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'EAC3', json('{
    "lossless": false,
    "compression_efficiency": 1.3,
    "storage_footprint": "moderate",
    "efficient_lossy_target": "OPUS",
    "notes": "E-AC-3. Lossy; Opus may be more storage-efficient.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'MP3', json('{
    "lossless": false,
    "compression_efficiency": 1.4,
    "storage_footprint": "moderate",
    "efficient_lossy_target": null,
    "notes": "MP3. Legacy lossy representation; conversion benefit modest.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'VORBIS', json('{
    "lossless": false,
    "compression_efficiency": 1.1,
    "storage_footprint": "low",
    "efficient_lossy_target": null,
    "notes": "Vorbis. Efficient lossy representation.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'DTS', json('{
    "lossless": false,
    "compression_efficiency": 2.2,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "DTS. Lossy; high footprint; Opus may be more storage-efficient.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'TRUEHD', json('{
    "lossless": true,
    "compression_efficiency": 3.0,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "TrueHD. Lossless; high footprint; conversion to lossy requires a quality trade-off.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'FLAC', json('{
    "lossless": true,
    "compression_efficiency": 2.6,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "FLAC. Lossless; high footprint; conversion to lossy requires a quality trade-off.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'PCM', json('{
    "lossless": true,
    "compression_efficiency": 4.0,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "PCM. Uncompressed lossless; high footprint; conversion to lossy requires a quality trade-off.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'PCM_S16LE', json('{
    "lossless": true,
    "compression_efficiency": 4.0,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "PCM 16-bit little-endian. Uncompressed lossless; high footprint.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'PCM_S24LE', json('{
    "lossless": true,
    "compression_efficiency": 4.0,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "PCM 24-bit little-endian. Uncompressed lossless; high footprint.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'PCM_S32LE', json('{
    "lossless": true,
    "compression_efficiency": 4.0,
    "storage_footprint": "high",
    "efficient_lossy_target": "OPUS",
    "notes": "PCM 32-bit little-endian. Uncompressed lossless; high footprint.",
    "confidence": 0.95
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio', 'UNKNOWN', json('{
    "lossless": null,
    "compression_efficiency": 1.0,
    "storage_footprint": "unknown",
    "efficient_lossy_target": null,
    "notes": "Unknown audio codec; no audio conversion proposition is defensible.",
    "confidence": 0.50
}')
FROM knowledge_sets WHERE name='audio' AND version='1.0';


-- ----------------------------------------------------------
-- codec_efficiency v1.0
-- ----------------------------------------------------------

INSERT INTO knowledge_sets (name, version, description)
VALUES ('codec_efficiency', '1.0', 'Codec conversion relationship intelligence');

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'codec_efficiency', 'H264->HEVC', json('{
    "source_codec": "H264",
    "target_codec": "HEVC",
    "relationship": "codec_conversion",
    "expected_storage_reduction": "substantial",
    "storage_reduction_low": 0.30,
    "storage_reduction_high": 0.50,
    "quality_risk": "low",
    "encoding_cost": "moderate",
    "notes": "H.264 to HEVC typically provides a substantial storage reduction at similar visual quality.",
    "confidence": 0.90
}')
FROM knowledge_sets WHERE name='codec_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'codec_efficiency', 'MPEG4->HEVC', json('{
    "source_codec": "MPEG4",
    "target_codec": "HEVC",
    "relationship": "codec_conversion",
    "expected_storage_reduction": "substantial",
    "storage_reduction_low": 0.40,
    "storage_reduction_high": 0.60,
    "quality_risk": "medium",
    "encoding_cost": "moderate",
    "notes": "MPEG-4 Part 2 to HEVC typically provides a substantial storage reduction.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='codec_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'codec_efficiency', 'MPEG2->HEVC', json('{
    "source_codec": "MPEG2",
    "target_codec": "HEVC",
    "relationship": "codec_conversion",
    "expected_storage_reduction": "substantial",
    "storage_reduction_low": 0.40,
    "storage_reduction_high": 0.60,
    "quality_risk": "medium",
    "encoding_cost": "moderate",
    "notes": "MPEG-2 to HEVC typically provides a substantial storage reduction.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='codec_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'codec_efficiency', 'MPEG1VIDEO->HEVC', json('{
    "source_codec": "MPEG1VIDEO",
    "target_codec": "HEVC",
    "relationship": "codec_conversion",
    "expected_storage_reduction": "substantial",
    "storage_reduction_low": 0.40,
    "storage_reduction_high": 0.60,
    "quality_risk": "medium",
    "encoding_cost": "moderate",
    "notes": "MPEG-1 to HEVC typically provides a substantial storage reduction.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='codec_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'codec_efficiency', 'VP9->AV1', json('{
    "source_codec": "VP9",
    "target_codec": "AV1",
    "relationship": "codec_conversion",
    "expected_storage_reduction": "moderate",
    "storage_reduction_low": 0.10,
    "storage_reduction_high": 0.25,
    "quality_risk": "low",
    "encoding_cost": "high",
    "notes": "VP9 to AV1 provides a moderate storage reduction at high encoding cost.",
    "confidence": 0.80
}')
FROM knowledge_sets WHERE name='codec_efficiency' AND version='1.0';


-- ----------------------------------------------------------
-- audio_efficiency v1.0
-- ----------------------------------------------------------

INSERT INTO knowledge_sets (name, version, description)
VALUES ('audio_efficiency', '1.0', 'Audio conversion relationship intelligence');

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio_efficiency', 'TRUEHD->OPUS', json('{
    "source_codec": "TRUEHD",
    "target_codec": "OPUS",
    "relationship": "audio_conversion",
    "expected_storage_reduction": "moderate",
    "audio_track_reduction_low": 0.60,
    "audio_track_reduction_high": 0.80,
    "quality_risk": "medium",
    "encoding_cost": "low",
    "notes": "Converting lossless TrueHD audio to Opus substantially reduces the audio track but is lossy.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='audio_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio_efficiency', 'FLAC->OPUS', json('{
    "source_codec": "FLAC",
    "target_codec": "OPUS",
    "relationship": "audio_conversion",
    "expected_storage_reduction": "moderate",
    "audio_track_reduction_low": 0.55,
    "audio_track_reduction_high": 0.75,
    "quality_risk": "medium",
    "encoding_cost": "low",
    "notes": "Converting lossless FLAC audio to Opus substantially reduces the audio track but is lossy.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='audio_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio_efficiency', 'PCM->OPUS', json('{
    "source_codec": "PCM",
    "target_codec": "OPUS",
    "relationship": "audio_conversion",
    "expected_storage_reduction": "moderate",
    "audio_track_reduction_low": 0.60,
    "audio_track_reduction_high": 0.85,
    "quality_risk": "medium",
    "encoding_cost": "low",
    "notes": "Converting uncompressed PCM audio to Opus substantially reduces the audio track but is lossy.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='audio_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio_efficiency', 'DTS->OPUS', json('{
    "source_codec": "DTS",
    "target_codec": "OPUS",
    "relationship": "audio_conversion",
    "expected_storage_reduction": "small",
    "audio_track_reduction_low": 0.40,
    "audio_track_reduction_high": 0.60,
    "quality_risk": "medium",
    "encoding_cost": "low",
    "notes": "Converting DTS audio to Opus reduces the audio track but is lossy.",
    "confidence": 0.80
}')
FROM knowledge_sets WHERE name='audio_efficiency' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'audio_efficiency', 'EAC3->OPUS', json('{
    "source_codec": "EAC3",
    "target_codec": "OPUS",
    "relationship": "audio_conversion",
    "expected_storage_reduction": "small",
    "audio_track_reduction_low": 0.25,
    "audio_track_reduction_high": 0.45,
    "quality_risk": "medium",
    "encoding_cost": "low",
    "notes": "Converting E-AC-3 audio to Opus reduces the audio track but is lossy.",
    "confidence": 0.80
}')
FROM knowledge_sets WHERE name='audio_efficiency' AND version='1.0';


-- ----------------------------------------------------------
-- bitrate_suitability v1.0
-- ----------------------------------------------------------

INSERT INTO knowledge_sets (name, version, description)
VALUES ('bitrate_suitability', '1.0', 'Expected bitrate range intelligence');

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'H264_2160p', json('{
    "codec": "H264",
    "resolution": "2160p",
    "typical_bitrate_bps": 30000000,
    "excess_reference_bps": 50000000,
    "justified_high_bitrate_bps": 65000000,
    "notes": "Typical good-quality H.264 2160p is around 30 Mbps; above ~50 Mbps indicates possible excess; above ~65 Mbps requires strong justification.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'H264_1080p', json('{
    "codec": "H264",
    "resolution": "1080p",
    "typical_bitrate_bps": 8000000,
    "excess_reference_bps": 12000000,
    "justified_high_bitrate_bps": 16000000,
    "notes": "Typical good-quality H.264 1080p is around 8 Mbps; above ~12 Mbps indicates possible excess; above ~16 Mbps may be justified by a high-value source.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'H264_720p', json('{
    "codec": "H264",
    "resolution": "720p",
    "typical_bitrate_bps": 5000000,
    "excess_reference_bps": 8000000,
    "justified_high_bitrate_bps": 10000000,
    "notes": "Typical good-quality H.264 720p is around 5 Mbps; above ~8 Mbps indicates possible excess.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'H264_480p', json('{
    "codec": "H264",
    "resolution": "480p",
    "typical_bitrate_bps": 2500000,
    "excess_reference_bps": 5000000,
    "justified_high_bitrate_bps": 7000000,
    "notes": "Typical good-quality H.264 480p is around 2.5 Mbps; above ~5 Mbps indicates possible excess.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'HEVC_2160p', json('{
    "codec": "HEVC",
    "resolution": "2160p",
    "typical_bitrate_bps": 20000000,
    "excess_reference_bps": 35000000,
    "justified_high_bitrate_bps": 50000000,
    "notes": "Typical good-quality HEVC 2160p is around 20 Mbps; above ~35 Mbps indicates possible excess.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'HEVC_1080p', json('{
    "codec": "HEVC",
    "resolution": "1080p",
    "typical_bitrate_bps": 5000000,
    "excess_reference_bps": 8000000,
    "justified_high_bitrate_bps": 12000000,
    "notes": "Typical good-quality HEVC 1080p is around 5 Mbps; above ~8 Mbps indicates possible excess.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'HEVC_720p', json('{
    "codec": "HEVC",
    "resolution": "720p",
    "typical_bitrate_bps": 3000000,
    "excess_reference_bps": 5000000,
    "justified_high_bitrate_bps": 8000000,
    "notes": "Typical good-quality HEVC 720p is around 3 Mbps; above ~5 Mbps indicates possible excess.",
    "confidence": 0.85
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

-- Unknown codec/resolution fallback entries so the rule always has a
-- documented reference to consult.
INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'UNKNOWN_1080p', json('{
    "codec": "UNKNOWN",
    "resolution": "1080p",
    "typical_bitrate_bps": 8000000,
    "excess_reference_bps": 15000000,
    "justified_high_bitrate_bps": 20000000,
    "notes": "Conservative fallback for an unknown codec at 1080p.",
    "confidence": 0.70
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'UNKNOWN_2160p', json('{
    "codec": "UNKNOWN",
    "resolution": "2160p",
    "typical_bitrate_bps": 30000000,
    "excess_reference_bps": 50000000,
    "justified_high_bitrate_bps": 65000000,
    "notes": "Conservative fallback for an unknown codec at 2160p.",
    "confidence": 0.70
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'UNKNOWN_720p', json('{
    "codec": "UNKNOWN",
    "resolution": "720p",
    "typical_bitrate_bps": 5000000,
    "excess_reference_bps": 8000000,
    "justified_high_bitrate_bps": 12000000,
    "notes": "Conservative fallback for an unknown codec at 720p.",
    "confidence": 0.70
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';

INSERT INTO knowledge_entries (
    knowledge_set_id, domain, knowledge_key, value_json
)
SELECT id, 'bitrate_suitability', 'UNKNOWN_480p', json('{
    "codec": "UNKNOWN",
    "resolution": "480p",
    "typical_bitrate_bps": 2500000,
    "excess_reference_bps": 5000000,
    "justified_high_bitrate_bps": 8000000,
    "notes": "Conservative fallback for an unknown codec at 480p.",
    "confidence": 0.70
}')
FROM knowledge_sets WHERE name='bitrate_suitability' AND version='1.0';