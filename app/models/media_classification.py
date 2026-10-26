from dataclasses import dataclass


@dataclass(slots=True)
class MediaClassification:
    source: str | None = None
    release_type: str | None = None
    resolution: str | None = None
    video_codec: str | None = None
    audio_type: str | None = None

    hdr: bool = False
    dolby_vision: bool = False
