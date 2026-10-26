"""
NAMOA Sprint 7 recommendation-prioritisation read models.

Authoritative recommendation-prioritisation read models produced by
RecommendationPrioritisationService
(app/services/recommendation_prioritisation_service.py).

These models answer:

    "Which current optimisation opportunities matter most?"

Prioritisation operates ONLY on the current-valid opportunity queue
produced by OpportunityQueueService (the current-opportunity boundary,
which consumes AnalysisValidityService for currentness). It never
touches experts, decision rules, Fusion internals, or execution.

Important distinction
---------------------

The analytical scores carried by an OptimisationCandidate
(opportunity_score, confidence, estimated_saving_percent, risk) are
produced by the Decision Engine / Fusion Engine and are NEVER
redefined. Prioritisation introduces a SEPARATE concept: a derived
priority score used to order recommendations. The raw analytical
fields are preserved verbatim on the wrapped candidate.
"""

from dataclasses import dataclass
from typing import Optional

from app.models.optimisation_candidate import OptimisationCandidate


@dataclass(frozen=True, slots=True)
class RecommendationComponents:
    """
    The weighted components of one priority score. Every component is
    exposed so the ordering is fully explainable.

    score_component          analytical value weight (opportunity score)
    savings_bytes_component  absolute expected saved bytes, normalised
    confidence_component     calibrated certainty weight
    risk_penalty             safety penalty
    calibrated_confidence    damped confidence
    risk_value               numeric risk mapping
    cost_benefit_ratio       saved bytes per unit of risk
    """

    score_component: float = 0.0

    savings_bytes_component: float = 0.0

    confidence_component: float = 0.0

    risk_penalty: float = 0.0

    calibrated_confidence: float = 0.0

    risk_value: float = 0.0

    cost_benefit_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class PrioritisedRecommendation:
    """
    One current-valid opportunity wrapped with its derived priority
    score, weighted components, and a human-readable rationale.

    The wrapped `candidate` is the authoritative OptimisationCandidate
    read model returned unchanged; the priority fields are a separate
    recommendation-layer concept.
    """

    rank: int

    candidate: OptimisationCandidate

    priority_score: float = 0.0

    opportunity_level: str = "none"

    priority_label: str = "No recommendation"

    components: RecommendationComponents = (
        RecommendationComponents()
    )

    rationale: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationSet:
    """
    A named, deterministic selection of prioritised recommendations
    (for example high-confidence, high-impact, or low-risk sets).
    Recommendations keep their priority order.
    """

    name: str

    description: str

    recommendations: tuple[PrioritisedRecommendation, ...] = ()

    count: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ProjectionCategory:
    """
    Aggregate savings projection for one opportunity classification.
    """

    opportunity: str

    count: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class SavingsProjection:
    """
    Aggregate savings projection over the prioritised recommendations.

    `top_n_projection` records the cumulative saved bytes if the user
    were to act on the top N recommendations (N from 1 to the length
    of the queue), illustrating diminishing returns.
    """

    total_opportunities: int = 0

    total_size_bytes: int = 0

    total_saved_bytes: int = 0

    total_saving_percent: float = 0.0

    by_opportunity: tuple[ProjectionCategory, ...] = ()

    top_n_projection: tuple[tuple[int, int, int], ...] = ()