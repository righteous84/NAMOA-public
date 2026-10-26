"""
Audio Expert.

Responsible for interpreting audio codec information.

Produces:
    ExpertResult
        |
        ExpertData
            |
            audio domain

Experts never:
    - modify MediaContext
    - perform optimisation decisions
    - access repositories directly
"""

from app.knowledge import KnowledgeService

from app.experts.base_expert import BaseExpert

from app.models.expert_result import (
    ExpertResult,
)

from app.models.expert_reasoning import (
    AgreementState,
    DomainAnalysis,
    ExpertData,
)

from app.models.analysis_context import (
    AnalysisContext,
)


class AudioExpert(BaseExpert):

    name = "audio_expert"

    domain = "audio"

    semantic_version = "1.0.0"


    def __init__(
        self,
        knowledge_service: KnowledgeService,
    ):
        self.knowledge_service = knowledge_service


    def analyze(
        self,
        context: AnalysisContext,
    ) -> ExpertResult:

        codec = context.media.audio_codec

        confidence = 0.0

        audio_type = None


        if codec:

            codec = codec.upper()

            audio_type = codec


            knowledge = self.knowledge_service.get(
                context=context,
                domain="audio",
                key=codec,
            )


            if knowledge:

                confidence = knowledge.value.get(
                    "confidence",
                    0.5,
                )

            else:

                confidence = 0.5


        expert_data = ExpertData()


        if audio_type:

            expert_data.domains["audio"] = DomainAnalysis(

                selected_value=audio_type,

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
                "audio_type": audio_type,
                "channels": context.media.audio_channels,
            },

            confidence=confidence,

            notes=(
                f"Audio codec identified as {audio_type}"
                if audio_type
                else "No audio codec detected"
            ),

            expert_data=expert_data,
        )