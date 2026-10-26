from typing import List, Optional

from app.models.analysis_context import AnalysisContext
from app.models.opportunity_assessment import OpportunityAssessment

from app.decision_engine.decision_base_rule import BaseDecisionRule
from app.decision_engine.fusion_engine.fusion_engine import FusionEngine
from app.decision_engine.signals.decision_signal import DecisionSignal

from app.utils.logger import logger


class DecisionEngine:
    """
    Executes decision rules and produces a fused optimisation assessment.

    Flow:

        AnalysisContext
              |
              v
        Decision Rules
              |
              v
        Decision Signals
              |
              v
        Fusion Engine
              |
              v
        OpportunityAssessment


    DecisionEngine is stateless.

    It does not:
        - mutate AnalysisContext
        - store assessments
        - own execution state

    The caller owns the returned assessment.
    """

    # Semantic version of the Decision Engine orchestration/decision
    # semantics. A semantic change MUST bump this version.
    #
    # 1.1.0: the engine now passes the active user policy to fusion so
    # reconciliation can enforce the policy risk ceiling.
    semantic_version = "1.1.0"


    def __init__(
        self,
        rules: List[BaseDecisionRule]
    ):
        self.rules = rules
        self.fusion = FusionEngine()



    def evaluate(
        self,
        context: AnalysisContext
    ) -> Optional[OpportunityAssessment]:

        signals: List[DecisionSignal] = []


        for rule in self.rules:

            # -------------------------
            # SUPPORT CHECK
            # -------------------------

            try:

                supports = rule.supports(context)


                logger.debug(
                    f"RULE: {rule.name} → supports={supports}"
                )


                if not supports:
                    continue


            except Exception as e:

                logger.warning(
                    f"supports() failed in "
                    f"{getattr(rule, 'name', 'unknown')}: {e}"
                )

                continue



            # -------------------------
            # RULE EXECUTION
            # -------------------------

            try:

                result = rule.evaluate(
                    context
                )


                if result:
                    signals.extend(
                        result
                    )


            except Exception as e:

                logger.warning(
                    f"Error in rule "
                    f"{getattr(rule, 'name', 'unknown')}: {e}"
                )

                continue



        # -------------------------
        # DEBUG ONLY
        # -------------------------

        logger.debug(
            f"ENGINE SIGNALS: {signals}"
        )


        # -------------------------
        # FUSION
        # -------------------------

        assessment = self.fusion.evaluate(
            signals,
            policy=context.policy_or_default(),
        )


        return assessment