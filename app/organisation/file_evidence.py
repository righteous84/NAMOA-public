"""
File/technical evidence for extended filenames
(Sprint 15 media identification).

Pure extraction of technical/release facts from a
local filename using the existing analysis rule
engines (source, resolution, video codec, audio,
HDR, release type) plus technical facts from an
analysed media context (ffprobe-backed scans)
where the filename is silent.

Only values the pipeline genuinely resolves are
exposed: anything uncertain stays missing so the
extended-naming renderer omits the component
instead of inventing text. Provider tags never
feed filenames.

Domain note: these are the same pure filename
classifiers the analysis pipeline uses; no
expert, decision-engine, or optimisation
component is involved, and nothing here
classifies, recommends, or mutates.
"""

import re

from app.analysis_engine.media_classifier.audio_classifier import (
    classify_audio,
)
from app.analysis_engine.media_classifier.hdr_classifier import (
    classify_hdr,
)
from app.analysis_engine.media_classifier.release_classifier import (
    classify_release_type,
)
from app.analysis_engine.media_classifier.resolution_classifier import (
    classify_resolution,
)
from app.analysis_engine.media_classifier.rules.rule_engine import (
    RuleEngine,
)
from app.analysis_engine.media_classifier.rules.rule_registry import (
    RuleRegistry,
)
from app.analysis_engine.media_classifier.source_classifier import (
    classify_source,
)
from app.analysis_engine.media_classifier.video_codec_classifier import (
    classify_video_codec,
)

#: Minimum rule confidence for the HDR token:
#: only explicit markers count, never the weak
#: 2160p/remux inferences.
_HDR_CONFIDENCE_FLOOR = 90

_hdr_engine = RuleEngine(
    RuleRegistry.get("hdr"),
    classifier="hdr",
)

_dv_engine = RuleEngine(
    RuleRegistry.get("dolby_vision"),
    classifier="dolby_vision",
)

#: Normalisation for technical codecs observed by
#: ffprobe when the filename itself is silent.
#: Unknown values stay missing rather than
#: guessed.
_CODEC_MAP = {
    "hevc": "HEVC",
    "h265": "HEVC",
    "x265": "HEVC",
    "h264": "H264",
    "x264": "H264",
    "avc": "H264",
    "av1": "AV1",
    "av01": "AV1",
}

_AUDIO_MAP = {
    "truehd": "TRUEHD",
    "atmos": "TRUEHD",
    "dts": "DTS",
    "eac3": "AC3/EAC3",
    "ac3": "AC3/EAC3",
    "aac": "AAC",
}


def _confident_hdr(name: str) -> str:
    """
    HDR/DV marker from explicit high-confidence
    filename rules only. Returns "DV", "HDR", or "".
    """

    lowered = str(name or "").lower()

    for evidence in _dv_engine.evaluate_evidence(lowered):
        if (evidence.confidence or 0) >= _HDR_CONFIDENCE_FLOOR:
            return "DV"

    for evidence in _hdr_engine.evaluate_evidence(lowered):
        if (evidence.confidence or 0) >= _HDR_CONFIDENCE_FLOOR:
            return "HDR"

    return ""


def _normalise_observed_codec(value, mapping: dict) -> str:
    text = str(value or "").strip().lower()

    if not text:
        return ""

    if text in mapping:
        return mapping[text]

    return ""


def _resolution_from_height(height) -> str:
    try:
        pixels = int(height)
    except (TypeError, ValueError):
        return ""

    if pixels >= 2160:
        return "2160p"

    if pixels >= 1080:
        return "1080p"

    if pixels >= 720:
        return "720p"

    if pixels >= 480:
        return "480p"

    return ""


def extract_file_evidence(filename, *, context=None) -> dict:
    """
    Technical/release facts for extended naming:
    resolution, quality (= resolution label),
    source, codec, audio, hdr, edition, bitrate.
    Missing data stays "" (never invented).
    `context` is an optional analysed media
    context (or mapping) with bitrate/height/
    codec facts used only when the filename is
    silent. Pure; never touches the filesystem.
    """

    name = str(filename or "")
    lowered = name.lower()

    resolution = classify_resolution(lowered) or ""
    source = classify_source(lowered) or ""
    codec = classify_video_codec(lowered) or ""
    audio = classify_audio(lowered) or ""
    hdr = _confident_hdr(lowered)
    release = classify_release_type(lowered) or ""
    edition = "" if release in ("", "ENCODE") else release

    facts = dict(context or {}) if isinstance(
        context, dict
    ) else {}

    if not resolution:
        height = facts.get("height")

        if height is None and context is not None:
            height = getattr(context, "height", None)

        resolution = _resolution_from_height(height)

    bitrate = facts.get("bitrate")

    if bitrate is None and context is not None:
        bitrate = getattr(context, "bitrate", None)

    try:
        bitrate_text = (
            str(int(bitrate)) if bitrate is not None else ""
        )
    except (TypeError, ValueError):
        bitrate_text = ""

    if not codec:
        observed = facts.get("video_codec")

        if observed is None and context is not None:
            observed = getattr(context, "video_codec", None)

        codec = _normalise_observed_codec(observed, _CODEC_MAP)

    if not audio:
        observed = facts.get("audio_codec")

        if observed is None and context is not None:
            observed = getattr(context, "audio_codec", None)

        audio = _normalise_observed_codec(observed, _AUDIO_MAP)

    if not hdr:
        observed = facts.get("hdr_format")

        if observed is None and context is not None:
            observed = getattr(context, "hdr_format", None)

        text = str(observed or "").strip().upper()

        hdr = text if text in ("HDR", "DV") else ""

    quality = resolution

    return {
        "resolution": resolution,
        "quality": quality,
        "source": source,
        "codec": codec,
        "audio": audio,
        "hdr": hdr,
        "edition": edition,
        "bitrate": bitrate_text,
    }


#: Token names the extended renderer accepts in
#: the file namespace, in picker order.
FILE_TOKENS = (
    "quality",
    "resolution",
    "bitrate",
    "codec",
    "audio",
    "source",
    "hdr",
    "edition",
)

#: Token names accepted in the media namespace,
#: in picker order.
MEDIA_TOKENS = (
    "title",
    "year",
    "series",
    "season",
    "episode",
    "episode_title",
)
