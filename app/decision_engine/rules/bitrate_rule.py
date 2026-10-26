from typing import List

from app.decision_engine.decision_base_rule import BaseDecisionRule
from app.models.analysis_context import AnalysisContext
from app.decision_engine.signals.decision_signal import DecisionSignal
from app.services.savings_conversion import SavingsConversion


HIGH_VALUE_SOURCES = frozenset({"REMUX", "BLURAY"})

#: documented fallback bitrate references (typical, excess, justified
#: high) per resolution, used ONLY when no knowledge service is
#: present (isolated unit testing). They mirror the maintained
#: bitrate_suitability knowledge set (migration 028, including the
#: UNKNOWN_* entries). In production a missing knowledge value fails
#: closed instead of silently using these constants.
FALLBACK_BITRATE_REFERENCES = {
    "2160p": (30_000_000, 50_000_000, 65_000_000),
    "1080p": (8_000_000, 12_000_000, 16_000_000),
    "720p": (5_000_000, 8_000_000, 10_000_000),
    "480p": (2_500_000, 5_000_000, 7_000_000),
}

#: neutral prior for an unattributed codec claim, used ONLY to
#: calibrate bitrate-signal confidence when no video_codec domain
#: analysis exists (the rule then names a codec it did not observe).
#: Mirrors the established 0.5 default the codec, audio and hdr
#: experts use when codec knowledge is unattended. Never invents a
#: codec: the UNKNOWN label is retained in the signal evidence.
UNKNOWN_CODEC_CONFIDENCE = 0.5


def _height_key(height: int) -> str:
    if height >= 2160:
        return "2160p"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    return "480p"


