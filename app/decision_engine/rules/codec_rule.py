from typing import List

from app.decision_engine.decision_base_rule import BaseDecisionRule
from app.models.analysis_context import AnalysisContext
from app.decision_engine.signals.decision_signal import DecisionSignal
from app.services.savings_conversion import SavingsConversion


# Documented fallback relationships used ONLY when no knowledge
# service is present (isolated unit testing). They mirror the
# maintained codec_efficiency knowledge set (migration 028) and are
# versioned with this rule. In production a missing knowledge value
# fails closed instead of silently using these constants.
FALLBACK_EFFICIENT_TARGETS = {
    "H264": ["HEVC"],
    "MPEG4": ["HEVC"],
    "MPEG2": ["HEVC"],
    "MPEG2VIDEO": ["HEVC"],
    "MPEG1VIDEO": ["HEVC"],
    "VP9": ["AV1"],
}

#: (target, reduction_low, reduction_high, quality_risk, cost,
#:  benefit, confidence)
FALLBACK_RELATIONSHIPS = {
    "H264->HEVC": (
        "HEVC", 0.30, 0.50, "low", "moderate", "substantial", 0.90,
    ),
    "MPEG4->HEVC": (
        "HEVC", 0.40, 0.60, "medium", "moderate", "substantial", 0.85,
    ),
    "MPEG2->HEVC": (
        "HEVC", 0.40, 0.60, "medium", "moderate", "substantial", 0.85,
    ),
    "MPEG2VIDEO->HEVC": (
        "HEVC", 0.40, 0.60, "medium", "moderate", "substantial", 0.85,
    ),
    "MPEG1VIDEO->HEVC": (
        "HEVC", 0.40, 0.60, "medium", "moderate", "substantial", 0.85,
    ),
    "VP9->AV1": (
        "AV1", 0.10, 0.25, "low", "high", "moderate", 0.80,
    ),
}

#: base opportunity score per benefit category
BENEFIT_BASE_SCORE = {
    "substantial": 0.65,
    "moderate": 0.45,
    "small": 0.30,
}

HIGH_VALUE_SOURCES = frozenset({"REMUX", "BLURAY"})

RISK_ESCALATION = {"low": "medium", "medium": "high", "high": "high"}

#: documented fallback typical bitrates for bitrate corroboration
#: when no knowledge service is available
FALLBACK_TYPICAL_BITRATE = {
    "H264_2160p": 30_000_000,
    "H264_1080p": 8_000_000,
    "H264_720p": 5_000_000,
    "H264_480p": 2_500_000,
    "HEVC_2160p": 20_000_000,
    "HEVC_1080p": 5_000_000,
    "HEVC_720p": 3_000_000,
}


def _height_key(height: int) -> str:
    if height >= 2160:
        return "2160p"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    return "480p"


