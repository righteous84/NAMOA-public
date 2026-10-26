class RecommendationService:
    """
    Application boundary for recommendation / opportunity workflows.

    The existing opportunity queue construction is owned by
    OpportunityQueueService, which consumes AnalysisValidityService for
    currentness and builds OptimisationCandidate read models.

    Sprint 7 introduces RecommendationPrioritisationService
    (app/services/recommendation_prioritisation_service.py), the
    authoritative recommendation-prioritisation authority. It operates
    exclusively on the OpportunityQueueService queue and never touches
    experts, decision rules, Fusion internals, or execution.

    This service therefore exposes:
    - get_current_queue(): the authoritative current-valid queue
    - prioritisation workflows delegating to
      RecommendationPrioritisationService

    All workflows are thin delegations; no ranking, weighting,
    calibration, currentness, or candidate-construction logic is
    reimplemented here.
    """

    def __init__(
        self,
        *,
        opportunity_queue_service,
        recommendation_prioritisation_service,
        recommendation_repository=None,
    ):

        self.opportunity_queue_service = opportunity_queue_service
        self.recommendation_prioritisation_service = (
            recommendation_prioritisation_service
        )
        self.recommendation_records = (
            recommendation_repository
        )

    def get_current_queue(self):
        """
        Application-facing read of the current-valid opportunity queue.

        Delegates to OpportunityQueueService; returns the existing
        OptimisationCandidate read models unchanged.

        Currentness is decided by the existing validity authority and
        is never reimplemented here.
        """

        return self.opportunity_queue_service.get_queue()

    def active_propositions_for(self, media_id):
        """
        Currently presentable propositions for one media lineage,
        delegated to the queue authority. Read-only.
        """

        return (
            self.opportunity_queue_service
            .active_propositions_for(media_id)
        )

    def get_prioritised_recommendations(self):
        """
        Deterministically prioritised recommendations over the
        current-valid queue.

        Delegates to RecommendationPrioritisationService; the wrapped
        candidates remain the authoritative OptimisationCandidate read
        models.
        """

        return (
            self.recommendation_prioritisation_service
            .prioritise()
        )

    def get_recommendation_sets(self):
        """
        The standard high-confidence / high-impact / low-risk
        recommendation sets, delegating to the prioritisation
        authority.
        """

        return (
            self.recommendation_prioritisation_service
            .recommendation_sets()
        )

    def get_savings_projection(self):
        """
        Aggregate savings projection over the prioritised
        recommendations, delegating to the prioritisation authority.
        """

        return (
            self.recommendation_prioritisation_service
            .savings_projection()
        )

    # ---------------------------------------------------------
    # Durable recommendation records (Sprint 10 correction)
    #
    # The recommendation rows themselves are created by the canonical
    # pipeline (the run is what produces them). This boundary exposes
    # the human decision and history reads over those durable
    # records. Acceptance is performed by ExecutionService.approve,
    # which freezes the presented priority snapshot and links the
    # execution job.
    # ---------------------------------------------------------

    def get_persisted_history(
        self,
        media_id: int,
    ):
        """
        All durable recommendation records for one media lineage,
        newest first, with their lifecycle events. Historical records
        are never rewritten by newer recommendations.
        """

        self._require_records()

        records = (
            self.recommendation_records.list_by_media(
                media_id
            )
        )

        return [
            {
                "recommendation": record,
                "events": (
                    self.recommendation_records.events_for(
                        record.id
                    )
                ),
            }
            for record in records
        ]

    def reject_recommendation(
        self,
        *,
        recommendation_id: int,
        rejected_by: str = "human",
        reason: str | None = None,
    ):
        """
        Record a human rejection of one proposed recommendation.

        Rejection is a durable, attributable historical decision; it
        never deletes or rewrites the recommendation.
        """

        self._require_records()

        record = self.recommendation_records.get(
            recommendation_id
        )

        if record is None:

            raise ValueError(
                f"recommendation {recommendation_id} not found"
            )

        return (
            self.recommendation_records.transition(
                recommendation_id,
                new_state="rejected",
                expected_current=("proposed", "accepted"),
                actor=rejected_by,
                detail=reason,
            )
        )

    def get_recommendation(self, recommendation_id: int):
        """
        One durable recommendation record with its lifecycle events.

        Raises ValueError when the record does not exist. The record
        is the historical result AS PRODUCED BY ITS RUN; this read
        never re-derives or reinterprets it.
        """

        self._require_records()

        record = self.recommendation_records.get(
            recommendation_id
        )

        if record is None:

            raise ValueError(
                f"recommendation {recommendation_id} not found"
            )

        return {
            "recommendation": record,
            "events": (
                self.recommendation_records.events_for(
                    record.id
                )
            ),
        }

    def get_latest_record(self, media_id: int):
        """
        The newest durable recommendation record for one lineage,
        or None when the lineage has none (for example data that
        predates recommendation persistence).
        """

        self._require_records()

        return self.recommendation_records.latest_for_media(
            media_id
        )

    def compare_recommendations(
        self,
        recommendation_id_a: int,
        recommendation_id_b: int,
    ):
        """
        Compare two DURABLE recommendation records of the same
        media lineage.

        Comparison semantics (Sprint 12):

        - subjects: exactly the two persisted records requested
        - dimension: field-by-field over the produced payload,
          acceptance snapshot and lifecycle facts
        - authoritative source: the stored rows only; nothing is
          recomputed from current intelligence or configuration
        - unavailable data: reported as unavailable on the side
          that lacks it; absence is NEVER presented as a change
        - meaningful difference: both sides present AND unequal

        Raises ValueError when either record is missing or the two
        records belong to different media lineages. No causality is
        claimed anywhere in the result.
        """

        self._require_records()

        left = self.recommendation_records.get(
            recommendation_id_a
        )

        right = self.recommendation_records.get(
            recommendation_id_b
        )

        if left is None:

            raise ValueError(
                f"recommendation {recommendation_id_a} not found"
            )

        if right is None:

            raise ValueError(
                f"recommendation {recommendation_id_b} not found"
            )

        if left.media_id != right.media_id:

            raise ValueError(
                f"Cannot compare recommendations from different "
                f"media lineages ({left.media_id} vs "
                f"{right.media_id})"
            )

        fields = _compare_fields(
            [
                ("opportunity", "Opportunity"),
                ("opportunity_score", "Score"),
                ("confidence", "Confidence"),
                (
                    "estimated_saving_percent",
                    "Estimated savings %",
                ),
                (
                    "estimated_saved_bytes",
                    "Estimated saved bytes",
                ),
                ("risk", "Risk"),
                ("priority_score", "Priority at acceptance"),
                ("rank_at_presentation", "Rank at acceptance"),
                ("analysis_run_id", "Producing run"),
                ("file_observation_id", "Observation"),
                ("execution_job_id", "Execution job"),
            ],
            left,
            right,
        )

        fields.append(
            _compare_sequences(
                "contributing_rules",
                "Contributing rules",
                left.contributing_rules,
                right.contributing_rules,
            )
        )

        fields.append(
            _compare_sequences(
                "rationale_lines",
                "Rationale line count",
                left.rationale,
                right.rationale,
                summary=len,
            )
        )

        return {
            "left": _record_ref(left),
            "right": _record_ref(right),
            "media_id": left.media_id,
            "same_media": True,
            "same_run": (
                left.analysis_run_id == right.analysis_run_id
            ),
            "states": {
                "left": left.state,
                "right": right.state,
            },
            "intelligence_identity": _compare_identity(
                left.intelligence_identity,
                right.intelligence_identity,
            ),
            "fields": fields,
        }

    def has_durable_records(self) -> bool:
        """
        Whether durable recommendation workflows are available on
        this instance (the repository was wired at composition).
        """

        return self.recommendation_records is not None

    def _require_records(self):

        if self.recommendation_records is None:

            raise RuntimeError(
                "RecommendationService was constructed without a "
                "recommendation repository; durable "
                "recommendation workflows are unavailable"
            )

