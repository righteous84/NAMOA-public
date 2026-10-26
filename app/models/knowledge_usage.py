from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeUsage:
    """
    Runtime provenance record.

    Represents a knowledge set consulted during a single
    analysis run.

    The database owns all version information.

    Runtime stores only immutable identifiers.
    """

    knowledge_set_id: int