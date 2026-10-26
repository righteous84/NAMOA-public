from typing import List

from app.decision_engine.decision_base_rule import BaseDecisionRule
from app.decision_engine.signals.decision_signal import DecisionSignal

from app.models.analysis_context import AnalysisContext


#: containers that justify a remux proposition (compatibility /
#: handling, NOT a storage optimisation)
REMUX_CANDIDATES = frozenset({"AVI", "MPEGTS"})

#: the proposed target container for each candidate
REMUX_TARGET = {
    "AVI": "MKV",
    "MPEGTS": "MKV",
}


class ContainerRule(BaseDecisionRule):

    name = "container_rule"

    # 2.0.0: container changes are represented as the compatibility /
    # handling benefit they actually pursue. A container change is NOT
    # a storage-saving optimisation unless evidence supports that
    # conclusion. User policy must permit the container change.
    semantic_version = "2.0.0"

    def supports(
        self,
        context: AnalysisContext,
    ) -> bool:

        return (
            context.get_domain_analysis(
                "container"
            )
            is not None
        )

    def evaluate(
        self,
        context: AnalysisContext,
    ) -> List[DecisionSignal]:

        result, analysis = self._get_domain(
            context,
            "container",
        )

        if analysis is None:
            return []

        policy = context.policy_or_default()

        container = analysis.selected_value

        if container not in REMUX_CANDIDATES:
            return []

        target = REMUX_TARGET.get(
            container,
            "MKV",
        )

        if not policy.permit_container_change:

            return [
                self._preserve_signal(
                    context=context,
                    proposition="container_remux",
                    reason="user policy forbids container changes",
                    notes=(
                        f"{container} could be remuxed to {target}, "
                        "but user policy forbids container changes."
                    ),
                    confidence=analysis.confidence,
                    result=result,
                    analysis=analysis,
                    domain="container",
                    cost="none",
                    risk="low",
                )
            ]

        return [
            DecisionSignal(
                rule=self.name,
                opportunity_score=0.40,
                confidence=analysis.confidence,
                direction="remux",
                proposition="container_remux",
                current_state=container,
                target_state=target,
                benefit="compatibility",
                cost="low",
                risk="low",
                reason=(
                    f"The {container} container is legacy; remuxing "
                    f"to {target} improves compatibility and "
                    "handling. This is not a storage-saving "
                    "optimisation."
                ),
                notes=(
                    f"{container} container may benefit from "
                    f"remuxing to {target}."
                ),
                evidence={
                    "container": container,
                    "target_container": target,
                    "benefit": "compatibility",
                    "storage_benefit": "none",
                },
                provenance=self._build_provenance(
                    result,
                    analysis,
                    "container",
                ),
            )
        ]