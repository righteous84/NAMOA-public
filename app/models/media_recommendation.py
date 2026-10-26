from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class MediaRecommendation:
    action: str
    confidence: float
    score: float
    estimated_savings: Dict[str, Any]
    reasoning: List[str]

@dataclass(slots=True)
class Recommendation:
    action: str = "UNKNOWN"
    reason: str = ""
    estimated_space_saving: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "estimated_space_saving": self.estimated_space_saving,
            "confidence": self.confidence,
        }
        