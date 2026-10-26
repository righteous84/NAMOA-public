from app.models.analysis_provenance import AnalysisProvenance
from app.models.observation_history import (
    ObservationHistory,
    ObservationHistoryEntry,
)
from app.models.historical_analysis_comparison import (
    AnalysisDifference,
    HistoricalAnalysisComparison,
)


class ProvenanceQueryService:
    """
    Read-only service for reconstructing NAMOA analytical history.

    This service:

    - consumes persisted provenance
    - never executes intelligence
    - never recalculates decisions
    - never modifies assessments

    It exists to assemble the provenance graph.
    """

    def __init__(
        self,
        *,
        provenance_repository,
        evidence_repository,
        expert_result_repository,
        decision_signal_repository,
        analysis_repository,
        media_repository,
        recommendation_repository=None,
    ):

        self.provenance_repository = provenance_repository
        self.evidence_repository = evidence_repository
        self.expert_result_repository = expert_result_repository
        self.decision_signal_repository = decision_signal_repository
        self.analysis_repository = analysis_repository
        self.media_repository = media_repository
        self.recommendation_repository = (
            recommendation_repository
        )


    def get_analysis_provenance(
        self,
        analysis_run_id: int,
    ) -> AnalysisProvenance:
        """
        Retrieve complete provenance for an AnalysisRun.
        """

        analysis_run = (
            self.provenance_repository
            .get_analysis_run(
                analysis_run_id
            )
        )

        if analysis_run is None:
            raise ValueError(
                f"AnalysisRun {analysis_run_id} not found"
            )


        return AnalysisProvenance(

            analysis_run=analysis_run,

            knowledge_usage=(
                self.provenance_repository
                .get_knowledge_usage(
                    analysis_run_id
                )
            ),

            evidence=(
                self.evidence_repository
                .get_by_analysis_run(
                    analysis_run_id
                )
            ),

            expert_results=(
                self.expert_result_repository
                .get_by_analysis_run(
                    analysis_run_id
                )
            ),

            decision_signals=(
                self.decision_signal_repository
                .get_by_analysis_run(
                    analysis_run_id
                )
            ),

            opportunity_assessment=(
                self.analysis_repository
                .get_opportunity_assessment(
                    analysis_run_id
                )
            ),

            configuration=self._configuration_snapshot(
                analysis_run.configuration_snapshot_id
            ),
        )

    def _configuration_snapshot(
        self,
        configuration_snapshot_id,
    ) -> dict:
        """
        Read the immutable configuration snapshot for a run, exposing the
        intelligence version identity that produced it.
        """

        if configuration_snapshot_id is None:
            return {}

        return (
            self.provenance_repository
            .get_configuration_snapshot(
                configuration_snapshot_id
            )
        )


    def get_observation_history(
        self,
        media_id: int,
    ) -> ObservationHistory:
        """
        Reconstruct the complete immutable observation history for
        one media lineage.

        Each observation carries the analysis runs executed against
        that specific observed file state. This is a read-model
        operation over persisted state only.
        """

        media = self.media_repository.get_media_item(
            media_id
        )

        if media is None:
            raise ValueError(
                f"Media lineage {media_id} not found"
            )

        observations = (
            self.media_repository
            .get_file_observations(
                media_id
            )
        )

        entries = tuple(
            ObservationHistoryEntry(
                observation=observation,
                analysis_runs=tuple(
                    self.provenance_repository
                    .get_analysis_runs_by_observation(
                        observation.id
                    )
                ),
            )
            for observation in observations
        )

        return ObservationHistory(
            media=media,
            observations=entries,
        )


    def compare_analysis_runs(
        self,
        run_a_id: int,
        run_b_id: int,
    ) -> HistoricalAnalysisComparison:
        """
        Compare two persisted historical analyses of the same media
        lineage.

        This is a read-model operation. It reconstructs persisted
        provenance for both runs and reports meaningful differences.
        It never reruns intelligence and never mutates either
        analysis.

        Raises:
            ValueError: if either run is missing, or the runs belong
                to different media lineages.
        """

        provenance_a = self.get_analysis_provenance(
            run_a_id
        )

        provenance_b = self.get_analysis_provenance(
            run_b_id
        )

        run_a = provenance_a.analysis_run
        run_b = provenance_b.analysis_run

        if run_a.media_id != run_b.media_id:
            raise ValueError(
                f"Cannot compare analyses from different media "
                f"lineages ({run_a.media_id} vs {run_b.media_id})"
            )

        observation_a = (
            self.provenance_repository
            .get_file_observation(
                run_a.file_observation_id
            )
            if run_a.file_observation_id
            else None
        )

        observation_b = (
            self.provenance_repository
            .get_file_observation(
                run_b.file_observation_id
            )
            if run_b.file_observation_id
            else None
        )

        same_observation = (
            run_a.file_observation_id is not None
            and run_a.file_observation_id
            == run_b.file_observation_id
        )

        differences = tuple(
            self._compute_differences(
                provenance_a,
                provenance_b,
                observation_a,
                observation_b,
            )
        )

        return HistoricalAnalysisComparison(
            run_a=run_a,
            run_b=run_b,
            media_id=run_a.media_id,
            same_observation=same_observation,
            observation_a=observation_a,
            observation_b=observation_b,
            differences=differences,
        )


    # ---------------------------------------------------------
    # Difference computation
    # ---------------------------------------------------------

    def _compute_differences(
        self,
        provenance_a: AnalysisProvenance,
        provenance_b: AnalysisProvenance,
        observation_a,
        observation_b,
    ) -> list[AnalysisDifference]:

        differences = []

        self._diff_run_state(
            differences,
            provenance_a.analysis_run,
            provenance_b.analysis_run,
        )

        self._diff_intelligence_identity(
            differences,
            provenance_a.analysis_run,
            provenance_b.analysis_run,
        )

        if (
            self.recommendation_repository is not None
        ):
            self._diff_recommendations(
                differences,
                provenance_a.analysis_run.id,
                provenance_b.analysis_run.id,
            )

        self._diff_observation(
            differences,
            observation_a,
            observation_b,
        )

        self._diff_expert_results(
            differences,
            provenance_a.expert_results,
            provenance_b.expert_results,
        )

        self._diff_decision_signals(
            differences,
            provenance_a.decision_signals,
            provenance_b.decision_signals,
        )

        self._diff_opportunity_assessment(
            differences,
            provenance_a.opportunity_assessment,
            provenance_b.opportunity_assessment,
        )

        self._diff_evidence(
            differences,
            provenance_a.evidence,
            provenance_b.evidence,
        )

        self._diff_knowledge_usage(
            differences,
            provenance_a.knowledge_usage,
            provenance_b.knowledge_usage,
        )

        return differences


    @staticmethod
    def _add_difference(
        differences: list[AnalysisDifference],
        category: str,
        key: str,
        before,
        after,
        summary: str,
    ) -> None:
        """
        Record a difference only when the values actually differ.
        """

        if before == after:
            return

        differences.append(
            AnalysisDifference(
                category=category,
                key=key,
                before=before,
                after=after,
                summary=summary,
            )
        )


    def _diff_run_state(
        self,
        differences: list[AnalysisDifference],
        run_a,
        run_b,
    ) -> None:

        fields = [
            ("status", "run status"),
            ("started_at", "run started_at"),
            ("completed_at", "run completed_at"),
            ("error_message", "run error_message"),
            (
                "configuration_snapshot_id",
                "run configuration_snapshot_id",
            ),
        ]

        for field_name, label in fields:

            self._add_difference(
                differences,
                "run_state",
                field_name,
                getattr(run_a, field_name),
                getattr(run_b, field_name),
                f"{label} changed",
            )


    def _diff_intelligence_identity(
        self,
        differences: list,
        run_a,
        run_b,
    ) -> None:
        """
        Compare the canonical intelligence identity digests recorded
        on the two runs. NULL identities (development-era runs) are
        reported as such rather than fabricated.
        """

        identity_a = getattr(
            run_a, "intelligence_identity", None
        )

        identity_b = getattr(
            run_b, "intelligence_identity", None
        )

        self._add_difference(
            differences,
            "intelligence_identity",
            "digest",
            identity_a or "unrecorded",
            identity_b or "unrecorded",
            "intelligence identity changed",
        )

    def _diff_recommendations(
        self,
        differences: list,
        run_a_id: int,
        run_b_id: int,
    ) -> None:
        """
        Compare the durable recommendations produced by the two
        runs (Sprint 10 correction).
        """

        rec_a = (
            self.recommendation_repository.get_by_run(
                run_a_id
            )
        )

        rec_b = (
            self.recommendation_repository.get_by_run(
                run_b_id
            )
        )

        summary_a = self._recommendation_summary(rec_a)
        summary_b = self._recommendation_summary(rec_b)

        keys = sorted(set(summary_a) | set(summary_b)) or [
            "all"
        ]

        for key in keys:

            self._add_difference(
                differences,
                "recommendation",
                key,
                summary_a.get(key),
                summary_b.get(key),
                f"recommendation {key} changed",
            )

    @staticmethod
    def _recommendation_summary(records) -> dict:

        summary = {}

        for record in records:

            summary[str(record.id)] = {
                "opportunity": record.opportunity,
                "opportunity_score": (
                    record.opportunity_score
                ),
                "confidence": record.confidence,
                "estimated_saving_percent": (
                    record.estimated_saving_percent
                ),
                "risk": record.risk,
                "priority_score": record.priority_score,
                "state": record.state,
                "contributing_rules": (
                    record.contributing_rules
                ),
            }

        return summary

    def _diff_observation(
        self,
        differences: list[AnalysisDifference],
        observation_a,
        observation_b,
    ) -> None:

        if observation_a is None and observation_b is None:
            return

        if observation_a is None:
            differences.append(
                AnalysisDifference(
                    category="observation",
                    key="presence",
                    before=None,
                    after=observation_b.id,
                    summary="run B has an observation, run A has none",
                )
            )
            return

        if observation_b is None:
            differences.append(
                AnalysisDifference(
                    category="observation",
                    key="presence",
                    before=observation_a.id,
                    after=None,
                    summary="run A has an observation, run B has none",
                )
            )
            return

        fields = [
            ("file_path", "observed file_path"),
            ("size_bytes", "observed size_bytes"),
            ("file_mtime_ns", "observed file_mtime_ns"),
            ("filesystem_device", "observed filesystem_device"),
            ("filesystem_inode", "observed filesystem_inode"),
            ("sha256_hash", "observed sha256_hash"),
            (
                "identity_match_method",
                "observed identity_match_method",
            ),
        ]

        for field_name, label in fields:

            self._add_difference(
                differences,
                "observation",
                field_name,
                getattr(observation_a, field_name),
                getattr(observation_b, field_name),
                f"{label} changed",
            )


    def _diff_expert_results(
        self,
        differences: list[AnalysisDifference],
        results_a,
        results_b,
    ) -> None:

        summary_a = self._expert_summary(results_a)
        summary_b = self._expert_summary(results_b)

        for expert_name in sorted(
            set(summary_a) | set(summary_b)
        ):

            self._add_difference(
                differences,
                "expert_result",
                expert_name,
                summary_a.get(expert_name),
                summary_b.get(expert_name),
                f"expert_result {expert_name} changed",
            )


    @staticmethod
    def _expert_summary(
        results,
    ) -> dict:

        summary = {}

        for result in results:

            domains = {}

            if result.expert_data:
                for domain, analysis in (
                    result.expert_data.domains.items()
                ):
                    domains[domain] = (
                        analysis.selected_value,
                        analysis.confidence,
                        analysis.agreement.value,
                    )

            summary[result.expert_name] = {
                "confidence": result.confidence,
                "domains": domains,
            }

        return summary


    def _diff_decision_signals(
        self,
        differences: list[AnalysisDifference],
        signals_a,
        signals_b,
    ) -> None:

        summary_a = self._signal_summary(signals_a)
        summary_b = self._signal_summary(signals_b)

        for rule_name in sorted(
            set(summary_a) | set(summary_b)
        ):

            self._add_difference(
                differences,
                "decision_signal",
                rule_name,
                summary_a.get(rule_name),
                summary_b.get(rule_name),
                f"decision_signal {rule_name} changed",
            )


    @staticmethod
    def _signal_summary(
        signals,
    ) -> dict:

        summary = {}

        for signal in signals:

            summary[signal.rule] = {
                "direction": signal.direction,
                "opportunity_score": (
                    signal.opportunity_score
                ),
                "confidence": signal.confidence,
            }

        return summary


    def _diff_opportunity_assessment(
        self,
        differences: list[AnalysisDifference],
        assessment_a,
        assessment_b,
    ) -> None:

        if assessment_a is None and assessment_b is None:
            return

        if assessment_a is None:
            differences.append(
                AnalysisDifference(
                    category="opportunity_assessment",
                    key="presence",
                    before=None,
                    after=True,
                    summary="run B has an assessment, run A has none",
                )
            )
            return

        if assessment_b is None:
            differences.append(
                AnalysisDifference(
                    category="opportunity_assessment",
                    key="presence",
                    before=True,
                    after=None,
                    summary="run A has an assessment, run B has none",
                )
            )
            return

        fields = [
            ("opportunity", "assessment opportunity"),
            ("opportunity_score", "assessment opportunity_score"),
            ("confidence", "assessment confidence"),
            (
                "estimated_saving_percent",
                "assessment estimated_saving_percent",
            ),
            ("risk", "assessment risk"),
            ("contributing_rules", "assessment contributing_rules"),
        ]

        for field_name, label in fields:

            self._add_difference(
                differences,
                "opportunity_assessment",
                field_name,
                getattr(assessment_a, field_name),
                getattr(assessment_b, field_name),
                f"{label} changed",
            )


    def _diff_evidence(
        self,
        differences: list[AnalysisDifference],
        evidence_a,
        evidence_b,
    ) -> None:

        summary_a = self._evidence_summary(evidence_a)
        summary_b = self._evidence_summary(evidence_b)

        self._add_difference(
            differences,
            "evidence",
            "all",
            summary_a,
            summary_b,
            "evidence set changed",
        )


    @staticmethod
    def _evidence_summary(
        evidence,
    ) -> tuple:

        return tuple(
            sorted(
                (
                    item.domain,
                    item.value,
                    item.confidence,
                    item.source,
                )
                for item in evidence
            )
        )


    def _diff_knowledge_usage(
        self,
        differences: list[AnalysisDifference],
        usage_a,
        usage_b,
    ) -> None:

        summary_a = tuple(
            sorted(
                item.knowledge_set_id
                for item in usage_a
            )
        )

        summary_b = tuple(
            sorted(
                item.knowledge_set_id
                for item in usage_b
            )
        )

        self._add_difference(
            differences,
            "knowledge_usage",
            "all",
            summary_a,
            summary_b,
            "knowledge usage changed",
        )
