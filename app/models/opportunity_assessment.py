from app.decision_engine.signals.decision_signal import DecisionSignal

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass(slots=True)
class OpportunityAssessment:
    """
    Final intelligence output produced by FusionEngine.

    Represents:

        Decision Signals
              |
              v
        FusionEngine
              |
              v
        OpportunityAssessment


    This object answers:

        "Should we consider changing this media item?"

    It does NOT execute changes.

    Execution planning belongs downstream.
    """


    # ---------------------------------
    # Opportunity classification
    # ---------------------------------

    opportunity: str = "unknown"


    # ---------------------------------
    # Confidence
    #
    # Confidence means:
    #
    # "How certain are we that this
    # assessment is correct?"
    #
    # Derived from signal certainty.
    # ---------------------------------

    confidence: float = 0.0


    # ---------------------------------
    # Opportunity value
    #
    # Means:
    #
    # "How valuable is the proposed
    # optimisation?"
    #
    # Derived from DecisionSignals.
    # ---------------------------------

    opportunity_score: float = 0.0


    # ---------------------------------
    # Expected impact
    # ---------------------------------

    estimated_saving_percent: float = 0.0


    # ---------------------------------
    # Supporting information
    # ---------------------------------

    evidence: Dict[str, Any] = field(
        default_factory=dict
    )


    reasoning: List[str] = field(
        default_factory=list
    )

    # ---------------------------------
    # Original decision signals
    #
    # Preserves every detected opportunity.
    #
    # FusionEngine summarises these but
    # does not destroy them.
    #
    # Future:
    # - UI explanation
    # - user selection
    # - execution planning
    # ---------------------------------

    signals: List[DecisionSignal] = field(
        default_factory=list
    )
    
    # ---------------------------------
    # Full provenance chain
    # ---------------------------------

    provenance: List[Dict[str, Any]] = field(
        default_factory=list
    )


    contributing_rules: List[str] = field(
        default_factory=list
    )


    # ---------------------------------
    # Future execution safety
    # ---------------------------------

    risk: str = "unknown"


    # ---------------------------------
    # Constraint / applicability signals
    #
    # Structured preserve/constraint output (Sprint 10 correction).
    #
    # Constraints NEVER reduce opportunity magnitude by aggregation;
    # they are carried verbatim so consumers can honour and explain
    # them. Each entry also remains persisted as its own
    # decision_signals row.
    # ---------------------------------

    constraints: List[Dict[str, Any]] = field(
        default_factory=list
    )


    # ---------------------------------
    # Opportunity semantics (§21)
    #
    # opportunity_level distinguishes whether a worthwhile
    # improvement exists:
    #
    #     none        no worthwhile opportunity
    #     weak        a possible but not clearly worthwhile opportunity
    #     meaningful  a credible, worthwhile opportunity
    #     strong      a substantial, high-confidence opportunity
    #
    # priority_label is the human-facing presentation label mapped
    # from opportunity_level.
    # ---------------------------------

    opportunity_level: str = "none"

    priority_label: str = "No recommendation"

    # Absolute expected storage saving derived from the proposition
    # signals and authoritative file size. None means the assessment
    # does not establish an absolute saving.
    expected_saved_bytes: Optional[int] = None

    # Aggregated benefit / cost / risk categories over the surviving
    # opportunity propositions.
    benefit: str = "none"
    cost: str = "none"

    # Reasons not to optimise (preservation signals and suppressed
    # propositions), for explainable preservation conclusions.
    preservation_reasons: List[str] = field(
        default_factory=list
    )

    # Opportunity propositions that fusion suppressed, with the
    # preservation reason that suppressed them.
    suppressed_signals: List[Dict[str, Any]] = field(
        default_factory=list
    )

    # The opportunity signals that SURVIVED fusion reconciliation
    # (the active propositions). `signals` retains every original
    # signal for full provenance; this field exposes the ones that
    # actually produced the assessment.
    active_signals: List[Any] = field(
        default_factory=list
    )