class BitrateRule(BaseDecisionRule):

    name = "bitrate_rule"

    # 2.1.0: fail-closed production behaviour. bitrate_suitability
    # knowledge is authoritative (codec-specific with the maintained
    # UNKNOWN_* production fallback); a missing production value yields
    # an explicit "knowledge unavailable" result.
    # 2.2.0: calibrated optimize-signal confidence. The conclusion
    # names a codec, so confidence combines resolution certainty with
    # codec-attribution certainty (multiplicative, mirroring
    # codec_rule); an absent video_codec domain calibrates with the
    # documented UNKNOWN_CODEC_CONFIDENCE neutral prior instead of
    # the full resolution confidence. Preserve paths are unchanged.
    semantic_version = "2.2.0"

    def supports(
        self,
        context: AnalysisContext
    ) -> bool:

        return (
            context.media.bitrate is not None
            and context.get_domain_analysis(
                "resolution"
            ) is not None
        )

    def _references(
        self,
        context: AnalysisContext,
        codec: str,
        height_key: str,
    ):
        """
        (typical, excess, justified_high) bitrate references for the
        codec and resolution.

        In production the maintained bitrate_suitability knowledge is
        authoritative: the codec-specific entry is used, and the
        maintained UNKNOWN_* entry (also versioned Knowledge) is the
        production fallback for an unseeded codec. When no knowledge
        service is present, documented test constants apply. Returns
        (references, knowledge_resolved); knowledge_resolved is False
        only when production knowledge is missing entirely (fail
        closed).
        """

        knowledge = self._knowledge(
            context,
            domain="bitrate_suitability",
            key=f"{codec}_{height_key}",
        )

        if knowledge is None and self.has_knowledge_service:
            # Maintained production fallback for an unseeded codec
            # lives in the same versioned knowledge set.
            knowledge = self._knowledge(
                context,
                domain="bitrate_suitability",
                key=f"UNKNOWN_{height_key}",
            )

        if knowledge is not None:
            value = knowledge.value
            return (
                (
                    int(value.get("typical_bitrate_bps", 0)),
                    int(value.get("excess_reference_bps", 0)),
                    int(value.get("justified_high_bitrate_bps", 0)),
                ),
                True,
            )

        if not self.has_knowledge_service:
            return (
                FALLBACK_BITRATE_REFERENCES.get(
                    height_key,
                    (0, 0, 0),
                ),
                True,
            )

        return (0, 0, 0), False

    def evaluate(
        self,
        context: AnalysisContext
    ) -> List[DecisionSignal]:

        result, resolution_analysis = self._get_domain(
            context,
            "resolution",
        )

        if not resolution_analysis:
            return []

        policy = context.policy_or_default()

        bitrate = context.media.bitrate or 0

        resolution = resolution_analysis.selected_value

        height = context.media.height or 0

        height_key = _height_key(height)

        codec = self._domain_value(
            context,
            "video_codec",
            default="UNKNOWN",
        )

        (typical, excess, justified_high), knowledge_resolved = (
            self._references(
                context,
                codec,
                height_key,
            )
        )

        if not knowledge_resolved:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="bitrate_reduction",
                    reason="bitrate suitability knowledge unavailable",
                    notes=(
                        f"Required bitrate-suitability knowledge for "
                        f"{resolution} is unavailable; whether the "
                        "bitrate is excessive cannot be established."
                    ),
                    confidence=resolution_analysis.confidence,
                    result=result,
                    analysis=resolution_analysis,
                    domain="resolution",
                    cost="none",
                    risk="unknown",
                )
            ]

        if bitrate <= 0 or excess <= 0:
            return []

        source = self._domain_value(
            context,
            "source",
        )

        provenance = self._build_provenance(
            result,
            resolution_analysis,
            "resolution",
        )

        # The bitrate is not materially higher than necessary.
        if bitrate <= excess:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="bitrate_reduction",
                    reason="bitrate already appropriate",
                    notes=(
                        f"{resolution} {codec} bitrate of "
                        f"{bitrate} bps is not materially higher "
                        "than necessary."
                    ),
                    confidence=resolution_analysis.confidence,
                    result=result,
                    analysis=resolution_analysis,
                    domain="resolution",
                    cost="none",
                    risk="low",
                    evidence={
                        "resolution": resolution,
                        "codec": codec,
                        "bitrate": bitrate,
                        "excess_reference_bps": excess,
                    },
                )
            ]

        if not policy.permit_bitrate_reduction:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="bitrate_reduction",
                    reason="user policy forbids bitrate reduction",
                    notes=(
                        f"{resolution} {codec} bitrate of "
                        f"{bitrate} bps could be reduced, but user "
                        "policy forbids bitrate reduction."
                    ),
                    confidence=resolution_analysis.confidence,
                    result=result,
                    analysis=resolution_analysis,
                    domain="resolution",
                    cost="none",
                    risk="low",
                    evidence={
                        "resolution": resolution,
                        "codec": codec,
                        "bitrate": bitrate,
                        "excess_reference_bps": excess,
                    },
                )
            ]

        # A high bitrate may be justified by a high-value source.
        if (
            source in HIGH_VALUE_SOURCES
            and justified_high > 0
            and bitrate <= justified_high
        ):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="bitrate_reduction",
                    reason="high bitrate justified by source quality",
                    notes=(
                        f"{bitrate} bps is high, but is consistent "
                        f"with the '{source}' source quality and "
                        "preservation intent."
                    ),
                    confidence=resolution_analysis.confidence,
                    result=result,
                    analysis=resolution_analysis,
                    domain="resolution",
                    cost="none",
                    risk="low",
                    evidence={
                        "resolution": resolution,
                        "codec": codec,
                        "bitrate": bitrate,
                        "excess_reference_bps": excess,
                        "justified_high_bitrate_bps": justified_high,
                        "source": source,
                    },
                )
            ]

        # A material excess exists; build the reduction proposition.
        target_bitrate = typical if typical > 0 else int(excess * 0.6)

        target_assumption = (
            "bitrate_target_typical"
            if typical > 0
            else "bitrate_target_fallback_0.6"
        )

        expected_saving_percent = round(
            ((bitrate - target_bitrate) / bitrate) * 100,
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

        risk = "medium" if source in HIGH_VALUE_SOURCES else "low"

        if not policy.worthwhile(
            expected_saving_percent,
            expected_saved_bytes,
        ):
            return [
                self._preserve_signal(
                    context=context,
                    proposition="bitrate_reduction",
                    reason=(
                        "expected storage saving too small to be "
                        "worthwhile"
                    ),
                    notes=(
                        f"Reducing the {resolution} {codec} bitrate "
                        f"from {bitrate} bps toward {target_bitrate} "
                        f"bps would save about "
                        f"{expected_saving_percent:.0f}% "
                        f"({expected_saved_bytes} bytes), which is "
                        "below the worthwhile threshold under "
                        "current user policy."
                    ),
                    confidence=resolution_analysis.confidence,
                    result=result,
                    analysis=resolution_analysis,
                    domain="resolution",
                    benefit="none",
                    cost="low",
                    risk=risk,
                    evidence={
                        "resolution": resolution,
                        "codec": codec,
                        "bitrate": bitrate,
                        "expected_saving_percent": (
                            expected_saving_percent
                        ),
                    "expected_saved_bytes": expected_saved_bytes,
                    "assumption": target_assumption,
                    "basis": converted.basis,
                    "modelling_version": (
                        SavingsConversion.semantic_version
                    ),
                    },
                )
            ]

        if not policy.risk_acceptable(risk):
            return [
                self._preserve_signal(
                    context=context,
                    proposition="bitrate_reduction",
                    reason="quality risk too high under user policy",
                    notes=(
                        f"Reducing the {resolution} {codec} bitrate "
                        f"carries '{risk}' risk, which exceeds the "
                        "acceptable risk under current user policy."
                    ),
                    confidence=resolution_analysis.confidence,
                    result=result,
                    analysis=resolution_analysis,
                    domain="resolution",
                    benefit="small",
                    cost="low",
                    risk=risk,
                    evidence={
                        "resolution": resolution,
                        "codec": codec,
                        "bitrate": bitrate,
                        "expected_saving_percent": (
                            expected_saving_percent
                        ),
                        "assumption": target_assumption,
                        "basis": converted.basis,
                        "modelling_version": (
                            SavingsConversion.semantic_version
                        ),
                    },
                )
            ]

        benefit = self.benefit_category(
            expected_saved_bytes
        )

        score = 0.35

        if benefit == "substantial":
            score = 0.75
        elif benefit == "moderate":
            score = 0.60
        elif benefit == "small":
            score = 0.45

        # Calibrated confidence: the bitrate conclusion names a codec,
        # so it combines the resolution certainty with the codec
        # attribution certainty (the codec_rule multiplicative
        # pattern). When no video_codec domain analysis exists the
        # codec is UNKNOWN and the neutral prior applies.
        _, codec_analysis = self._get_domain(
            context,
            "video_codec",
        )

        if codec_analysis is not None:
            codec_confidence = codec_analysis.confidence
        else:
            codec_confidence = UNKNOWN_CODEC_CONFIDENCE

        confidence = round(
            resolution_analysis.confidence * codec_confidence,
            3,
        )

        return [
            DecisionSignal(
                rule=self.name,
                opportunity_score=round(score, 3),
                confidence=confidence,
                direction="optimize",
                proposition="bitrate_reduction",
                current_state=(
                    f"{bitrate} bps"
                ),
                target_state=(
                    f"~{target_bitrate} bps"
                ),
                benefit=benefit,
                cost="low",
                risk=risk,
                reason=(
                    f"Bitrate {bitrate} bps is materially higher "
                    f"than necessary for {resolution} {codec}; "
                    f"reducing toward {target_bitrate} bps is "
                    f"expected to save about "
                    f"{expected_saving_percent:.0f}% "
                    f"({expected_saved_bytes} bytes)."
                ),
                notes=(
                    f"{resolution} | {bitrate} bps | excess bitrate "
                    "for the represented quality"
                ),
                evidence={
                    "resolution": resolution,
                    "codec": codec,
                    "codec_confidence": codec_confidence,
                    "bitrate": bitrate,
                    "typical_bitrate_bps": typical,
                    "excess_reference_bps": excess,
                    "expected_saving_percent": (
                        expected_saving_percent
                    ),
                    "expected_saved_bytes": expected_saved_bytes,
                    "source": source,
                    "size_bytes": size_bytes,
                    "assumption": target_assumption,
                    "basis": converted.basis,
                    "modelling_version": (
                        SavingsConversion.semantic_version
                    ),
                },
                provenance=provenance,
            )
        ]