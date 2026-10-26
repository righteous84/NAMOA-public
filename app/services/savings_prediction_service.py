"""Predicted-savings semantics (Phase 6).

Distinguishes PREDICTED savings (what NAMOA expects before execution)
from MEASURED savings (what actually happened after execution, derived
from source and result observations).

The old conceptual `estimated_saving_percent = score * 50` shortcut is
never used as an execution savings model. Prediction derives from the
requested transformation, the source observation, and versioned
optimisation knowledge. Where the knowledge service is unavailable or
a relationship is missing, a versioned documented fallback applies and
the basis is recorded so no false precision is presented.

Compatibility-only operations (container remux) never claim a storage
saving.
"""

from app.execution.operations import (
    OPERATION_REMUX_MP4,
    require_operation,
)

from app.models.transformation import (
    RequestedTransformation,
)

#: Semantic version of the prediction policy meaning. A change to the
#: relationship constants, the fallback map, or the derivation logic
#: that can alter a prediction MUST bump this version.
PREDICTION_POLICY_VERSION = "1.0.0"

#: Versioned documented fallback: (target, reduction_low,
#: reduction_high, confidence). Mirrors the codec-efficiency
#: relationship knowledge and is used ONLY when the knowledge service
#: is unavailable or the relationship is missing.
FALLBACK_RELATIONSHIPS = {
    "H264->HEVC": (0.30, 0.50, 0.90),
    "MPEG2->HEVC": (0.40, 0.60, 0.85),
    "MPEG4->HEVC": (0.40, 0.60, 0.85),
    "MPEG2VIDEO->HEVC": (0.40, 0.60, 0.85),
    "MPEG1VIDEO->HEVC": (0.40, 0.60, 0.85),
    "VP9->AV1": (0.10, 0.25, 0.80),
}


class SavingsPredictionService:
    """
    Versioned predicted-savings semantics.

    Measured savings are NOT produced here: they are computed by the
    execution authority from the actual source and result observations
    after successful verified replacement.
    """

    semantic_version = PREDICTION_POLICY_VERSION

    def __init__(
        self,
        *,
        knowledge_service=None,
    ):

        self.knowledge_service = knowledge_service

    # -------------------------------------------------
    # Prediction
    # -------------------------------------------------

    def predict(
        self,
        *,
        transformation: RequestedTransformation,
        source_summary: dict | None,
        source_size_bytes: int | None,
    ) -> dict:
        """
        Predicted savings for a requested transformation.

        Returns the `predicted_json` payload:

            predicted_saved_bytes   int | null
            predicted_percent       float | null
            basis                   description of the derivation
            evidence                the facts used
            knowledge_version       knowledge/fallback version used
            confidence              float
            compatibility_only      bool

        Compatibility-only operations produce null savings with
        `compatibility_only: true`. No precision is invented that the
        evidence cannot support.
        """

        operation = transformation.operation

        definition = require_operation(operation)

        if not definition.storage_savings_expected:

            return {
                "predicted_saved_bytes": None,
                "predicted_percent": None,
                "basis": (
                    "compatibility operation; no storage saving "
                    "claimed"
                ),
                "evidence": {},
                "knowledge_version": None,
                "confidence": None,
                "compatibility_only": True,
                "operation": operation,
            }

        source_codec = (
            (source_summary or {}).get("video_codec") or ""
        )

        target_codec = self._target_codec(transformation)

        relationship = self._relationship(
            source_codec,
            target_codec,
        )

        size = int(source_size_bytes or 0)

        if relationship is None or size <= 0:

            return {
                "predicted_saved_bytes": None,
                "predicted_percent": None,
                "basis": (
                    "no defensible relationship for "
                    f"{source_codec}->{target_codec}; no prediction"
                ),
                "evidence": {
                    "source_codec": source_codec,
                    "target_codec": target_codec,
                },
                "knowledge_version": None,
                "confidence": None,
                "compatibility_only": False,
                "operation": operation,
            }

        low, high, confidence = relationship

        reduction_mid = (low + high) / 2

        predicted_percent = round(reduction_mid * 100, 1)

        predicted_saved_bytes = int(size * reduction_mid)

        return {
            "predicted_saved_bytes": predicted_saved_bytes,
            "predicted_percent": predicted_percent,
            "basis": (
                "transformation + versioned codec relationship "
                "knowledge applied to the source observation"
            ),
            "evidence": {
                "source_codec": source_codec,
                "target_codec": target_codec,
                "source_size_bytes": size,
                "storage_reduction_low": low,
                "storage_reduction_high": high,
                "relationship_used": (
                    f"{source_codec.upper()}->{target_codec.upper()}"
                ),
            },
            "knowledge_version": (
                self._knowledge_version()
            ),
            "confidence": round(confidence, 3),
            "compatibility_only": False,
            "operation": operation,
        }

    # -------------------------------------------------
    # Internals
    # -------------------------------------------------

    def _target_codec(
        self,
        transformation: RequestedTransformation,
    ) -> str:
        """
        The transformation's target video codec, from the operation
        definition's expected output or the proposition target.
        """

        definition = require_operation(transformation.operation)

        expected = definition.expected_output.get("video_codec")

        if expected:
            return str(expected)

        for proposition in transformation.propositions:
            if proposition.target_state:
                return str(proposition.target_state)

        return ""

    def _relationship(
        self,
        source_codec: str,
        target_codec: str,
    ):
        """
        (low, high, confidence) for the conversion, from the versioned
        codec-efficiency knowledge set when available, otherwise from
        the documented versioned fallback. None when no defensible
        relationship exists.
        """

        key = f"{source_codec.upper()}->{target_codec.upper()}"

        if self.knowledge_service is not None:

            entry = self.knowledge_service.get(
                domain="codec_efficiency",
                key=key,
            )

            if entry is not None:

                value = entry.value

                try:
                    low = float(
                        value.get("storage_reduction_low", 0.0)
                    )
                    high = float(
                        value.get("storage_reduction_high", 0.0)
                    )
                    confidence = float(
                        value.get("confidence", 0.85)
                    )
                except (TypeError, ValueError):
                    low = high = confidence = None

                if low is not None and high > 0:
                    return (low, high, confidence)

        return FALLBACK_RELATIONSHIPS.get(key)

    def _knowledge_version(self) -> str | None:
        """
        The authoritative knowledge version when a knowledge service
        is wired (its knowledge sets are versioned in the database).
        """

        if self.knowledge_service is None:
            return f"fallback:{PREDICTION_POLICY_VERSION}"

        return f"knowledge+policy:{PREDICTION_POLICY_VERSION}"

    def policy_values(self) -> dict:
        """
        The attributable prediction-policy snapshot.
        """

        return {
            "version": self.semantic_version,
            "fallback_relationships": {
                key: list(value)
                for key, value in FALLBACK_RELATIONSHIPS.items()
            },
        }