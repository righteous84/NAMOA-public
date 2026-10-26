from dataclasses import dataclass

from app.models.analysis_run import AnalysisRun


@dataclass(frozen=True, slots=True)
class AnalysisProvenance:
    """
    Complete immutable provenance snapshot for an AnalysisRun.

    Represents the historical chain:

        Evidence
            ↓
        Knowledge
            ↓
        Experts
            ↓
        Decision Signals
            ↓
        Opportunity Assessment
    """

    analysis_run: AnalysisRun

    knowledge_usage: list

    evidence: list

    expert_results: list

    decision_signals: list

    opportunity_assessment: object | None

    # Immutable configuration snapshot for the run, including the
    # intelligence version manifest, policy values, and Git revision
    # that produced the run.
    configuration: dict = None