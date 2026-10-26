from dataclasses import replace

from app.services.filesystem_currentness import (
    STATE_MISSING,
    STATE_PRESENT,
    STATE_UNAVAILABLE,
    probe_current_file,
)


class OpportunityQueueService:
    """
    Provides ranked, CURRENT-VALID optimisation opportunities.

    Currentness is decided by AnalysisValidityService - the single
    validity authority in the architecture. Only active media lineages
    with a valid completed analysis for their current filesystem state
    produce a candidate, and at most one candidate is returned per
    lineage.

    Standing decisions are presentation-level and approval-admissibility
    filters only. A refused standing decision suppresses that specific
    lineage + proposition. It never alters the underlying analysis,
    assessment, validity result, or Fusion output.

    This service does not:
    - analyse media
    - execute optimisation
    - change assessments
    - reimplement validity logic
    - alter Fusion's persisted suppressed propositions
    """

    def __init__(
        self,
        opportunity_repository,
        media_repository,
        analysis_validity_service,
        standing_decision_repository=None,
        current_state_provider=None,
    ):

        self.repository = opportunity_repository
        self.media_repository = media_repository
        self.validity_service = analysis_validity_service
        self.standing_decision_repository = (
            standing_decision_repository
        )

        self.current_state_provider = (
            current_state_provider
            or (
                lambda lineage: probe_current_file(
                    lineage.file_path
                )
            )
        )

    def _standing_refused_propositions(self, media_id):
        if self.standing_decision_repository is None:
            return set()

        return set(
            self.standing_decision_repository
            .get_refused_propositions(media_id)
        )

    @staticmethod
    def _active_propositions(candidate):
        """
        Return the candidate's presentable opportunity propositions.

        Fusion suppression remains separate: only propositions that are
        executable opportunity signals and were not analytically
        suppressed are considered here.
        """

        fusion_suppressed = set(
            getattr(
                candidate,
                "suppressed_propositions",
                (),
            )
            or ()
        )

        propositions = set()

        for signal in (
            getattr(candidate, "signals", ())
            or ()
        ):

            if getattr(signal, "direction", "") not in (
                "optimize",
                "remux",
            ):
                continue

            proposition = (
                getattr(signal, "proposition", "")
                or ""
            )

            if not proposition:
                continue

            if proposition in fusion_suppressed:
                continue

            propositions.add(proposition)

        return propositions

    def get_queue(self):

        queue = []

        # Active lineages are the existence-authoritative enumeration.
        # Per-lineage currentness is DERIVED through the existing
        # AnalysisValidityService - never reimplemented here.
        for lineage in (
            self.media_repository
            .get_active_lineages()
        ):

            live = self.current_state_provider(lineage)

            if live.state == STATE_PRESENT:

                validity = self.validity_service.get_validity(
                    lineage.id,
                    current_size_bytes=live.size_bytes,
                    current_file_mtime_ns=live.file_mtime_ns,
                )

            elif live.state == STATE_MISSING:

                validity = self.validity_service.get_validity(
                    lineage.id,
                    current_missing=True,
                )

            else:

                validity = self.validity_service.get_validity(
                    lineage.id,
                    current_unavailable=True,
                )

            # No valid completed analysis for the current state.
            if validity.valid_analysis_run is None:
                continue

            # A valid analysis without an opportunity remains valid
            # but produces no queue candidate.
            if validity.current_opportunity is None:
                continue

            candidate = self.repository.build_candidate(
                lineage,
                validity.current_opportunity,
                analysis_run_id=(
                    validity.valid_analysis_run.id
                    if validity.valid_analysis_run
                    is not None
                    else validity.valid_run_id
                ),
                observation_id=(
                    validity.current_observation.id
                    if validity.current_observation
                    is not None
                    else None
                ),
            )

            active_propositions = (
                self._active_propositions(candidate)
            )

            standing_refused = (
                self._standing_refused_propositions(
                    lineage.id
                )
            )

            standing_suppressed = tuple(
                sorted(
                    active_propositions
                    & standing_refused
                )
            )

            # Do not present a candidate when every currently
            # presentable proposition has been explicitly refused.
            #
            # No underlying assessment or validity state is changed.
            if (
                active_propositions
                and active_propositions
                <= set(standing_suppressed)
            ):
                continue

            if standing_suppressed:
                candidate = replace(
                    candidate,
                    standing_suppressed_propositions=(
                        standing_suppressed
                    ),
                )

            queue.append(candidate)

        queue.sort(
            key=lambda candidate: (
                candidate.opportunity_score
            ),
            reverse=True,
        )

        return queue

    def active_propositions_for(self, media_id):
        """
        Currently presentable propositions for one media lineage,
        resolved authoritatively from the current queue at call
        time. Read-only: no state changes and no revalidation
        beyond the queue's own currentness derivation. Returns an
        empty tuple when the lineage has no presentable candidate
        (already refused, suppressed, stale, or never an
        opportunity), so callers create no refusal records in
        that case.
        """

        try:
            wanted = int(media_id)
        except (TypeError, ValueError):
            return ()

        for candidate in self.get_queue():
            if candidate.media_id == wanted:
                return tuple(
                    sorted(
                        self._active_propositions(candidate)
                    )
                )

        return ()