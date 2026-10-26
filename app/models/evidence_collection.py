from dataclasses import dataclass, field

from .classification_evidence import ClassificationEvidence


@dataclass(slots=True)
class EvidenceCollection:
    """
    Container for classification evidence produced by different sources.

    EvidenceCollection does not evaluate or resolve evidence.
    It only stores and retrieves evidence items.
    """

    evidence: list[ClassificationEvidence] = field(default_factory=list)

    def add(self, evidence: ClassificationEvidence) -> None:
        """
        Add a single evidence item to the collection.
        """
        self.evidence.append(evidence)

    def all(self) -> list[ClassificationEvidence]:
        """
        Return all evidence items.
        """
        return self.evidence

    def by_domain(self, domain: str) -> list[ClassificationEvidence]:
        """
        Return evidence matching a specific classification domain.
        """
        return [
            item
            for item in self.evidence
            if item.domain == domain
        ]