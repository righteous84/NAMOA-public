"""
Resolution Expert.

Responsible for interpreting video resolution.

Produces:

    ExpertResult
        |
        ExpertData
            |
            resolution domain


Experts never:
    - mutate MediaContext
    - decide optimisation actions
    - access repositories directly
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



class ResolutionExpert(BaseExpert):

    name = "resolution_expert"

    domain = "resolution"

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


        width = context.media.width
        height = context.media.height


        confidence = 0.0

        resolution_key = None


        if height:


            if height >= 2160:
                resolution_key = "2160p"

            elif height >= 1080:
                resolution_key = "1080p"

            elif height >= 720:
                resolution_key = "720p"

            else:
                resolution_key = "480p"



            knowledge = self.knowledge_service.get(
                context=context,
                domain="resolution",
                key=resolution_key,
            )


            if knowledge:

                confidence = knowledge.value.get(
                    "confidence",
                    0.9,
                )

            else:

                confidence = 0.5



        expert_data = ExpertData()



        if resolution_key:


            expert_data.domains["resolution"] = DomainAnalysis(

                selected_value=resolution_key,

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

                "width": width,

                "height": height,

                "resolution": resolution_key,

            },

            confidence=confidence,

            notes=(

                f"Resolution identified as {resolution_key}"

                if resolution_key

                else "No resolution detected"

            ),

            expert_data=expert_data,
        )