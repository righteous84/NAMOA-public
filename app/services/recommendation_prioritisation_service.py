"""
NAMOA recommendation-prioritisation authority.

Answers:

    "Which current optimisation opportunities matter most?"

It operates EXCLUSIVELY on the current-valid opportunity queue produced
by OpportunityQueueService (the current-opportunity boundary, which
consumes AnalysisValidityService for currentness). It never:

- invokes or duplicates experts, decision rules, or Fusion internals
- redefines the analytical opportunity scores it receives
- touches execution workflows

The analytical fields carried by an OptimisationCandidate
(opportunity_score, confidence, estimated_saving_percent, risk) are
produced by the Decision Engine / Fusion Engine and are used verbatim.
Prioritisation introduces a SEPARATE derived concept: a priority score
used to order recommendations.

Prioritisation policy (documented, deterministic, explainable)
--------------------------------------------------------------

    priority_score =
        WEIGHT_VALUE       * opportunity_score        (analytical value)
      + WEIGHT_SAVINGS     * savings_bytes_normalised (absolute impact)
      + WEIGHT_CONFIDENCE  * calibrated_confidence    (calibrated)
      - WEIGHT_RISK        * risk_penalty             (safety)

    WEIGHT_VALUE      = 0.4   the FusionEngine opportunity score
    WEIGHT_SAVINGS    = 0.3   absolute expected saved bytes
    WEIGHT_CONFIDENCE = 0.2   analytical confidence
    WEIGHT_RISK       = 0.1   safety penalty

    savings_bytes_normalised = min(expected_saved_bytes /
                                    SAVINGS_IMPACT_REFERENCE_BYTES, 1.0)
        A saving of SAVINGS_IMPACT_REFERENCE_BYTES (2 GiB) or more
        counts as full storage impact. Absolute bytes matter: a
        multi-gigabyte saving outranks a tiny theoretical saving even
        when percentage scores are similar.

    calibrated_confidence = 0.5 + (confidence - 0.5) * 0.9
        Conservative damping that preserves ordering while reducing
        overconfidence at the extremes. The raw analytical confidence
        remains untouched on the candidate.

    risk_penalty = {"low": 0.0, "medium": 0.5, "high": 1.0}[risk]

    cost_benefit_ratio = estimated_saved_bytes / risk_value
        where risk_value = {"low": 1, "medium": 2, "high": 3}. Bytes
        saved per unit of risk.

Ties are broken deterministically by media_id ascending.
"""

from app.models.recommendation_prioritisation import (
    PrioritisedRecommendation,
    ProjectionCategory,
    RecommendationComponents,
    RecommendationSet,
    SavingsProjection,
)

# ---------------------------------------------------------
# Documented weighting policy constants
# ---------------------------------------------------------

WEIGHT_VALUE = 0.4
WEIGHT_SAVINGS = 0.3
WEIGHT_CONFIDENCE = 0.2
WEIGHT_RISK = 0.1

# A saving of this many bytes (2 GiB) or more counts as full
# storage impact in the savings component.
SAVINGS_IMPACT_REFERENCE_BYTES = 2 * 1024 * 1024 * 1024

CONFIDENCE_DAMPING = 0.9

RISK_PENALTIES = {
    "low": 0.0,
    "medium": 0.5,
    "high": 1.0,
}

RISK_VALUES = {
    "low": 1.0,
    "medium": 2.0,
    "high": 3.0,
}

DEFAULT_HIGH_CONFIDENCE_MIN = 0.8
DEFAULT_HIGH_IMPACT_MIN_SAVINGS = 20.0
DEFAULT_LOW_RISK_VALUES = ("low",)


