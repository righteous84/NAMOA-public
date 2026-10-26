from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class OptimisationCandidate:
    """
    Ranked library optimisation opportunity.

    This is a read model.

    It does not create recommendations.
    It represents already identified opportunities.
    """

    media_id: int

    file_path: str

    file_name: str

    opportunity: str

    opportunity_score: float

    confidence: float

    estimated_saving_percent: float

    file_size_bytes: int

    estimated_saved_bytes: int

    risk: str

    # Opportunity semantics carried from the producing assessment.
    opportunity_level: str = "none"
    priority_label: str = "No recommendation"
    benefit: str = "none"
    cost: str = "none"

    # Provenance anchors surfaced by OpportunityQueueService from
    # AnalysisValidityService (the sole currentness authority):
    # the valid completed analysis run and the matching current
    # observation behind this candidate. Optional for backward
    # compatibility; populated for all queue-derived candidates.
    analysis_run_id: Optional[int] = None

    observation_id: Optional[int] = None

    # The persisted decision signals of the producing run, carried
    # verbatim so presentation layers can derive the proposed
    # transformation (change summary) from data the system already
    # persists. Never recomputed.
    signals: tuple = ()

    # The propositions Fusion suppressed for the producing run
    # (persisted suppressed_signals). Used to present only the
    # surviving opportunity propositions without recomputing fusion.
    #
    # This field remains exclusively owned by analytical Fusion
    # suppression. It must not be used for user standing decisions.
    suppressed_propositions: tuple = ()

    # Propositions the user has explicitly refused for this lineage
    # as a standing presentation/approval preference.
    #
    # This is separate from Fusion suppression. It does not alter the
    # underlying assessment, scores, validity, or intelligence output.
    standing_suppressed_propositions: tuple = ()