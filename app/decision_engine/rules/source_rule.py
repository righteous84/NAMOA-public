from typing import List

from app.decision_engine.decision_base_rule import (
    BaseDecisionRule,
)

from app.decision_engine.signals.decision_signal import (
    DecisionSignal,
)

from app.models.analysis_context import (
    AnalysisContext,
)


#: high-value / lossless sources whose quality warrants preservation
HIGH_VALUE_SOURCES = frozenset({"REMUX", "BLURAY"})


class SourceRule(BaseDecisionRule):

    name = "source_rule"

    # 2.0.0: source quality participates in decisions as preservation
    # intelligence, not as an interchangeable optimisation trigger.
    # A low-quality source is NOT by itself an opportunity, and
    # sources with identical resolution are NOT interchangeable. A
    # high-value source warrants a documented preservation warning
    # that other rules consume as risk context.
    semantic_version = "2.0.0"

    def supports(
        self,
        context: AnalysisContext,
    ) -> bool:

        return (
            context.get_domain_analysis(
                "source"
            )
            is not None
        )

    def evaluate(
        self,
        context: AnalysisContext,
    ) -> List[DecisionSignal]:

        result, analysis = self._get_domain(
            context,
            "source",
        )

        if analysis is None:
            return []

        source = analysis.selected_value

        if source not in HIGH_VALUE_SOURCES:
            return []

        return [
            self._preserve_signal(
                context=context,
                proposition="source_preservation",
                reason="source quality warrants preservation",
                notes=(
                    f"The '{source}' source is high value; changes "
                    "carry preservation risk and require stronger "
                    "justification."
                ),
                confidence=analysis.confidence,
                result=result,
                analysis=analysis,
                domain="source",
                risk="low",
            )
        ]