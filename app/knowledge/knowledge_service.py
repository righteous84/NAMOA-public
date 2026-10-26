from abc import ABC, abstractmethod

from app.models.analysis_context import AnalysisContext
from app.knowledge.knowledge_entry import KnowledgeEntry


class KnowledgeService(ABC):
    """
    Read-only interface for accessing versioned knowledge.

    Implementations may record provenance when an
    AnalysisContext is supplied.
    """

    @abstractmethod
    def get(
        self,
        *,
        domain: str,
        key: str,
        context: AnalysisContext | None = None,
    ) -> KnowledgeEntry | None:
        """
        Retrieve knowledge.

        If an AnalysisContext is supplied, implementations
        should record provenance automatically.

        Returns None if the requested knowledge does not exist.
        """
        pass