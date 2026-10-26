from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """
    Immutable knowledge item.

    Represents a single versioned piece of domain knowledge.

    Examples:

        domain:
            video_codec

        key:
            HEVC

        payload:
            codec efficiency information
    """

    domain: str

    key: str

    value: Dict[str, Any]

    version: str