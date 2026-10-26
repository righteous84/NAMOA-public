from app.database.repositories.knowledge_repository import (
    KnowledgeRepository,
)

from app.knowledge.knowledge_service import (
    KnowledgeService,
)

from app.knowledge.knowledge_entry import (
    KnowledgeEntry,
)

from app.models.analysis_context import AnalysisContext


class DatabaseKnowledgeService(KnowledgeService):
    """
    SQLite-backed implementation of KnowledgeService.
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
    ):
        self.repository = repository

    def get(
        self,
        *,
        domain: str,
        key: str,
        context: AnalysisContext | None = None,
    ) -> KnowledgeEntry | None:

        result = self.repository.get_entry(
            set_name=domain,
            domain=domain,
            key=key,
        )

        if result is None:
            return None

        knowledge_set_id, knowledge = result

        if context is not None:
            context.record_knowledge_usage(
                knowledge_set_id
            )

        return knowledge