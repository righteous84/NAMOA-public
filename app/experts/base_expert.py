"""
Base classes for NAMOA Expert modules.

Experts consume AnalysisContext.

They receive:
    - immutable media facts
    - collected evidence
    - runtime analysis state

Experts never:
    - mutate MediaContext
    - perform IO
    - write to database
"""

from abc import ABC, abstractmethod

from app.models.analysis_context import AnalysisContext
from app.models.expert_result import ExpertResult


class BaseExpert(ABC):
    """
    Base interface for all NAMOA experts.

    Every expert owns exactly one intelligence domain.
    """

    name: str = "base_expert"

    domain: str = "base"

    # Semantic version of this Expert's interpretation behaviour.
    # A semantic change (meaning, calculation, threshold, classification
    # or confidence behaviour) MUST bump this version so historical
    # results are not ambiguously attributed to multiple meanings.
    semantic_version: str = "0.0.0"


    @abstractmethod
    def analyze(
        self,
        context: AnalysisContext,
    ) -> ExpertResult:
        """
        Analyse runtime context and return intelligence.
        """
        pass


    def supports(
        self,
        context: AnalysisContext
    ) -> bool:
        """
        Optional execution filter.

        Default:
        every expert supports every context.
        """

        return True