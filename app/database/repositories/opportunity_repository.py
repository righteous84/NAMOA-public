from app.models.optimisation_candidate import (
    OptimisationCandidate
)

from app.services.savings_conversion import SavingsConversion


class OpportunityRepository:
    """
    Read-only access to optimisation opportunities.

    This repository does not:
    - rank opportunities
    - calculate savings
    - modify recommendations
    - decide whether an opportunity is current

    Currentness is decided by AnalysisValidityService (the single
    validity authority). This repository only constructs the
    OptimisationCandidate read model from a media lineage and its
    current valid OpportunityAssessment.
    """

    def __init__(self, connection):
        self.connection = connection

    def build_candidate(
        self,
        lineage,
        opportunity,
        *,
        analysis_run_id=None,
        observation_id=None,
    ) -> OptimisationCandidate:

        file_size_bytes = lineage.file_size_bytes or 0

        saving_percent = (
            opportunity.estimated_saving_percent or 0
        )

        # The authoritative absolute expected saving is the assessment's
        # transformation-aware expected_saved_bytes (the dominant
        # storage proposition's evidence). Historical rows recorded
        # before that field existed fall back to the percent-derived
        # value so they remain readable, through the single shared
        # historical fallback (Phase 9).
        saved_bytes = opportunity.expected_saved_bytes

        if saved_bytes is None:

            saved_bytes = SavingsConversion.historical_fallback(
                saving_percent,
                file_size_bytes,
            )

        return OptimisationCandidate(
            media_id=lineage.id,
            file_path=lineage.file_path,
            file_name=lineage.file_name,
            opportunity=opportunity.opportunity,
            opportunity_score=opportunity.opportunity_score,
            confidence=opportunity.confidence,
            estimated_saving_percent=(
                opportunity.estimated_saving_percent
            ),
            file_size_bytes=file_size_bytes,
            estimated_saved_bytes=int(saved_bytes),
            risk=opportunity.risk,
            opportunity_level=(
                opportunity.opportunity_level
            ),
            priority_label=(
                opportunity.priority_label
            ),
            benefit=(
                opportunity.benefit
            ),
            cost=(
                opportunity.cost
            ),
            analysis_run_id=analysis_run_id,
            observation_id=observation_id,
            signals=tuple(
                getattr(
                    opportunity,
                    "signals",
                    (),
                )
                or ()
            ),
            suppressed_propositions=tuple(
                (
                    item.get("proposition")
                    if isinstance(item, dict)
                    else getattr(
                        item, "proposition", None
                    )
                )
                for item in (
                    getattr(
                        opportunity,
                        "suppressed_signals",
                        (),
                    )
                    or ()
                )
                if (
                    item.get("proposition")
                    if isinstance(item, dict)
                    else getattr(
                        item, "proposition", None
                    )
                )
            ),
        )
