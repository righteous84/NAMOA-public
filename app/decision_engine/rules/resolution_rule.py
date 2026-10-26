from typing import List

from app.decision_engine.decision_base_rule import BaseDecisionRule
from app.models.analysis_context import AnalysisContext
from app.decision_engine.signals.decision_signal import DecisionSignal
from app.services.savings_conversion import SavingsConversion


LOW_QUALITY_SOURCES = frozenset({"WEBRIP", "HDTV", "DVD"})

#: resolution reduction is considered only for these resolutions
REDUCTION_CANDIDATES = frozenset({"2160p", "1080p"})

#: the proposed target resolution for each candidate
NEXT_LOWER_RESOLUTION = {
    "2160p": "1080p",
    "1080p": "720p",
}

#: documented factor: a bitrate below this fraction of the typical
#: value for the resolution suggests the resolution is inflated
INFLATED_BITRATE_FACTOR = 0.6


class ResolutionRule(BaseDecisionRule):

    name = "resolution_rule"

    # 2.1.0: fail-closed production behaviour. Bitrate-based evidence
    # of an inflated resolution comes from maintained Knowledge; a
    # missing production value makes that evidence path unavailable
    # rather than substituting an untracked constant.
    # 2.2.0: the rule enforces the established risk_acceptable policy
    # gate itself. A resolution reduction always carries high quality
    # risk, so under any policy whose ceiling is below high the rule
    # emits an explicit preservation conclusion instead of relying on
    # downstream FusionEngine suppression.
    semantic_version = "2.2.0"

    def supports(
        self,
        context: AnalysisContext
    ) -> bool:

        return (
            context.get_domain_analysis(
                "resolution"
            )
            is not None
        )

    def _typical_bitrate(
        self,
        context: AnalysisContext,
        height_key: str,
    ) -> int:
        """
        Typical bitrate reference for the resolution, from the
        maintained bitrate_suitability UNKNOWN_* entries (production
        Knowledge) or documented test fallback when no knowledge
        service is present. In production a missing value returns 0
        (that evidence path is unavailable; it is never silently
        substituted from an untracked constant).
        """

        knowledge = self._knowledge(
            context,
            domain="bitrate_suitability",
            key=f"UNKNOWN_{height_key}",
        )

        if knowledge is not None:
            return int(
                knowledge.value.get(
                    "typical_bitrate_bps",
                    0,
                )
            )

        if not self.has_knowledge_service:

            fallback = {
                "2160p": 30_000_000,
                "1080p": 8_000_000,
                "720p": 5_000_000,
                "480p": 2_500_000,
            }
            return fallback.get(height_key, 0)

        return 0

    def _evidence_of_inflated_resolution(
        self,
        context: AnalysisContext,
        height_key: str,
    ) -> bool:
        """
        Defensible evidence that the resolution is inflated: either a
        low-quality source or a bitrate well below the typical value
        for the resolution.
        """

        source = self._domain_value(
            context,
            "source",
        )

        if source in LOW_QUALITY_SOURCES:
            return True

        bitrate = context.media.bitrate or 0

        typical = self._typical_bitrate(
            context,
            height_key,
        )

        if bitrate > 0 and typical > 0:
            return bitrate < typical * INFLATED_BITRATE_FACTOR

        return False

    def evaluate(
        self,
        context: AnalysisContext
    ) -> List[DecisionSignal]:

        result, analysis = self._get_domain(
            context,
            "resolution",
        )

        if not analysis:
            return []

        policy = context.policy_or_default()

        resolution = analysis.selected_value

        if resolution not in REDUCTION_CANDIDATES:
            return []

        height = context.media.height or 0

        height_key = (
            "2160p" if height >= 2160
            else "1080p" if height >= 1080
            else "720p" if height >= 720
            else "480p"
        )

        target = NEXT_LOWER_RESOLUTION.get(
            resolution,
        )

        provenance = self._build_provenance(
            result,
            analysis,
            "resolution",
        )

        if not policy.permit_resolution_reduction:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="resolution_reduction",
                    reason=(
                        "user policy preserves the current "
                        "resolution"
                    ),
                    notes=(
                        f"{resolution} resolution is preserved; "
                        "user policy does not permit resolution "
                        "reduction."
                    ),
                    confidence=analysis.confidence,
                    result=result,
                    analysis=analysis,
                    domain="resolution",
                    cost="none",
                    risk="low",
                )
            ]

        if target is None:
            return []

        if not self._evidence_of_inflated_resolution(
            context,
            height_key,
        ):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="resolution_reduction",
                    reason=(
                        "no evidence that the resolution is inflated"
                    ),
                    notes=(
                        f"No evidence suggests {resolution} is "
                        "inflated; resolution reduction is not "
                        "defensible."
                    ),
                    confidence=analysis.confidence,
                    result=result,
                    analysis=analysis,
                    domain="resolution",
                    cost="none",
                    risk="low",
                )
            ]

        size_bytes = context.media.size_bytes or 0

        # Documented rough estimate: downscaling one step typically
        # reduces video storage by roughly half. The value stays
        # owned here as resolution-domain intelligence; only the
        # percent-to-bytes conversion is owned centrally (Phase 9
        # canonical from_percent construction).
        expected_saving_percent = 50.0

        converted = SavingsConversion.from_percent(
            expected_saving_percent,
            size_bytes,
        )

        expected_saved_bytes = converted.saved_bytes

        if not policy.worthwhile(
            expected_saving_percent,
            expected_saved_bytes,
        ):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="resolution_reduction",
                    reason=(
                        "expected storage saving too small to be "
                        "worthwhile"
                    ),
                    notes=(
                        f"Reducing {resolution} to {target} would "
                        f"save about {expected_saving_percent:.0f}% "
                        f"({expected_saved_bytes} bytes), which is "
                        "below the worthwhile threshold under "
                        "current user policy."
                    ),
                    confidence=analysis.confidence,
                    result=result,
                    analysis=analysis,
                    domain="resolution",
                    benefit="none",
                    cost="moderate",
                    risk="high",
                )
            ]

        if not policy.risk_acceptable("high"):

            return [
                self._preserve_signal(
                    context=context,
                    proposition="resolution_reduction",
                    reason=(
                        "quality risk too high under user policy"
                    ),
                    notes=(
                        f"Reducing {resolution} to {target} "
                        f"carries 'high' quality risk, which "
                        "exceeds the acceptable risk under "
                        "current user policy."
                    ),
                    confidence=analysis.confidence,
                    result=result,
                    analysis=analysis,
                    domain="resolution",
                    benefit="none",
                    cost="moderate",
                    risk="high",
                )
            ]

        return [
            DecisionSignal(
                rule=self.name,
                opportunity_score=0.45,
                confidence=analysis.confidence,
                direction="optimize",
                proposition="resolution_reduction",
                current_state=resolution,
                target_state=target,
                benefit="moderate",
                cost="moderate",
                risk="high",
                reason=(
                    f"{resolution} appears inflated for its source "
                    f"and bitrate; reducing to {target} is expected "
                    f"to save about {expected_saving_percent:.0f}% "
                    f"({expected_saved_bytes} bytes) with a "
                    "significant quality trade-off."
                ),
                notes=(
                    f"{resolution} resolution reduction proposition "
                    f"({target} target)"
                ),
                evidence={
                    "resolution": resolution,
                    "target_resolution": target,
                    "expected_saving_percent": (
                        expected_saving_percent
                    ),
                    "expected_saved_bytes": expected_saved_bytes,
                    "assumption": "resolution_step_estimate_50.0",
                    "basis": converted.basis,
                    "modelling_version": (
                        SavingsConversion.semantic_version
                    ),
                    "size_bytes": size_bytes,
                },
                provenance=provenance,
            )
        ]