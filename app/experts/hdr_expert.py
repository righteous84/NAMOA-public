"""
HDR Expert.

Responsible for interpreting HDR format information.

Produces:

    ExpertResult
        |
        ExpertData
            |
            hdr domain

Experts never:
    - modify MediaContext
    - access repositories directly
    - create optimisation decisions
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


class HDRExpert(BaseExpert):

    name = "hdr_expert"

    domain = "hdr"

    semantic_version = "1.0.0"


    def __init__(
        self,
        knowledge_service: KnowledgeService,
    ):
        self.knowledge_service = knowledge_service


    def normalize_hdr(
        self,
        hdr_format: str | None,
    ) -> str:

        if not hdr_format:
            return "SDR"

        value = hdr_format.upper()


        if (
            "DOLBY" in value
            or "DV" in value
            or "DVHE" in value
        ):
            return "DOLBY_VISION"


        if (
            "2084" in value
            or "HDR10" in value
            or "PQ" in value
        ):
            return "HDR10"


        if (
            "HLG" in value
            or "B67" in value
        ):
            return "HLG"


        return "UNKNOWN"



    def analyze(
        self,
        context: AnalysisContext,
    ) -> ExpertResult:


        hdr_key = self.normalize_hdr(
            context.media.hdr_format
        )


        knowledge = self.knowledge_service.get(
            context=context,
            domain="hdr",
            key=hdr_key,
        )


        if knowledge is None:
            confidence = 0.5 if hdr_key != "UNKNOWN" else 0.0
        else:
            confidence = knowledge.value.get(
                "confidence",
                0.5,
            )


        expert_data = ExpertData()


        expert_data.domains["hdr"] = DomainAnalysis(

            selected_value=hdr_key,

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
                "hdr_format":
                    context.media.hdr_format,

                "normalized_hdr":
                    hdr_key,
            },

            confidence=confidence,

            notes=(
                f"HDR interpreted as {hdr_key}"
            ),

            expert_data=expert_data,
        )