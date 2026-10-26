from typing import List

from app.decision_engine.decision_base_rule import BaseDecisionRule
from app.models.analysis_context import AnalysisContext
from app.decision_engine.signals.decision_signal import DecisionSignal
from app.services.savings_conversion import SavingsConversion


HIGH_VALUE_SOURCES = frozenset({"REMUX", "BLURAY"})

#: documented assumption (versioned with this rule): in the absence of
#: stream-level size evidence, the audio track of a video file is
#: assumed to be a small fraction of the whole file. An audio-only
#: file (no video stream) has share 1.0 from authoritative evidence.
DEFAULT_AUDIO_SHARE_OF_FILE = 0.15


class AudioRule(BaseDecisionRule):

    name = "audio_rule"

    # 1.1.0: fail-closed production behaviour. Required audio and
    # audio-efficiency knowledge is authoritative; a missing production
    # value yields an explicit "knowledge unavailable" result.
    semantic_version = "1.1.0"

    def supports(
        self,
        context: AnalysisContext
    ) -> bool:

        return (
            context.get_domain_analysis(
                "audio"
            )
            is not None
        )

    def _audio_semantics(
        self,
        context: AnalysisContext,
        codec: str,
    ):
        """
        (lossless, footprint, efficient_lossy_target) for the audio
        codec from maintained audio knowledge, or documented fallback.
        """

        knowledge = self._knowledge(
            context,
            domain="audio",
            key=codec,
        )

        if knowledge is not None:
            value = knowledge.value
            return (
                (
                    value.get("lossless"),
                    value.get("storage_footprint", "unknown"),
                    value.get("efficient_lossy_target"),
                ),
                True,
            )

        if not self.has_knowledge_service:
            return (
                FALLBACK_AUDIO_SEMANTICS.get(
                    codec,
                    (None, "unknown", None),
                ),
                True,
            )

        # Production knowledge present but the value is missing:
        # fail closed, the audio proposition cannot be established.
        return (None, "unknown", None), False

    def _conversion_relationship(
        self,
        context: AnalysisContext,
        codec: str,
        target: str,
    ):
        """
        (track_reduction_low, track_reduction_high, quality_risk,
        benefit) for an audio conversion, or None.
        """

        knowledge = self._knowledge(
            context,
            domain="audio_efficiency",
            key=f"{codec}->{target}",
        )

        if knowledge is not None:
            value = knowledge.value
            return (
                {
                    "reduction_low": float(
                        value.get("audio_track_reduction_low", 0.0)
                    ),
                    "reduction_high": float(
                        value.get("audio_track_reduction_high", 0.0)
                    ),
                    "quality_risk": value.get(
                        "quality_risk", "medium"
                    ),
                    "benefit": value.get(
                        "expected_storage_reduction", "small"
                    ),
                },
                True,
            )

        if not self.has_knowledge_service:

            fallback = FALLBACK_AUDIO_RELATIONSHIPS.get(
                f"{codec}->{target}",
                None,
            )

            if fallback is None:
                return None, True

            return (
                {
                    "reduction_low": fallback[0],
                    "reduction_high": fallback[1],
                    "quality_risk": fallback[2],
                    "benefit": fallback[3],
                },
                True,
            )

        return None, False

    def evaluate(
        self,
        context: AnalysisContext
    ) -> List[DecisionSignal]:

        result, analysis = self._get_domain(
            context,
            "audio",
        )

        if not analysis:
            return []

        policy = context.policy_or_default()

        codec = analysis.selected_value

        audio_confidence = analysis.confidence

        (lossless, footprint, target), audio_knowledge_resolved = (
            self._audio_semantics(
                context,
                codec,
            )
        )

        if not audio_knowledge_resolved:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="audio_conversion",
                    reason="audio knowledge unavailable",
                    notes=(
                        f"Required audio knowledge for {codec} is "
                        "unavailable; no audio conversion proposition "
                        "can be established."
                    ),
                    confidence=audio_confidence,
                    result=result,
                    analysis=analysis,
                    domain="audio",
                    cost="none",
                    risk="unknown",
                )
            ]

        if target is None:
            # Already efficient / not lossy-convertible: no audio
            # recommendation merely because another codec exists.
            return []

        if not policy.permit_audio_conversion:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="audio_conversion",
                    reason="user policy forbids audio conversion",
                    notes=(
                        f"{codec} audio could be converted, but "
                        "user policy forbids audio conversion."
                    ),
                    confidence=audio_confidence,
                    result=result,
                    analysis=analysis,
                    domain="audio",
                    cost="none",
                    risk="medium",
                )
            ]

        source = self._domain_value(
            context,
            "source",
        )

        # Lossless audio on a high-value archival source requires
        # stronger justification before changing.
        if lossless is True and source in HIGH_VALUE_SOURCES:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="audio_conversion",
                    reason=(
                        "lossless audio on a high-value source "
                        "warrants preservation"
                    ),
                    notes=(
                        f"Lossless {codec} audio on the "
                        f"'{source}' source requires stronger "
                        "justification before converting to a lossy "
                        "representation."
                    ),
                    confidence=audio_confidence,
                    result=result,
                    analysis=analysis,
                    domain="audio",
                    cost="low",
                    risk="medium",
                )
            ]

        relationship, relationship_resolved = (
            self._conversion_relationship(
                context,
                codec,
                target,
            )
        )

        if not relationship_resolved:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="audio_conversion",
                    reason=(
                        "audio conversion relationship knowledge "
                        "unavailable"
                    ),
                    notes=(
                        f"Required audio-efficiency relationship "
                        f"for {codec} to {target} is unavailable; "
                        "the conversion benefit cannot be estimated."
                    ),
                    confidence=audio_confidence,
                    result=result,
                    analysis=analysis,
                    domain="audio",
                    cost="none",
                    risk="unknown",
                )
            ]

        if relationship is None:
            return []

        reduction_mid = (
            relationship["reduction_low"]
            + relationship["reduction_high"]
        ) / 2

        # Authoritative audio share: an audio-only file has share 1.0;
        # otherwise the documented default share applies.
        has_video = (
            context.media.video_codec is not None
        )

        audio_share = (
            1.0
            if not has_video
            else DEFAULT_AUDIO_SHARE_OF_FILE
        )

        share_assumption = (
            "audio_share_1.0"
            if not has_video
            else "audio_share_0.15"
        )

        expected_saving_percent = round(
            reduction_mid * audio_share * 100,
            1,
        )

        size_bytes = context.media.size_bytes or 0

        # Owned conversion: bytes from the established percent
        # (Phase 9 canonical from_percent construction).
        converted = SavingsConversion.from_percent(
            expected_saving_percent,
            size_bytes,
        )

        expected_saved_bytes = converted.saved_bytes

        quality_risk = relationship["quality_risk"]

        if not policy.worthwhile(
            expected_saving_percent,
            expected_saved_bytes,
        ):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="audio_conversion",
                    reason=(
                        "expected storage saving too small to be "
                        "worthwhile"
                    ),
                    notes=(
                        f"Converting {codec} audio to {target} is "
                        f"expected to save about "
                        f"{expected_saving_percent:.0f}% of the file "
                        f"({expected_saved_bytes} bytes), which is "
                        "below the worthwhile threshold under "
                        "current user policy."
                    ),
                    confidence=audio_confidence,
                    result=result,
                    analysis=analysis,
                    domain="audio",
                    benefit=relationship["benefit"],
                    cost="low",
                    risk=quality_risk,
                )
            ]

        if not policy.risk_acceptable(quality_risk):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="audio_conversion",
                    reason="quality risk too high under user policy",
                    notes=(
                        f"Converting {codec} audio to {target} is "
                        f"lossy and carries '{quality_risk}' quality "
                        "risk, which exceeds the acceptable risk "
                        "under current user policy."
                    ),
                    confidence=audio_confidence,
                    result=result,
                    analysis=analysis,
                    domain="audio",
                    benefit=relationship["benefit"],
                    cost="low",
                    risk=quality_risk,
                )
            ]

        benefit = self.benefit_category(
            expected_saved_bytes
        )

        score = 0.45

        if benefit == "substantial":
            score = 0.65
        elif benefit == "moderate":
            score = 0.55
        elif benefit == "small":
            score = 0.35

        return [
            DecisionSignal(
                rule=self.name,
                opportunity_score=round(score, 3),
                confidence=audio_confidence,
                direction="optimize",
                proposition="audio_conversion",
                current_state=codec,
                target_state=target,
                benefit=benefit,
                cost="low",
                risk=quality_risk,
                reason=(
                    f"{codec} audio ({'lossless' if lossless else 'high footprint'}) "
                    f"is disproportionately large for this "
                    f"'{source or 'unknown'}' source; converting to "
                    f"{target} could reduce storage by about "
                    f"{expected_saving_percent:.0f}% "
                    f"({expected_saved_bytes} bytes) without "
                    "changing the video stream, at a lossy quality "
                    "trade-off."
                ),
                notes=(
                    f"{codec} audio conversion proposition "
                    f"({target} target)"
                ),
                evidence={
                    "audio_codec": codec,
                    "target_audio_codec": target,
                    "lossless": lossless,
                    "storage_footprint": footprint,
                    "audio_share": audio_share,
                    "expected_saving_percent": (
                        expected_saving_percent
                    ),
                    "expected_saved_bytes": expected_saved_bytes,
                    "assumption": share_assumption,
                    "basis": converted.basis,
                    "modelling_version": (
                        SavingsConversion.semantic_version
                    ),
                    "source": source,
                    "size_bytes": size_bytes,
                },
                provenance=self._build_provenance(
                    result,
                    analysis,
                    "audio",
                ),
            )
        ]


#: documented fallback audio semantics (lossless, footprint, target)
FALLBACK_AUDIO_SEMANTICS = {
    "TRUEHD": (True, "high", "OPUS"),
    "FLAC": (True, "high", "OPUS"),
    "PCM": (True, "high", "OPUS"),
    "DTS": (False, "high", "OPUS"),
    "EAC3": (False, "moderate", "OPUS"),
    "AC3": (False, "moderate", None),
    "AAC": (False, "low", None),
    "OPUS": (False, "low", None),
    "MP3": (False, "moderate", None),
}

#: (track_reduction_low, track_reduction_high, quality_risk, benefit)
FALLBACK_AUDIO_RELATIONSHIPS = {
    "TRUEHD->OPUS": (0.60, 0.80, "medium", "moderate"),
    "FLAC->OPUS": (0.55, 0.75, "medium", "moderate"),
    "PCM->OPUS": (0.60, 0.85, "medium", "moderate"),
    "DTS->OPUS": (0.40, 0.60, "medium", "small"),
    "EAC3->OPUS": (0.25, 0.45, "medium", "small"),
}