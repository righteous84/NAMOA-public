"""
Codec Expert.

Responsible for interpreting video codec information.

Produces:
    ExpertResult
        |
        ExpertData
            |
            video_codec domain

Experts never modify MediaContext.
"""

from app.knowledge import KnowledgeService
from app.experts.base_expert import BaseExpert
from app.models.expert_result import ExpertResult
from app.models.expert_reasoning import (
    AgreementState,
    DomainAnalysis,
    ExpertData,
)
from app.models.analysis_context import AnalysisContext


class CodecExpert(BaseExpert):

    name = "codec_expert"
    domain = "video_codec"

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

        codec = context.media.video_codec

        confidence = 0.0

        if codec:

            codec = codec.upper()

            knowledge = self.knowledge_service.get(
                context=context,
                domain="video_codec",
                key=codec,
            )

            if knowledge is not None:

                confidence = knowledge.value.get(
                    "confidence",
                    0.5,
                )

            else:

                confidence = 0.5

        expert_data = ExpertData()


        if codec:

            expert_data.domains["video_codec"] = DomainAnalysis(
                selected_value=codec,
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
                "video_codec": codec,
            },

            confidence=confidence,

            notes=(
                f"Video codec identified as {codec}"
                if codec
                else "No video codec detected"
            ),

            expert_data=expert_data,
        )