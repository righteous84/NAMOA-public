import subprocess
import json


def run_ffprobe(file_path: str):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        file_path
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=True
        )

        return json.loads(result.stdout)

    except Exception:
        return None


def _parse_frame_rate(value):
    """
    Normalise an FFprobe avg_frame_rate string ("30000/1001") to a
    float, or None when absent/unparseable. Additive technical fact.
    """

    if not value:
        return None

    if "/" in value:
        try:
            numerator, denominator = value.split("/", 1)
            denominator = float(denominator)
            if denominator == 0:
                return None
            return round(float(numerator) / denominator, 4)
        except (TypeError, ValueError):
            return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _audio_stream_fact(stream):
    """
    One audio stream's structured additive facts: codec, channels,
    sample rate, channel layout, and language where recorded.
    """

    return {
        "index": stream.get("index"),
        "codec": stream.get("codec_name"),
        "channels": int(stream.get("channels") or 0),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channel_layout": stream.get("channel_layout"),
        "language": (
            (stream.get("tags") or {}).get("language")
        ),
    }


def extract_summary(ffprobe_data):
    if not ffprobe_data:
        return None

    format_info = ffprobe_data.get(
        "format",
        {}
    )

    streams = ffprobe_data.get(
        "streams",
        []
    )

    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
        ),
        None
    )

    audio = [
        s
        for s in streams
        if s.get("codec_type") == "audio"
    ]

    subtitles = [
        s
        for s in streams
        if s.get("codec_type") == "subtitle"
    ]

    return {

        # -------------------------
        # Container / file facts
        # -------------------------

        "container": format_info.get(
            "format_name"
        ),

        "duration": float(
            format_info.get(
                "duration"
            )
            or 0
        ),

        "bitrate": int(
            format_info.get(
                "bit_rate"
            )
            or 0
        ),

        "size_bytes": int(
            format_info.get(
                "size"
            )
            or 0
        ),


        # -------------------------
        # Video facts
        # -------------------------

        "width": (
            video.get("width")
            if video
            else None
        ),

        "height": (
            video.get("height")
            if video
            else None
        ),

        "video_codec": (
            video.get("codec_name")
            if video
            else None
        ),

        "fps": (
            _parse_frame_rate(
                video.get("avg_frame_rate")
            )
            if video
            else None
        ),

        "pixel_format": (
            video.get("pix_fmt")
            if video
            else None
        ),

        "video_codec_profile": (
            video.get("profile")
            if video
            else None
        ),

        "video_codec_level": (
            video.get("level")
            if video
            else None
        ),

        "video_streams": (
            [
                {
                    "index": s.get("index"),
                    "codec": s.get("codec_name"),
                    "width": s.get("width"),
                    "height": s.get("height"),
                    "pix_fmt": s.get("pix_fmt"),
                    "profile": s.get("profile"),
                    "level": s.get("level"),
                }
                for s in streams
                if s.get("codec_type") == "video"
            ]
        ),


        # -------------------------
        # Audio facts
        # -------------------------

        "audio_tracks": len(audio),

        "audio_codec": (
            audio[0].get("codec_name")
            if audio
            else None
        ),

        "audio_channels": (
            int(audio[0].get("channels") or 0)
            if audio
            else 0
        ),

        "audio_sample_rate": (
            int(audio[0].get("sample_rate") or 0)
            if audio
            else 0
        ),

        "audio_channel_layout": (
            audio[0].get("channel_layout")
            if audio
            else None
        ),

        "audio_streams": [
            _audio_stream_fact(stream)
            for stream in audio
        ],


        # -------------------------
        # Subtitle facts
        # -------------------------

        "subtitle_tracks": len(subtitles),

        "subtitle_streams": [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
            }
            for s in subtitles
        ],

        "chapter_count": len(
            ffprobe_data.get("chapters") or []
        ),

        "format_tags": dict(
            format_info.get("tags") or {}
        ),


        # -------------------------
        # HDR facts
        # -------------------------

        "hdr_format": _derive_hdr_format(
            video
        ),

        "hdr_metadata": (
            {
                "color_transfer": video.get(
                    "color_transfer"
                ),
                "color_primaries": video.get(
                    "color_primaries"
                ),
                "color_space": video.get(
                    "color_space"
                ),
            }
            if video
            else None
        ),


        # -------------------------
        # Raw per-stream facts
        # -------------------------

        "streams": [
            {
                "index": s.get("index"),
                "codec_type": s.get("codec_type"),
                "codec_name": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "pix_fmt": s.get("pix_fmt"),
                "profile": s.get("profile"),
                "level": s.get("level"),
                "channels": s.get("channels"),
                "sample_rate": s.get("sample_rate"),
                "channel_layout": s.get("channel_layout"),
                "avg_frame_rate": s.get("avg_frame_rate"),
            }
            for s in streams
        ],
    }


def _derive_hdr_format(video):
    """
    Derive an HDR technical fact from the ffprobe video stream.

    Returns a raw technical value that HDRExpert normalises, or None
    for non-HDR (SDR) content so existing SDR behaviour is preserved.

    Sources, in order:
    - Dolby Vision: a DV codec tag (dvhe/dvh1/dvav/...) or DOVI side
      data.
    - HDR10: SMPTE ST 2084 / PQ transfer characteristic.
    - HLG: ARIB STD-B67 transfer characteristic.
    """

    if not video:
        return None

    codec_tag = (
        video.get("codec_tag_string")
        or ""
    ).lower()

    if (
        codec_tag.startswith("dv")
        or codec_tag.startswith("dvh")
        or codec_tag.startswith("dva")
    ):
        return "dolby_vision"

    transfer = (
        video.get("color_transfer")
        or ""
    ).lower()

    if "2084" in transfer:
        return transfer

    if "b67" in transfer:
        return transfer

    for side_data in video.get(
        "side_data_list"
    ) or []:

        side_type = (
            side_data.get(
                "side_data_type"
            )
            or ""
        ).lower()

        if (
            "dovi" in side_type
            or "dolby" in side_type
        ):
            return "dolby_vision"

    return None


def probe_file_summary(file_path: str):

    raw = run_ffprobe(
        file_path
    )

    return extract_summary(
        raw
    )