class CodecRule(BaseDecisionRule):

    name = "codec_rule"

    # 2.1.0: fail-closed production behaviour. Required codec-efficiency
    # and relationship knowledge is authoritative; a missing production
    # value yields an explicit "knowledge unavailable" preservation
    # result instead of a silent untracked fallback.
    semantic_version = "2.1.0"

    def supports(
        self,
        context: AnalysisContext
    ) -> bool:

        return (
            context.get_domain_analysis(
                "video_codec"
            )
            is not None
        )

    def _efficient_targets(
        self,
        context: AnalysisContext,
        codec: str,
    ) -> tuple:
        """
        Candidate conversion targets for the current codec.

        Returns (targets, knowledge_resolved):
            targets           list of defensible targets, or None
            knowledge_resolved True when knowledge (or the test
                               fallback) established the value;
                               False when production knowledge is
                               missing and the value is UNKNOWN.
        """

        knowledge = self._knowledge(
            context,
            domain="video_codec",
            key=codec,
        )

        if knowledge is not None:
            targets = knowledge.value.get(
                "efficient_targets",
                [],
            )
            return list(targets), True

        if not self.has_knowledge_service:
            return list(
                FALLBACK_EFFICIENT_TARGETS.get(
                    codec,
                    [],
                )
            ), True

        # Production knowledge is present but the value is missing:
        # fail closed, the proposition cannot be established.
        return None, False

    def _relationship(
        self,
        context: AnalysisContext,
        codec: str,
        target: str,
    ):
        """
        Relationship knowledge for one codec conversion as a dict, or
        None when no defensible relationship exists. In production a
        missing relationship fails closed (no silent test fallback).
        """

        knowledge = self._knowledge(
            context,
            domain="codec_efficiency",
            key=f"{codec}->{target}",
        )

        if knowledge is not None:
            value = knowledge.value
            return {
                "target": target,
                "reduction_low": float(
                    value.get("storage_reduction_low", 0.0)
                ),
                "reduction_high": float(
                    value.get("storage_reduction_high", 0.0)
                ),
                "quality_risk": value.get(
                    "quality_risk", "medium"
                ),
                "encoding_cost": value.get(
                    "encoding_cost", "moderate"
                ),
                "benefit": value.get(
                    "expected_storage_reduction", "moderate"
                ),
                "confidence": float(
                    value.get("confidence", 0.85)
                ),
            }

        if not self.has_knowledge_service:

            fallback = FALLBACK_RELATIONSHIPS.get(
                f"{codec}->{target}",
                None,
            )

            if fallback is None:
                return None

            (
                fb_target,
                low,
                high,
                risk,
                cost,
                benefit,
                confidence,
            ) = fallback

            return {
                "target": fb_target,
                "reduction_low": low,
                "reduction_high": high,
                "quality_risk": risk,
                "encoding_cost": cost,
                "benefit": benefit,
                "confidence": confidence,
            }

        return None

    def _bitrate_corroboration(
        self,
        context: AnalysisContext,
        codec: str,
    ) -> bool:
        """
        Whether the current bitrate corroborates a codec-conversion
        proposition (the file uses materially more bitrate than
        typical for its codec and resolution).

        Corroboration is optional strengthening, not a required value:
        in production a missing bitrate-suitability entry simply means
        no corroboration bonus (the test fallback is never used in
        production).
        """

        bitrate = context.media.bitrate or 0
        height = context.media.height or 0

        if bitrate <= 0 or height <= 0:
            return False

        height_key = _height_key(height)

        knowledge = self._knowledge(
            context,
            domain="bitrate_suitability",
            key=f"{codec}_{height_key}",
        )

        if knowledge is not None:
            typical = knowledge.value.get(
                "typical_bitrate_bps",
                0,
            )
            return typical > 0 and bitrate > typical

        if not self.has_knowledge_service:

            fallback_typical = FALLBACK_TYPICAL_BITRATE.get(
                f"{codec}_{height_key}",
                0,
            )
            return (
                fallback_typical > 0
                and bitrate > fallback_typical
            )

        return False

    def evaluate(
        self,
        context: AnalysisContext
    ) -> List[DecisionSignal]:

        result, analysis = self._get_domain(
            context,
            "video_codec",
        )

        if not analysis:
            return []

        policy = context.policy_or_default()

        codec = analysis.selected_value

        codec_confidence = analysis.confidence

        targets, knowledge_resolved = self._efficient_targets(
            context,
            codec,
        )

        if not knowledge_resolved:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="codec_conversion",
                    reason=(
                        "codec efficiency knowledge unavailable"
                    ),
                    notes=(
                        f"Required codec-efficiency knowledge for "
                        f"{codec.upper()} is unavailable; no codec "
                        "conversion proposition can be established."
                    ),
                    confidence=codec_confidence,
                    result=result,
                    analysis=analysis,
                    domain="video_codec",
                    cost="none",
                    risk="unknown",
                )
            ]

        if not targets:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="codec_conversion",
                    reason="already efficient codec",
                    notes=(
                        f"{codec.upper()} is already an efficient "
                        "codec; no codec conversion opportunity."
                    ),
                    confidence=codec_confidence,
                    result=result,
                    analysis=analysis,
                    domain="video_codec",
                    cost="none",
                    risk="low",
                )
            ]

        if not policy.permit_codec_conversion:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="codec_conversion",
                    reason="user policy forbids codec conversion",
                    notes=(
                        f"{codec.upper()} could be converted, but "
                        "user policy forbids codec conversion."
                    ),
                    confidence=codec_confidence,
                    result=result,
                    analysis=analysis,
                    domain="video_codec",
                    cost="none",
                    risk="low",
                )
            ]

        # Evaluate each candidate target and keep the best defensible
        # proposition.
        best = None

        for target in targets:

            relationship = self._relationship(
                context,
                codec,
                target,
            )

            if relationship is None:
                continue

            reduction_mid = (
                relationship["reduction_low"]
                + relationship["reduction_high"]
            ) / 2

            size_bytes = context.media.size_bytes or 0

            # Owned conversion: percent and bytes from the
            # relationship midpoint (Phase 9 canonical
            # from_ratio construction).
            converted = SavingsConversion.from_ratio(
                reduction_mid,
                size_bytes,
            )

            expected_saving_percent = converted.percent

            expected_saved_bytes = converted.saved_bytes

            quality_risk = relationship["quality_risk"]

            source = self._domain_value(
                context,
                "source",
            )

            if source in HIGH_VALUE_SOURCES:
                quality_risk = RISK_ESCALATION.get(
                    quality_risk,
                    quality_risk,
                )

            candidate = {
                "target": relationship["target"],
                "expected_saving_percent": (
                    expected_saving_percent
                ),
                "expected_saved_bytes": expected_saved_bytes,
                "basis": converted.basis,
                "benefit": relationship["benefit"],
                "cost": relationship["encoding_cost"],
                "risk": quality_risk,
                "confidence": relationship["confidence"],
            }

            if best is None or candidate[
                "expected_saved_bytes"
            ] > best["expected_saved_bytes"]:
                best = candidate

        if best is None:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="codec_conversion",
                    reason="no defensible codec conversion target",
                    notes=(
                        f"No defensible conversion target exists "
                        f"for {codec.upper()}."
                    ),
                    confidence=codec_confidence,
                    result=result,
                    analysis=analysis,
                    domain="video_codec",
                    cost="none",
                    risk="low",
                )
            ]

        # A defensible proposition must be worthwhile and within the
        # acceptable risk under user policy.
        if not policy.worthwhile(
            best["expected_saving_percent"],
            best["expected_saved_bytes"],
        ):
            return [
                self._preserve_signal(
                    context=context,
                    proposition="codec_conversion",
                    reason=(
                        "expected storage saving too small to be "
                        "worthwhile"
                    ),
                    notes=(
                        f"Converting {codec.upper()} to "
                        f"{best['target']} is expected to save about "
                        f"{best['expected_saving_percent']:.0f}% "
                        f"({best['expected_saved_bytes']} bytes), "
                        "which is below the worthwhile threshold "
                        "under current user policy."
                    ),
                    confidence=codec_confidence,
                    result=result,
                    analysis=analysis,
                    domain="video_codec",
                    benefit=best["benefit"],
                    cost=best["cost"],
                    risk=best["risk"],
                )
            ]

        if not policy.risk_acceptable(best["risk"]):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="codec_conversion",
                    reason="quality risk too high under user policy",
                    notes=(
                        f"Converting {codec.upper()} to "
                        f"{best['target']} carries "
                        f"'{best['risk']}' quality risk, which "
                        "exceeds the acceptable risk under current "
                        "user policy."
                    ),
                    confidence=codec_confidence,
                    result=result,
                    analysis=analysis,
                    domain="video_codec",
                    benefit=best["benefit"],
                    cost=best["cost"],
                    risk=best["risk"],
                )
            ]

        bitrate_supports = self._bitrate_corroboration(
            context,
            codec,
        )

        # The emitted benefit category reflects the ACTUAL expected
        # absolute saving; the relationship knowledge category is
        # retained in the evidence for attribution.
        benefit = self.benefit_category(
            best["expected_saved_bytes"]
        )

        score = BENEFIT_BASE_SCORE.get(
            benefit,
            0.30,
        )

        if bitrate_supports:
            score += 0.10

        if (context.media.size_bytes or 0) >= (
            self.SUBSTANTIAL_SAVING_BYTES
        ):
            score += 0.05

        score = min(score, 0.85)

        confidence = min(
            0.95,
            round(
                best["confidence"] * codec_confidence,
                3,
            ),
        )

        return [
            DecisionSignal(
                rule=self.name,
                opportunity_score=round(score, 3),
                confidence=confidence,
                direction="optimize",
                proposition="codec_conversion",
                current_state=codec,
                target_state=best["target"],
                benefit=benefit,
                cost=best["cost"],
                risk=best["risk"],
                reason=(
                    f"{codec.upper()} to {best['target']} is "
                    f"expected to reduce storage by about "
                    f"{best['expected_saving_percent']:.0f}% "
                    f"({best['expected_saved_bytes']} bytes) at "
                    f"'{best['risk']}' quality risk."
                ),
                notes=(
                    f"{codec.upper()} codec has a worthwhile "
                    f"{best['target']} conversion opportunity."
                ),
                evidence={
                    "codec": codec,
                    "target_codec": best["target"],
                    "expected_storage_reduction_category": (
                        best["benefit"]
                    ),
                    "expected_saving_percent": (
                        best["expected_saving_percent"]
                    ),
                    "expected_saved_bytes": (
                        best["expected_saved_bytes"]
                    ),
                    "basis": best["basis"],
                    "assumption": "codec_relationship_midpoint",
                    "modelling_version": (
                        SavingsConversion.semantic_version
                    ),
                    "bitrate_corroboration": bitrate_supports,
                    "source": self._domain_value(
                        context,
                        "source",
                    ),
                    "size_bytes": context.media.size_bytes,
                },
                provenance=self._build_provenance(
                    result,
                    analysis,
                    "video_codec",
                ),
            )
        ]