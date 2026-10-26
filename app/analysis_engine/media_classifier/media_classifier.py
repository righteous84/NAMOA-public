"""
Deprecated.

Classification is now performed through:

EvidenceBuilder
    ->
ClassificationExpert

Retained temporarily for migration compatibility.
"""

from app.models.media_classification import MediaClassification

from .source_classifier import classify_source
from .release_classifier import classify_release_type
from .resolution_classifier import classify_resolution
from .video_codec_classifier import classify_video_codec
from .audio_classifier import classify_audio
from .hdr_classifier import classify_hdr

class MediaClassifier:
    """
    Public facade for media classification.

    This remains the stable API:
        classification = MediaClassifier().classify(filename, summary)
    """

    def classify(self, filename: str, summary=None) -> MediaClassification:
        name = filename.lower()

        classification = MediaClassification()

        # -------------------------
        # Source detection
        # -------------------------
        classification.source = classify_source(name)

        # -------------------------
        # Release type
        # -------------------------
        classification.release_type = classify_release_type(name)

        # -------------------------
        # Resolution
        # -------------------------
        classification.resolution = classify_resolution(name)

        # -------------------------
        # Video codec
        # -------------------------
        classification.video_codec = classify_video_codec(name)

        # -------------------------
        # Audio
        # -------------------------
        classification.audio_type = classify_audio(name)

        # -------------------------
        # HDR
        # -------------------------
        hdr, dv = classify_hdr(name)
        classification.hdr = hdr
        classification.dolby_vision = dv

        return classification