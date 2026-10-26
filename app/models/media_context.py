from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass(frozen=True, slots=True)
class MediaContext:
    """
    Immutable representation of facts discovered about a media file.

    Ownership boundary:

        Scanner
            |
            v
        FFProbe
            |
            v
        MediaContext
            |
            v
        AnalysisContext


    MediaContext contains ONLY facts.

    Allowed:
        - filesystem information
        - scanner metadata
        - ffprobe metadata
        - raw source information


    Not allowed:
        - classifications
        - expert reasoning
        - evidence
        - scoring
        - recommendations
        - assessments
        - execution state


    Once created, this object must never change.
    Derived intelligence belongs in AnalysisContext.
    """


    # -------------------------
    # Identity / File System Facts
    # -------------------------

    path: str

    name: Optional[str] = None

    extension: Optional[str] = None

    container: Optional[str] = None

    source: Optional[str] = None

    # -------------------------
    # File Statistics
    # -------------------------

    size_bytes: Optional[int] = None

    file_mtime_ns: Optional[int] = None

    size_mib: Optional[float] = None

    size_gib: Optional[float] = None



    # -------------------------
    # Technical Media Facts
    # -------------------------

    duration: Optional[float] = None

    bitrate: Optional[int] = None


    width: Optional[int] = None

    height: Optional[int] = None

    fps: Optional[float] = None


    video_codec: Optional[str] = None


    audio_codec: Optional[str] = None

    audio_channels: Optional[int] = None

    audio_language: Optional[str] = None


    hdr_format: Optional[str] = None



    # -------------------------
    # Raw Source Data
    # -------------------------

    raw_ffprobe: Dict[str, Any] = field(
        default_factory=dict
    )


    raw_scanner: Dict[str, Any] = field(
        default_factory=dict
    )