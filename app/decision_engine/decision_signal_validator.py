from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StandardizedSignal:
    rule: str
    opportunity_score: float
    confidence: float
    weight: float
    direction: str
    metadata: dict[str, Any]