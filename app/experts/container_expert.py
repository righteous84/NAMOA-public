"""
Container Expert.

Responsible for interpreting media container formats.

Produces:

    ExpertResult
        |
        ExpertData
            |
            container domain

ContainerExpert does not recommend remuxing.

That belongs to ContainerRule.
"""

from app.experts.base_expert import BaseExpert

from app.knowledge import KnowledgeService

from app.models.analysis_context import AnalysisContext

from app.models.expert_result import ExpertResult

from app.models.expert_reasoning import (
    AgreementState,
    DomainAnalysis,
    ExpertData,
)


class ContainerExpert(BaseExpert):

    name = "container_expert"

    domain = "container"

    semantic_version = "1.0.0"

    def __init__(
        self,
        knowledge_service: KnowledgeService,
    ):
        self.knowledge_service = knowledge_service


    def _normalise_container(
        self,
        container: str | None,
    ) -> str:

        if not container:
            return "UNKNOWN"

        value = container.lower()

        #
        # FFprobe returns format_name,
        # which may contain aliases.
        #

        if "matroska" in value:
            return "MATROSKA"

        if "mp4" in value or "mov" in value:
            return "MP4"

        if "avi" in value:
            return "AVI"

        if "mpegts" in value:
            return "MPEGTS"

        return "UNKNOWN"


    def analyze(
        self,
        context: AnalysisContext,
    ) -> ExpertResult:

        selected = self._normalise_container(
            context.media.container
        )

        confidence = 0.0

        knowledge = self.knowledge_service.get(
            context=context,
            domain="container",
            key=selected,
        )

        if knowledge:

            confidence = knowledge.value.get(
                "confidence",
                0.0,
            )

        expert_data = ExpertData()

        expert_data.domains["container"] = DomainAnalysis(

            selected_value=selected,

            confidence=confidence,

            agreement=AgreementState.SINGLE,

            has_conflict=False,

            uncertainty=round(
                1.0 - confidence,
                3,
            ),
        )

        return ExpertResult(

            expert_name=self.name,

            observations={

                "container": selected,

                "raw_container":
                    context.media.container,

            },

            confidence=confidence,

            notes=f"Container identified as {selected}",

            expert_data=expert_data,
        )