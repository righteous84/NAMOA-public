from dataclasses import dataclass, field
from typing import Dict

from app.knowledge.knowledge_entry import KnowledgeEntry


@dataclass(frozen=True, slots=True)
class KnowledgeSet:
    """
    Immutable collection of knowledge entries.

    A KnowledgeSet represents one version of a knowledge domain.
    """

    name: str

    version: str

    entries: Dict[str, KnowledgeEntry] = field(
        default_factory=dict
    )


    def get(
        self,
        key: str
    ) -> KnowledgeEntry | None:

        return self.entries.get(key)