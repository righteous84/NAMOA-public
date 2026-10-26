"""
Normalized output from FFprobe.

Represents objective media properties extracted directly from
the media file. Contains no interpretation or recommendations.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class FFprobeSummary:
    width: int = 0
    height: int = 0

    duration: float = 0.0

    bitrate: int = 0

    video_codec: str = ""

    audio_tracks: int = 0

    frame_rate: float = 0.0

    container: str = ""

    file_size: int = 0
