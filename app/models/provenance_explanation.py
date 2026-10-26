from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProvenanceExplanation:
    """
    Human-readable explanation generated from immutable provenance.

    This model contains no intelligence.

    It is only a presentation representation of
    AnalysisProvenance.
    """

    summary: str

    expert_contributions: list[str] = field(
        default_factory=list
    )

    evidence_summary: list[str] = field(
        default_factory=list
    )

    decision_summary: list[str] = field(
        default_factory=list
    )

    knowledge_summary: list[str] = field(
        default_factory=list
    )

    confidence_summary: str = ""