class RecommendationPrioritisationService:
    """
    Authoritative recommendation prioritisation over the current-valid
    opportunity queue. Read-only; never writes persistence.
    """

    # Semantic version of the recommendation/prioritisation policy.
    # 2.0.0: prioritisation now represents actual value. The savings
    # component uses absolute expected saved bytes (a multi-gigabyte
    # saving outranks a tiny theoretical saving) instead of a
    # percentage derived from the analytical score.
    semantic_version = "2.0.0"

    def __init__(
        self,
        *,
        opportunity_queue_service,
    ):

        self.queue_service = opportunity_queue_service

    @classmethod
    def policy_values(cls) -> dict:
        """
        The recommendation/prioritisation policy values that affect
        analytical meaning, attributable to semantic_version.
        """

        return {
            "weights": {
                "value": WEIGHT_VALUE,
                "savings": WEIGHT_SAVINGS,
                "confidence": WEIGHT_CONFIDENCE,
                "risk": WEIGHT_RISK,
            },
            "savings_impact_reference_bytes": (
                SAVINGS_IMPACT_REFERENCE_BYTES
            ),
            "confidence_damping": CONFIDENCE_DAMPING,
            "risk_penalties": RISK_PENALTIES,
            "risk_values": RISK_VALUES,
            "high_confidence_min": DEFAULT_HIGH_CONFIDENCE_MIN,
            "high_impact_min_savings": (
                DEFAULT_HIGH_IMPACT_MIN_SAVINGS
            ),
            "low_risk_values": list(DEFAULT_LOW_RISK_VALUES),
        }

    # ---------------------------------------------------------
    # Calibration (documented policy)
    # ---------------------------------------------------------

    @staticmethod
    def calibrate_confidence(confidence: float) -> float:
        """
        Conservative confidence calibration: a monotonic mapping that
        preserves ordering while damping overconfidence at the
        extremes. The raw analytical confidence is never modified.
        """

        confidence = float(confidence or 0.0)

        return round(
            0.5 + (confidence - 0.5) * CONFIDENCE_DAMPING,
            4,
        )

    # ---------------------------------------------------------
    # Prioritised ranking
    # ---------------------------------------------------------

    def prioritise(
        self,
    ) -> tuple[PrioritisedRecommendation, ...]:
        """
        Deterministic ranking of the current-valid queue by priority
        score (descending), ties broken by media_id (ascending).
        """

        queue = self.queue_service.get_queue()

        scored = [
            self._prioritise_one(candidate)
            for candidate in queue
        ]

        scored.sort(
            key=lambda item: (
                -item.priority_score,
                item.candidate.media_id,
            )
        )

        return tuple(
            PrioritisedRecommendation(
                rank=index + 1,
                candidate=item.candidate,
                priority_score=item.priority_score,
                opportunity_level=(
                    item.candidate.opportunity_level
                ),
                priority_label=(
                    item.candidate.priority_label
                ),
                components=item.components,
                rationale=item.rationale,
            )
            for index, item in enumerate(scored)
        )

    def _prioritise_one(
        self,
        candidate,
    ) -> PrioritisedRecommendation:

        score = candidate.opportunity_score or 0.0

        raw_confidence = candidate.confidence or 0.0

        calibrated = self.calibrate_confidence(
            raw_confidence
        )

        saved_bytes = candidate.estimated_saved_bytes or 0

        savings_normalised = min(
            saved_bytes / SAVINGS_IMPACT_REFERENCE_BYTES,
            1.0,
        )

        risk = candidate.risk or "unknown"

        risk_penalty_value = RISK_PENALTIES.get(
            risk,
            RISK_PENALTIES["medium"],
        )

        risk_value = RISK_VALUES.get(
            risk,
            RISK_VALUES["medium"],
        )

        value_component = WEIGHT_VALUE * score
        savings_component = WEIGHT_SAVINGS * savings_normalised
        confidence_component = WEIGHT_CONFIDENCE * calibrated
        risk_penalty = WEIGHT_RISK * risk_penalty_value

        priority_score = (
            value_component
            + savings_component
            + confidence_component
            - risk_penalty
        )

        cost_benefit_ratio = (
            saved_bytes / risk_value
            if risk_value > 0
            else 0.0
        )

        components = RecommendationComponents(
            score_component=round(value_component, 4),
            savings_bytes_component=round(
                savings_component,
                4,
            ),
            confidence_component=round(
                confidence_component,
                4,
            ),
            risk_penalty=round(risk_penalty, 4),
            calibrated_confidence=calibrated,
            risk_value=risk_value,
            cost_benefit_ratio=round(
                cost_benefit_ratio,
                2,
            ),
        )

        rationale = (
            f"Analytical value score {score:.4f} "
            f"(weight {WEIGHT_VALUE}).",
            f"Absolute expected saving {saved_bytes} bytes "
            f"normalised to {savings_normalised:.4f} "
            f"(weight {WEIGHT_SAVINGS}).",
            f"Calibrated confidence {calibrated:.4f} "
            f"(raw {raw_confidence:.4f}, weight "
            f"{WEIGHT_CONFIDENCE}).",
            f"Risk '{risk}' penalty {risk_penalty_value:.1f} "
            f"(weight {WEIGHT_RISK}).",
        )

        return PrioritisedRecommendation(
            rank=0,
            candidate=candidate,
            priority_score=round(priority_score, 4),
            opportunity_level=(
                candidate.opportunity_level
            ),
            priority_label=(
                candidate.priority_label
            ),
            components=components,
            rationale=rationale,
        )

    # ---------------------------------------------------------
    # Recommendation sets
    # ---------------------------------------------------------

    def high_confidence_set(
        self,
        min_confidence: float = DEFAULT_HIGH_CONFIDENCE_MIN,
    ) -> RecommendationSet:
        """
        Recommendations whose raw analytical confidence is at least
        `min_confidence`. Selection uses the authoritative analytical
        confidence, not the calibrated value.
        """

        selected = [
            item
            for item in self.prioritise()
            if (item.candidate.confidence or 0.0)
            >= min_confidence
        ]

        return self._build_set(
            name="high_confidence",
            description=(
                "Current opportunities whose analytical confidence "
                f"is at least {min_confidence:.2f}."
            ),
            recommendations=selected,
        )

    def high_impact_set(
        self,
        min_saving_percent: float = (
            DEFAULT_HIGH_IMPACT_MIN_SAVINGS
        ),
    ) -> RecommendationSet:
        """
        Recommendations whose estimated saving percent is at least
        `min_saving_percent`.
        """

        selected = [
            item
            for item in self.prioritise()
            if (item.candidate.estimated_saving_percent or 0.0)
            >= min_saving_percent
        ]

        return self._build_set(
            name="high_impact",
            description=(
                "Current opportunities whose estimated saving is at "
                f"least {min_saving_percent:g}%."
            ),
            recommendations=selected,
        )

    def low_risk_set(
        self,
        allowed_risks: tuple[str, ...] = (
            DEFAULT_LOW_RISK_VALUES
        ),
    ) -> RecommendationSet:
        """
        Recommendations whose risk classification is in
        `allowed_risks` (default: only 'low').
        """

        selected = [
            item
            for item in self.prioritise()
            if (item.candidate.risk or "unknown") in allowed_risks
        ]

        return self._build_set(
            name="low_risk",
            description=(
                "Current opportunities whose risk classification is "
                + ", ".join(f"'{risk}'" for risk in allowed_risks)
                + "."
            ),
            recommendations=selected,
        )

    def recommendation_sets(
        self,
    ) -> tuple[RecommendationSet, ...]:
        """
        The standard three sets: high-confidence, high-impact, and
        low-risk, in a deterministic order.
        """

        return (
            self.high_confidence_set(),
            self.high_impact_set(),
            self.low_risk_set(),
        )

    @staticmethod
    def _build_set(
        *,
        name: str,
        description: str,
        recommendations,
    ) -> RecommendationSet:

        return RecommendationSet(
            name=name,
            description=description,
            recommendations=tuple(recommendations),
            count=len(recommendations),
            total_size_bytes=sum(
                item.candidate.file_size_bytes
                for item in recommendations
            ),
            total_saved_bytes=sum(
                item.candidate.estimated_saved_bytes
                for item in recommendations
            ),
        )

    # ---------------------------------------------------------
    # Aggregate savings projection
    # ---------------------------------------------------------

    def savings_projection(
        self,
    ) -> SavingsProjection:
        """
        Aggregate savings projection over the prioritised
        recommendations, including per-opportunity categories and a
        cumulative top-N projection.
        """

        prioritised = self.prioritise()

        total_size = sum(
            item.candidate.file_size_bytes
            for item in prioritised
        )

        total_saved = sum(
            item.candidate.estimated_saved_bytes
            for item in prioritised
        )

        by_opportunity = {}

        for item in prioritised:

            category = by_opportunity.get(
                item.candidate.opportunity
            )

            by_opportunity[item.candidate.opportunity] = (
                ProjectionCategory(
                    opportunity=item.candidate.opportunity,
                    count=(
                        category.count + 1
                        if category is not None
                        else 1
                    ),
                    total_size_bytes=(
                        category.total_size_bytes
                        + item.candidate.file_size_bytes
                        if category is not None
                        else item.candidate.file_size_bytes
                    ),
                    total_saved_bytes=(
                        category.total_saved_bytes
                        + item.candidate.estimated_saved_bytes
                        if category is not None
                        else item.candidate.estimated_saved_bytes
                    ),
                )
            )

        cumulative = []

        running = 0

        for item in prioritised:

            running += item.candidate.estimated_saved_bytes

            cumulative.append(
                (
                    item.rank,
                    item.candidate.estimated_saved_bytes,
                    running,
                )
            )

        return SavingsProjection(
            total_opportunities=len(prioritised),
            total_size_bytes=total_size,
            total_saved_bytes=total_saved,
            total_saving_percent=(
                (total_saved / total_size) * 100
                if total_size > 0
                else 0.0
            ),
            by_opportunity=tuple(
                by_opportunity[key]
                for key in sorted(by_opportunity)
            ),
            top_n_projection=tuple(cumulative),
        )