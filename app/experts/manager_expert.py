"""
Expert Manager.

Responsible only for orchestrating Expert execution.

Architectural guarantees:

- Each Expert owns exactly one intelligence domain.
- Only one Expert may own a given domain.
- Experts are executed independently.
- Expert failures do not stop the pipeline.
- Knowledge usage is attributed to the Expert that caused it.
"""

from typing import List

from app.experts.base_expert import BaseExpert
from app.models.analysis_context import AnalysisContext
from app.models.expert_result import ExpertResult


class ExpertManager:

    def __init__(
        self,
        experts: List[BaseExpert]
    ):
        self.experts = experts

        # ---------------------------------
        # Validate expert ownership.
        #
        # Every intelligence domain must
        # have exactly one owning Expert.
        # ---------------------------------

        domains = [
            expert.domain
            for expert in experts
        ]

        duplicates = {
            domain
            for domain in domains
            if domains.count(domain) > 1
        }

        if duplicates:
            raise ValueError(
                "Multiple experts registered for domain(s): "
                + ", ".join(sorted(duplicates))
            )

    def run(
        self,
        context: AnalysisContext
    ) -> List[ExpertResult]:

        results = []

        for expert in self.experts:

            if hasattr(expert, "supports"):

                if not expert.supports(context):
                    continue

            # ---------------------------------
            # Start a fresh attribution scope
            # for this Expert.
            #
            # Run-level knowledge usage remains
            # cumulative in AnalysisContext.
            # ---------------------------------

            context.begin_expert_knowledge_scope()

            try:

                result = expert.analyze(
                    context
                )

                # ---------------------------------
                # Attribute every knowledge set
                # consulted during this Expert's
                # execution.
                #
                # This is independent of whether
                # another Expert consulted the same
                # knowledge set previously.
                # ---------------------------------

                result.knowledge_set_ids = (
                    context.end_expert_knowledge_scope()
                )

                results.append(
                    result
                )

            except Exception as e:

                # Close the attribution scope even
                # when the Expert fails.
                context.end_expert_knowledge_scope()

                results.append(
                    ExpertResult(
                        expert_name=getattr(
                            expert,
                            "name",
                            "unknown_expert"
                        ),
                        observations={},
                        confidence=0.0,
                        notes=f"Expert failed: {str(e)}",
                    )
                )

        return results