# ---------------------------------------------------------
# Sprint 12 recommendation-comparison helpers
#
# Pure functions over the two persisted records. They implement the
# comparison semantics documented on compare_recommendations:
# a difference is claimed only when both sides exist and differ;
# missing values are reported as unavailable, never as changes.
# ---------------------------------------------------------


def _record_ref(record):

    return {
        "id": record.id,
        "media_id": record.media_id,
        "analysis_run_id": record.analysis_run_id,
        "state": record.state,
        "created_at": record.created_at,
        "intelligence_identity": record.intelligence_identity,
    }


def _side_values(left_value, right_value):

    if left_value is None and right_value is None:

        return "neither"

    if right_value is None:

        return "left_only"

    if left_value is None:

        return "right_only"

    return "both"


def _compare_fields(specs, left, right):

    fields = []

    for key, label in specs:

        left_value = getattr(left, key, None)

        right_value = getattr(right, key, None)

        availability = _side_values(left_value, right_value)

        changed = None

        if availability == "both":

            changed = left_value != right_value

        fields.append(
            {
                "key": key,
                "label": label,
                "left": left_value,
                "right": right_value,
                "availability": availability,
                "changed": changed,
            }
        )

    return fields


def _compare_sequences(
    key,
    label,
    left_items,
    right_items,
    summary=None,
):

    left_list = list(left_items or [])

    right_list = list(right_items or [])

    if summary is not None:

        left_value = summary(left_list)

        right_value = summary(right_list)

    else:

        left_value = left_list

        right_value = right_list

    availability = _side_values(
        left_list or None, right_list or None
    )

    changed = None

    if availability == "both":

        changed = left_list != right_list

    return {
        "key": key,
        "label": label,
        "left": left_value,
        "right": right_value,
        "availability": availability,
        "changed": changed,
    }


def _compare_identity(left_digest, right_digest):
    """
    Compare two recorded intelligence identity digests.

    Verdicts are strictly derived from the stored values; a digest
    that was never recorded is reported as unrecorded rather than
    being treated as equal to or different from anything.
    """

    verdict = "unrecorded"

    if left_digest and right_digest:

        verdict = (
            "identical"
            if left_digest == right_digest
            else "different"
        )

    elif left_digest and not right_digest:

        verdict = "right_unrecorded"

    elif right_digest and not left_digest:

        verdict = "left_unrecorded"

    return {
        "left": left_digest,
        "right": right_digest,
        "verdict": verdict,
    }
