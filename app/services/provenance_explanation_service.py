from app.models.provenance_explanation import (
    ProvenanceExplanation
)


class ProvenanceExplanationService:
    """
    Converts persisted provenance into human-readable
    explanations.

    This service:

    - consumes AnalysisProvenance only
    - never accesses databases
    - never recalculates decisions
    - never modifies analytical results

    It is a presentation layer.
    """


    def explain(
        self,
        provenance,
    ) -> ProvenanceExplanation:

        assessment = (
            provenance.opportunity_assessment
        )


        if assessment:

            summary = (
                f"NAMOA identified a "
                f"{assessment.opportunity} "
                f"optimisation opportunity "
                f"with a score of "
                f"{assessment.opportunity_score:.2f}."
            )

        else:

            summary = (
                "NAMOA completed analysis but "
                "identified no optimisation opportunity."
            )


        expert_contributions = [
            (
                f"{expert.expert_name} concluded "
                f"with confidence "
                f"{expert.confidence:.2f}."
            )
            for expert
            in provenance.expert_results
        ]


        evidence_summary = [
            (
                f"{evidence.domain}: "
                f"{evidence.value} "
                f"(confidence "
                f"{evidence.confidence:.2f})"
            )
            for evidence
            in provenance.evidence
        ]


        decision_summary = [
            (
                f"{signal.rule} produced "
                f"a {signal.direction} signal "
                f"with score "
                f"{signal.opportunity_score:.2f}."
            )
            for signal
            in provenance.decision_signals
        ]


        knowledge_summary = [
            (
                f"Knowledge set "
                f"{usage.knowledge_set_id}"
                " was consulted."
            )
            for usage
            in provenance.knowledge_usage
        ]


        confidence_summary = (
            f"Assessment confidence: "
            f"{assessment.confidence:.2f}"
            if assessment
            else
            "No assessment confidence available."
        )


        return ProvenanceExplanation(

            summary=summary,

            expert_contributions=(
                expert_contributions
            ),

            evidence_summary=(
                evidence_summary
            ),

            decision_summary=(
                decision_summary
            ),

            knowledge_summary=(
                knowledge_summary
            ),

            confidence_summary=(
                confidence_summary
            ),
        )