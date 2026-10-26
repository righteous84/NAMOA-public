from app.experts.base_expert import BaseExpert
from app.models.expert_result import ExpertResult
from app.models.analysis_context import AnalysisContext

from app.models.expert_reasoning import (
    AgreementState,
    DomainAnalysis,
    ExpertData,
)


class QualityExpert(BaseExpert):
    """
    Evaluates overall media quality based on resolution,
    bitrate, and size.
    """

    name = "quality_expert"
    domain = "quality"

    semantic_version = "1.0.0"

    def analyze(
        self,
        context: AnalysisContext
    ) -> ExpertResult:

        confidence = 0.5
        rating = "UNKNOWN"

        if context.media.bitrate and context.media.height:

            if context.media.bitrate > 30000000:
                rating = "HIGH"
                confidence = 0.9

            elif context.media.bitrate > 12000000:
                rating = "MEDIUM"
                confidence = 0.7

            else:
                rating = "LOW"
                confidence = 0.6


        expert_data = ExpertData()

        expert_data.domains["quality"] = DomainAnalysis(
            selected_value=rating,
            confidence=confidence,
            agreement=AgreementState.SINGLE,
            has_conflict=False,
            uncertainty=round(
                1.0 - confidence,
                3,
            ),
        )


        observations = {
            "quality_rating": rating,
            "bitrate": context.media.bitrate,
            "confidence": confidence,
        }


        return ExpertResult(
            expert_name=self.name,
            observations=observations,
            confidence=confidence,
            notes="Quality estimation based on bitrate heuristics",
            expert_data=expert_data,
        )