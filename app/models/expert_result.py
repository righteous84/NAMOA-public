"""
Standard output model for NAMOA Expert modules.

Experts analyse an AnalysisContext and return ExpertResult objects.

This model forms the shared contract between Experts and downstream
consumers such as the Decision Engine, persistence layer, and future
explainability tooling.
"""

from dataclasses import asdict, dataclass, field
import json
from typing import Any

from app.models.expert_reasoning import ExpertData


@dataclass(slots=True)
class ExpertResult:
    """
    Standard output from an Expert.

    Pipeline philosophy:

        Observations
            ↓
        Human explanation (notes)
            ↓
        Structured reasoning (expert_data)
    """

    expert_name: str

    observations: dict[str, Any]

    confidence: float = 0.0

    notes: str = ""

    expert_data: ExpertData = field(
        default_factory=ExpertData
    )

    knowledge_set_ids: set[int] = field(
        default_factory=set
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expert_name": self.expert_name,
            "observations": self.observations,
            "confidence": self.confidence,
            "notes": self.notes,
            "expert_data": asdict(self.expert_data),
            "knowledge_set_ids": sorted(
                self.knowledge_set_ids
            ),
        }

    def to_snapshot(self) -> dict[str, Any]:
        """
        Produce an immutable, JSON-safe snapshot suitable for
        provenance persistence.
        """

        return {
            "expert_name": self.expert_name,
            "confidence": self.confidence,
            "observations_json": json.dumps(
                self.observations
            ),
            "notes": self.notes,
            "expert_data_json": json.dumps(
                asdict(self.expert_data)
            ),
            "knowledge_set_ids_json": json.dumps(
                sorted(self.knowledge_set_ids)
            ),
        }
