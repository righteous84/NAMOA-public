from typing import List

from app.decision_engine.decision_base_rule import (
    BaseDecisionRule
)

from app.models.analysis_context import (
    AnalysisContext
)

from app.decision_engine.signals.decision_signal import (
    DecisionSignal
)


class HDRRule(BaseDecisionRule):

    name = "hdr_rule"

    # 2.0.0: HDR preservation is now policy-aware. HDR characteristics
    # participate in optimisation reasoning as a preservation
    # requirement: unless user policy explicitly permits changing HDR,
    # optimisation must preserve HDR. A codec conversion that preserves
    # HDR remains a candidate; the HDR constraint documents the
    # preservation requirement without diluting opportunity magnitude.
    semantic_version = "2.0.0"

    def supports(
        self,
        context: AnalysisContext
    ) -> bool:

        return (
            context.get_domain_analysis(
                "hdr"
            )
            is not None
        )

    def evaluate(
        self,
        context: AnalysisContext
    ) -> List[DecisionSignal]:

        result, analysis = self._get_domain(
            context,
            "hdr",
        )

        if not analysis:
            return []

        policy = context.policy_or_default()

        hdr = analysis.selected_value

        if hdr == "SDR":
            return []

        # HDR is a preservation requirement unless user policy
        # explicitly permits changing HDR characteristics.
        if not policy.preserve_hdr:
            return []

        return [
            self._preserve_signal(
                context=context,
                proposition="hdr_preservation",
                reason="HDR preservation required",
                notes=(
                    f"{hdr} detected - HDR preservation required "
                    "unless user policy explicitly permits changing "
                    "HDR characteristics."
                ),
                confidence=analysis.confidence,
                result=result,
                analysis=analysis,
                domain="hdr",
                risk="low",
            )
        ]