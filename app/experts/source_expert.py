"""
Source Expert.

Responsible for interpreting media source information.

Produces:

    ExpertResult
        |
        ExpertData
            |
            source domain

SourceExpert does not recommend optimisation.

That belongs to SourceRule.
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


class SourceExpert(BaseExpert):

    name = "source_expert"

    domain = "source"

    semantic_version = "1.0.0"


    def __init__(
        self,
        knowledge_service: KnowledgeService,
    ):
        self.knowledge_service = knowledge_service


    def _normalise_source(
        self,
        source: str | None,
    ) -> str:

        if not source:
            return "UNKNOWN"

        value = source.upper()

        aliases = {

            "WEBDL": "WEB-DL",

            "WEB-DL":
                "WEB-DL",

            "WEBRIP":
                "WEBRIP",

            "WEB-RIP":
                "WEBRIP",

            "BLURAY":
                "BLURAY",

            "BLU-RAY":
                "BLURAY",

            "BDREMUX":
                "REMUX",

            "REMUX":
                "REMUX",

            "DVD":
                "DVD",

            "HDTV":
                "HDTV",

        }

        return aliases.get(
            value,
            value,
        )


    def analyze(
        self,
        context: AnalysisContext,
    ) -> ExpertResult:

        source = self._normalise_source(
            context.media.source
        )

        confidence = 0.0


        knowledge = self.knowledge_service.get(
            context=context,
            domain="source",
            key=source,
        )


        if knowledge:

            confidence = knowledge.value.get(
                "confidence",
                0.0,
            )


        expert_data = ExpertData()


        expert_data.domains["source"] = DomainAnalysis(

            selected_value=source,

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

                "source": source,

                "raw_source":
                    context.media.source,

            },

            confidence=confidence,

            notes=(
                f"Source identified as {source}"
            ),

            expert_data=expert_data,
        )