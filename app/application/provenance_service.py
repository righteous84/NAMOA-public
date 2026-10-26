from app.models.analysis_provenance import AnalysisProvenance
from app.models.provenance_explanation import ProvenanceExplanation
from app.models.historical_analysis_comparison import (
    HistoricalAnalysisComparison,
)


class ProvenanceService:
    """
    Application boundary for provenance / explanation workflows.

    Composes the two existing provenance authorities:

        ProvenanceQueryService        - reconstructs persisted history
        ProvenanceExplanationService  - explains persisted history

    This service orchestrates those capabilities; it never reconstructs
    or explains provenance itself.

    Observation history reads are exposed by MediaService (the
    lineage/observation read boundary) and are intentionally not
    duplicated here.
    """

    def __init__(
        self,
        *,
        provenance_query_service,
        provenance_explanation_service,
    ):

        self.provenance_query_service = provenance_query_service
        self.provenance_explanation_service = (
            provenance_explanation_service
        )

    def get_analysis_provenance(
        self,
        analysis_run_id,
    ) -> AnalysisProvenance:
        """
        Application-facing reconstruction of one analysis run's
        provenance.

        Delegates to ProvenanceQueryService; returns the existing
        AnalysisProvenance read model unchanged.
        """

        return self.provenance_query_service.get_analysis_provenance(
            analysis_run_id
        )

    def explain(
        self,
        analysis_run_id,
    ) -> ProvenanceExplanation:
        """
        Application-facing human-readable explanation for one analysis
        run.

        Orchestrates ProvenanceQueryService (reconstruct) and
        ProvenanceExplanationService (explain). No explanation logic is
        reimplemented here.
        """

        provenance = (
            self.provenance_query_service
            .get_analysis_provenance(
                analysis_run_id
            )
        )

        return self.provenance_explanation_service.explain(
            provenance
        )

    def compare_analysis_runs(
        self,
        run_a_id,
        run_b_id,
    ) -> HistoricalAnalysisComparison:
        """
        Application-facing read comparison of two persisted analyses
        of the same media lineage.

        Delegates to ProvenanceQueryService; returns the existing
        HistoricalAnalysisComparison read model unchanged.

        Raises ValueError when either run is missing or the runs
        belong to different media lineages.
        """

        return self.provenance_query_service.compare_analysis_runs(
            run_a_id,
            run_b_id,
        )
