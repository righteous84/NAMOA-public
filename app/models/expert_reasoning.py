"""
Typed reasoning models produced by Experts.

These models represent an Expert's interpretation of collected evidence.

Pipeline philosophy:

    ClassificationEvidence
            ↓
      Expert Interpretation
            ↓
        ExpertData
            ↓
       FusionEngine

The original evidence remains immutable.

Experts never modify evidence. Instead, they reference the evidence they
used and record how it contributed to their conclusions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgreementState(str, Enum):
    """
    Describes the level of agreement between supporting evidence.
    """

    SINGLE = "single"
    SAME_SOURCE = "same_source"
    INDEPENDENT = "independent"


class EvidenceRole(str, Enum):
    """
    Describes how an Expert used a piece of evidence.
    """

    PRIMARY = "primary"
    SUPPORTING = "supporting"
    REJECTED = "rejected"


@dataclass(slots=True, frozen=True)
class EvidenceReference:
    """
    Records how an Expert used a piece of evidence.

    This is not a copy of ClassificationEvidence.

    Instead, it captures the Expert's interpretation of that evidence at
    the time the analysis was performed.

    The referenced evidence itself remains immutable.
    """

    source: str

    raw_confidence: float

    weighted_confidence: float

    role: EvidenceRole

    evidence_id: Optional[str] = None

    matched_text: Optional[str] = None


@dataclass(slots=True, frozen=True)
class AlternativeInterpretation:
    """
    Represents an interpretation that was considered but not selected.
    """

    value: str

    confidence: float

    support_count: int


@dataclass(slots=True, frozen=True)
class DomainAnalysis:
    """
    Expert interpretation for a single classification domain.

    Example domains:

        video_codec
        audio
        resolution
        hdr
    """

    selected_value: str

    confidence: float

    agreement: AgreementState

    has_conflict: bool

    uncertainty: float

    selected_references: tuple[EvidenceReference, ...] = ()

    rejected_references: tuple[EvidenceReference, ...] = ()

    alternatives: tuple[AlternativeInterpretation, ...] = ()


@dataclass(slots=True)
class ExpertData:
    """
    Structured reasoning produced by an Expert.

    FusionEngine and future pipeline stages consume this model rather than
    parsing human-readable notes.
    """

    domains: dict[str, DomainAnalysis] = field(default_factory=dict)