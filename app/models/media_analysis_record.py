"""
NAMOA media-analysis facts read model.

Represents the persisted technical facts (media_analysis row) for one
analysis run. This is a read model only: it is reconstructed from
persisted state and contains no persistence or business logic.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class MediaAnalysisRecord:
    """
    Technical media facts persisted for one analysis run.

    Facts mirror the media_analysis table columns that are meaningful
    for presentation: codec, resolution, duration, bitrate, audio
    tracks, HDR flag, container and analysis timestamp.
    """

    media_id: int

    analysis_run_id: Optional[int] = None

    resolution: Optional[str] = None

    video_codec: Optional[str] = None

    duration: Optional[float] = None

    bitrate: Optional[float] = None

    audio_tracks: Optional[int] = None

    is_hdr: Optional[int] = None

    container: Optional[str] = None

    analysed_at: Optional[str] = None
