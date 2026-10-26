from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True, frozen=True)
class ClassificationEvidence:
    """
    Represents a single piece of evidence supporting a classification.

    Evidence is intentionally independent of any specific classifier.
    Multiple sources (filename, FFprobe, MediaInfo, OCR, AI, etc.)
    can produce ClassificationEvidence instances which are later
    evaluated by Experts and the Fusion Engine.
    """

    # What is being classified?
    domain: str

    # Proposed classification value.
    value: str

    # Confidence in this evidence (0.0 - 1.0)
    confidence: float

    # Origin of the evidence.
    # Examples:
    #   filename
    #   ffprobe
    #   mediainfo
    #   tmdb
    #   ai
    source: str

    # Identifier for traceability.
    # Examples:
    #   filename rule name
    #   FFprobe field name
    #   AI model identifier
    evidence_id: Optional[str] = None

    # Actual text/value that generated this evidence.
    # Mainly useful for filename-based evidence.
    matched_text: Optional[str] = None