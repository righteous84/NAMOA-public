"""
Execution application service (Sprint 9, extended Phase 6).

The single operational boundary for the Execution Engine. External
interfaces (CLI/GUI/API) may ONLY approve, plan, run, roll back,
recover, delete-original and run the queue through this service; they
never touch FFmpeg or the filesystem themselves.

Lifecycle and safety model:

    recommendation (current-valid queue candidate)
        ↓  approve(media_id): explicit human action; the requested
        ↓  transformation (what the user approved) is frozen, the
        ↓  exact source observation is linked, and delete-original
        ↓  intent (default false) is recorded
    job 'approved' (source fingerprint frozen on the record)
        ↓  plan(job_id): policy validation + transformation-aware
        ↓  plan snapshot + predicted savings
    job 'planned'
        ↓  run(job_id): freshness re-check (size/mtime/inode/sha256),
        ↓  disk-space preflight, FFmpeg (arg list), operation-aware
        ↓  verification, pre-swap source-drift revalidation, atomic
        ↓  replacement (original preserved under recorded backup
        ↓  path), new filesystem observation via the canonical lineage
        ↓  mechanism, measured savings from actual observations
    job 'succeeded' | honest failure/interrupt states
        ↓  delete_original(job_id) (explicit, separate lifecycle):
        ↓  preserved original removed ONLY after verified successful
        ↓  replacement; recorded as original_deleted | deletion_failed

Guarantees enforced here:

- a recommendation alone can never execute: an explicit approval
  record is required, and running requires the approval record
- a changed source makes the job stale; stale jobs never execute and
  never re-target
- the requested transformation is immutable; planning never silently
  changes it and never re-targets a different operation
- policy validation cannot be bypassed: no run without a stored
  allow decision made by the policy boundary
- source drift during a long encode can never cause replacement: the
  source is revalidated immediately before the swap
- the original survives every failure mode up to replacement; after
  replacement the original bytes remain under the recorded backup
  path until an explicit rollback consumes them or an explicit
  delete-original action removes them
- every state transition is persisted as it happens so interruption
  is detectable and recoverable
"""

import os
import shutil
import dataclasses

from app.execution.lineage import (
    find_existing_observation_id,
    record_execution_observation,
)

from app.execution.engine import (
    DEFAULT_PROBER,
    DEFAULT_RUNNER,
    ReplacementFailed,
    cleanup_path,
    make_temp_output,
    perform_replacement,
    restore_original,
    sha256_of,
    verify_output,
)

from app.execution.ffmpeg import build_argv

from app.utils.file_identity import (
    FileIdentityError,
    capture_sha256,
)

from app.execution.policy import (
    OPERATION_REMUX_MP4,
    validate as validate_policy,
)

from app.execution.operations import (
    EXECUTABLE_OPERATIONS,
    HEVC_CONVERSION_SOURCE_CODECS,
    OPERATION_CODEC_CONVERSION,
    OPERATION_CODEC_CONVERSION_MKV,
    get_operation,
    operation_for_proposition,
    require_operation,
)

from app.retention.assessment import (
    VERDICT_OK,
    assess as assess_retention,
    check_approval as check_retention_approval,
)

from app.execution.planning import (
    EncodingSpeedPolicy,
)

from app.models.execution import (
    build_plan,
)

from app.models.transformation import (
    RequestedTransformation,
    TransformationProposition,
)

from app.application.transformation_service import (
    NoExecutablePropositionError,
)

from app.models.user_policy import (
    UserPolicy,
)


#: Headroom required above the source size when checking disk space
#: before an execution (staged output can never be assumed smaller
#: merely because an operation is expected to save space).
STAGING_HEADROOM_BYTES = 512 * 1024 * 1024


class SourceDriftError(ValueError):
    """
    Raised when the source changed between the pre-encode freshness
    check and the replacement swap. This is NOT `interrupted`: the
    process completed; the filesystem moved under it.
    """


#: operation -> planning proposition used to resolve planning/cost
#: semantics. The inverse (proposition -> operation) is owned by the
#: operation registry.
_PLAN_OPERATION_PROPOSITIONS = {
    OPERATION_REMUX_MP4: "container_remux",
    OPERATION_CODEC_CONVERSION: "codec_conversion",
    OPERATION_CODEC_CONVERSION_MKV: "codec_conversion",
}


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


class ExecutionService:
    """
    Application-facing execution workflows.
    """

    def __init__(
        self,
        *,
        execution_repository,
        recommendation_service,
        media_repository,
        recommendation_repository=None,
        transformation_service=None,
        prediction_service=None,
        runner=None,
        prober=None,
        notification_service=None,
        user_policy_service=None,
    ):

        self.executions = execution_repository

        self.recommendations_service = (
            recommendation_service
        )

        self.recommendation_records = (
            recommendation_repository
        )

        self.media_repository = media_repository

        self.transformations = transformation_service

        self.predictor = prediction_service

        self._runner = runner or DEFAULT_RUNNER

        self._prober = prober or DEFAULT_PROBER

        self.notification_service = notification_service

        self.user_policy_service = user_policy_service

    def _retention_policy(self):
        """Effective retention preferences (durable or default)."""

        service = self.user_policy_service

        if service is None:
            return {
                "subtitle_retention": "allow_loss",
                "content_retention": "normal",
            }

        try:
            policy = service.get_effective_policy()
        except Exception:
            return {
                "subtitle_retention": "allow_loss",
                "content_retention": "normal",
            }

        return {
            "subtitle_retention": (
                getattr(policy, "subtitle_retention", None)
                or "allow_loss"
            ),
            "content_retention": (
                getattr(policy, "content_retention", None)
                or "normal"
            ),
        }

    def _enforce_retention_policy(
        self, candidate, transformation, *, path, stat
    ):
        """Server-side strict-retention approval gate.

        Authoritative (Preview gates are advisory): refuses blocked
        layouts always (acknowledgement can never bypass them), and
        refuses lossy/unassessable layouts under strict preferences
        unless a matching explicit acknowledgement is frozen on the
        transformation. Under defaults, lossy/unassessable layouts
        pass here (builders remain the backstop for genuinely
        blocked layouts at plan/build time). Unprobable sources
        pass here under defaults (plan refuses as today) but refuse
        under strict policy.
        """

        preferences = self._retention_policy()

        strict = (
            preferences["subtitle_retention"] == "preserve"
            or preferences["content_retention"]
            == "preserve_supported"
        )

        try:
            source_summary = self._prober(path)
        except Exception:
            source_summary = None

        if not isinstance(source_summary, dict):
            if strict:
                raise ValueError(
                    "strict retention policy requires a "
                    "probable source; the source could not be "
                    "probed as valid media"
                )

            return

        pins = {
            "observation_id": getattr(
                candidate, "observation_id", None
            ),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

        try:
            assessment = assess_retention(
                source_summary,
                transformation.to_dict()
                if hasattr(transformation, "to_dict")
                else transformation,
                subtitle_retention=(
                    preferences["subtitle_retention"]
                ),
                content_retention=(
                    preferences["content_retention"]
                ),
                pins=pins,
            )
        except ValueError:
            if strict:
                raise

            return

        if assessment.verdict == VERDICT_OK:
            return

        check_retention_approval(
            assessment,
            transformation,
            subtitle_retention=(
                preferences["subtitle_retention"]
            ),
            content_retention=(
                preferences["content_retention"]
            ),
            pins=pins,
        )

    def _notify(
        self,
        category: str,
        title: str,
        message: str,
        *,
        media_id=None,
        job_id=None,
        recommendation_id=None,
    ):
        """
        Best-effort notification emission. A notification write must
        never fail or alter the underlying execution operation.
        """

        if self.notification_service is None:
            return

        try:

            self.notification_service.create(
                category=category,
                title=title,
                message=message,
                media_id=media_id,
                execution_job_id=job_id,
                recommendation_id=recommendation_id,
            )

        except Exception:

            from app.utils.logger import logger

            logger.warning(
                "notification write skipped (best-effort): "
                f"{category} {title}"
            )

    def _media_name(self, media_id) -> str:
        try:
            lineage = self.media_repository.get_media_item(
                media_id
            )
            if lineage is not None and lineage.file_name:
                return lineage.file_name
        except ValueError:
            pass
        return f"media {media_id}"

    def _measured_saved_text(self, job, result_observation_id) -> str:
        """
        The measured size delta between the approved source and the
        verified result observation. This is measured data, never an
        estimate. Returns a conservative line when the delta cannot be
        established.
        """

        if result_observation_id is None:
            return "Result verified and recorded"

        observation = self.media_repository.get_observation_by_id(
            result_observation_id
        )

        if (
            observation is None
            or observation.size_bytes is None
            or job.source_size_bytes is None
        ):
            return "Result verified and recorded"

        delta = job.source_size_bytes - observation.size_bytes

        if delta > 0:
            return f"Saved {self._format_bytes(delta)} (measured)"

        return "Result verified and recorded"

    @staticmethod
    def _format_bytes(value) -> str:
        step = 1024.0
        for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
            if value < step:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.2f} {unit}"
            value /= step
        return f"{value:.2f} TiB"

    # -------------------------------------------------
    # recommendation linkage / lifecycle mirroring
    #
    # The execution job remains the single execution authority.
    # The linked recommendation mirrors job milestones ONLY at the
    # moments they happen here, and every mirror is recorded as an
    # immutable lifecycle event. When no recommendation repository is
    # wired (legacy constructions), linkage is skipped and behaviour
    # is unchanged.
    # -------------------------------------------------

    def _linked_recommendation(self, job):

        if self.recommendation_records is None:
            return None

        return (
            self.recommendation_records
            .get_by_execution_job(job.id)
        )

    def _mirror_state(
        self,
        job,
        *,
        new_state,
        expected_current,
        detail=None,
    ):

        record = self._linked_recommendation(job)

        if record is None:
            return

        try:

            self.recommendation_records.transition(
                record.id,
                new_state=new_state,
                expected_current=expected_current,
                actor="execution",
                detail=detail,
                execution_job_id=job.id,
            )

        except ValueError as error:

            # Lifecycle mirroring must never break or corrupt an
            # honest execution outcome; a mapping surprise is logged
            # for investigation instead of silently rewriting state.

            from app.utils.logger import logger

            logger.warning(
                f"recommendation mirror skipped for job "
                f"{job.id}: {error}"
            )

    # -------------------------------------------------
    # approval
    # -------------------------------------------------

    def approve(
        self,
        media_id,
        *,
        approved_by="human",
        delete_original_requested=False,
        parameters=None,
        transformation_source=None,
        transformation_context=None,
    ):
        """
        Explicitly approve the CURRENT-VALID optimisation
        recommendation for one lineage.

        A recommendation alone never executes anything: this call is
        the approval boundary. The source fingerprint is frozen onto
        the record at approval time so later runs can detect drift.

        The requested transformation (what the user approved) is
        captured from the surviving proposition signals and frozen
        onto the record. `delete_original_requested` records the
        explicit, separate file-lifecycle choice (default false).

        `transformation_source` / `transformation_context` are
        optional provenance markers (for example a Preview user
        override). They are applied only to a successfully built
        transformation, never to the legacy remux fallback, and
        default to no marking so existing callers are unaffected.

        Duplicate-action protection (Sprint 11): approval is refused
        while a non-terminal job already exists for this lineage,
        when the human rejected the producing recommendation, or
        when that recommendation has already completed optimisation.
        """

        candidate = self._current_candidate(media_id)

        self._assert_not_duplicated(candidate)

        recommendation_id = self._find_recommendation_id(
            candidate
        )

        transformation = self._build_transformation(
            candidate,
            recommendation_id=recommendation_id,
            parameters=parameters,
            transformation_source=transformation_source,
            transformation_context=transformation_context,
        )

        return self._create_approved_job(
            candidate,
            transformation,
            recommendation_id=recommendation_id,
            approved_by=approved_by,
            delete_original_requested=(
                delete_original_requested
            ),
        )

    def approve_advanced(
        self,
        media_id,
        *,
        operation,
        parameters=None,
        approved_by="human",
        delete_original_requested=False,
        transformation_source=None,
        transformation_context=None,
    ):
        """
        Explicitly approve a user-selected advanced operation for
        one lineage.

        The operation must be registered and executable in the
        closed operation registry
        (app/execution/operations.py); parameters are validated
        against that operation's definition before anything is
        recorded. Unknown operations, non-executable operations,
        and invalid parameters are refused with ValueError and
        create no job.

        Every other approval semantic is identical to approve():
        the candidate must be current-valid, duplicate queueing is
        refused, the source fingerprint and exact source observation
        are frozen onto the record, and the requested
        transformation is recorded with source 'advanced'.
        Planning, policy validation, execution, verification, and
        recovery all proceed through the existing boundaries.
        Intelligence and recommendation layers can never execute
        through this path: it only records an approved
        transformation for later planning and execution.
        """

        candidate = self._current_candidate(media_id)

        self._assert_not_duplicated(candidate)

        recommendation_id = self._find_recommendation_id(
            candidate
        )

        transformation = self._build_advanced_transformation(
            candidate,
            operation=operation,
            parameters=parameters,
            recommendation_id=recommendation_id,
            transformation_source=transformation_source,
            transformation_context=transformation_context,
        )

        return self._create_approved_job(
            candidate,
            transformation,
            recommendation_id=recommendation_id,
            approved_by=approved_by,
            delete_original_requested=(
                delete_original_requested
            ),
        )

    def _validate_candidate_source(self, candidate):
        """
        Prove that the live source is the content described by the
        candidate's linked analysis observation.

        Phase 18 approval integrity: the live file must carry the
        same content identity as the observation that produced the
        candidate. The returned stat and digest are the exact values
        frozen onto the approved job; the job must not reread and
        re-baseline the source.

        A candidate with no trustworthy observation content identity
        is refused. Historical observations are never assigned
        invented hashes.
        """

        observation_id = candidate.observation_id

        if observation_id is None:

            raise ValueError(
                "source cannot be verified: the candidate has no "
                "linked analysis observation; rescan and analyse "
                "again"
            )

        observation = (
            self.media_repository.get_observation_by_id(
                observation_id
            )
        )

        if observation is None:

            raise ValueError(
                "source cannot be verified: the candidate's "
                "analysis observation is missing; rescan and "
                "analyse again"
            )

        if observation.media_id != candidate.media_id:

            raise ValueError(
                "source cannot be verified: the candidate's "
                "observation belongs to a different media lineage"
            )

        if not observation.sha256_hash:

            raise ValueError(
                "source cannot be verified: the analysis has no "
                "content identity (SHA-256); rescan and analyse "
                "the current source before approval"
            )

        expected_inode = observation.filesystem_inode or None

        try:

            digest, stat = capture_sha256(
                candidate.file_path,
                expected_size_bytes=observation.size_bytes,
                expected_file_mtime_ns=(
                    observation.file_mtime_ns
                ),
                expected_inode=expected_inode,
            )

        except FileIdentityError as error:

            raise ValueError(
                f"source cannot be verified: {error}. "
                "The source changed or could not be inspected "
                "reliably; rescan and analyse again before "
                "approval."
            ) from error

        if digest != observation.sha256_hash:

            raise ValueError(
                "source cannot be verified: the live SHA-256 does "
                "not match the analysed content; rescan and "
                "analyse the current source before approval"
            )

        return stat, digest

    def _create_approved_job(
        self,
        candidate,
        transformation,
        *,
        recommendation_id=None,
        approved_by="human",
        delete_original_requested=False,
    ):
        """
        The single job-creation tail shared by approve() and
        approve_advanced(). Validates the live source against the
        candidate's analysed observation, freezes those exact
        values, links the exact source observation, records the
        immutable requested transformation and the separate
        delete-original intent, links the accepted recommendation,
        and notifies.
        """

        media_id = candidate.media_id

        path = candidate.file_path

        stat, source_sha256 = (
            self._validate_candidate_source(candidate)
        )

        self._enforce_retention_policy(
            candidate,
            transformation,
            path=path,
            stat=stat,
        )

        job_id = self.executions.create(
            media_id=media_id,
            opportunity=candidate.opportunity,
            analysis_run_id=candidate.analysis_run_id,
            source_path=path,
            source_size_bytes=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            source_inode=stat.st_ino,
            source_sha256=source_sha256,
            approved_by=approved_by,
            source_observation_id=candidate.observation_id,
            requested_transformation=transformation.to_dict(),
            delete_original_requested=(
                delete_original_requested
            ),
        )

        self._link_acceptance(
            job_id=job_id,
            candidate=candidate,
            approved_by=approved_by,
            recommendation_id=recommendation_id,
        )

        self._notify(
            "success",
            "Optimisation approved",
            f"{candidate.file_name} · {candidate.opportunity} · "
            "Added to optimisation queue",
            media_id=media_id,
            job_id=job_id,
        )

        return job_id

    def approve_selected(
        self,
        media_ids,
        *,
        approved_by="human",
        delete_original_requested=False,
    ):
        """
        Approve the current-valid recommendations for several
        lineages as a group.

        This is a thin loop over the single approval boundary
        (approve); it adds no approval semantics of its own. Every
        item is decided independently: a refusal for one lineage
        never prevents or silently skips another.

        Returns per-item results:

            {"approved": [{"media_id", "job_id"}...],
             "refused":  [{"media_id", "reason"}...]}
        """

        approved = []

        refused = []

        seen = set()

        for raw_id in media_ids:

            media_id = int(raw_id)

            if media_id in seen:

                refused.append(
                    {
                        "media_id": media_id,
                        "reason": (
                            "requested twice in the same "
                            "selection"
                        ),
                    }
                )

                continue

            seen.add(media_id)

            try:

                job_id = self.approve(
                    media_id,
                    approved_by=approved_by,
                    delete_original_requested=(
                        delete_original_requested
                    ),
                )

            except ValueError as error:

                refused.append(
                    {
                        "media_id": media_id,
                        "reason": str(error),
                    }
                )

                continue

            approved.append(
                {"media_id": media_id, "job_id": job_id}
            )

        return {
            "approved": approved,
            "refused": refused,
        }

    def approve_selected_advanced(
        self,
        requests,
        *,
        approved_by="human",
        delete_original_requested=False,
    ):
        """
        Approve user-selected advanced operations for several
        lineages as a group.

        `requests` is a sequence of per-file dicts, each with
        `media_id`, `operation`, and optional `parameters`. This
        is a thin loop over the single advanced approval boundary
        (approve_advanced); it adds no approval semantics of its
        own. Every file is validated independently against the
        closed operation registry: a refusal for one file (unknown
        operation, non-executable operation, invalid parameters,
        stale recommendation, duplicate queueing) never prevents,
        approves, or silently skips another file.

        Returns per-item results:

            {"approved": [{"media_id", "job_id"}...],
             "refused":  [{"media_id", "reason"}...]}
        """

        approved = []

        refused = []

        seen = set()

        for request in requests or []:

            if isinstance(request, dict):

                raw_id = request.get("media_id")

                operation = request.get("operation")

                parameters = request.get("parameters")

            else:

                raw_id = request

                operation = None

                parameters = None

            try:

                media_id = int(raw_id)

            except (TypeError, ValueError):

                refused.append(
                    {
                        "media_id": raw_id,
                        "reason": (
                            "invalid media id in bulk "
                            "advanced request"
                        ),
                    }
                )

                continue

            if media_id in seen:

                refused.append(
                    {
                        "media_id": media_id,
                        "reason": (
                            "requested twice in the same "
                            "selection"
                        ),
                    }
                )

                continue

            seen.add(media_id)

            try:

                job_id = self.approve_advanced(
                    media_id,
                    operation=operation,
                    parameters=parameters,
                    approved_by=approved_by,
                    delete_original_requested=(
                        delete_original_requested
                    ),
                )

            except (ValueError, TypeError) as error:

                refused.append(
                    {
                        "media_id": media_id,
                        "reason": str(error),
                    }
                )

                continue

            approved.append(
                {"media_id": media_id, "job_id": job_id}
            )

        return {
            "approved": approved,
            "refused": refused,
        }

    def plan_selected(self, job_ids, user_policy=None):
        """
        Plan several approved jobs as a group.

        This is a thin loop over the single planning boundary
        (plan); it adds no planning semantics of its own. Every
        job is validated independently (freshness, policy,
        operation preconditions): a refusal for one job never
        prevents or silently skips another.

        Returns per-item results:

            {"planned": [{"job_id"}...],
             "refused": [{"job_id", "reason"}...]}
        """

        planned = []

        refused = []

        seen = set()

        for raw_id in job_ids or []:

            try:

                job_id = int(raw_id)

            except (TypeError, ValueError):

                refused.append(
                    {
                        "job_id": raw_id,
                        "reason": "invalid job id in bulk plan",
                    }
                )

                continue

            if job_id in seen:

                refused.append(
                    {
                        "job_id": job_id,
                        "reason": (
                            "requested twice in the same "
                            "selection"
                        ),
                    }
                )

                continue

            seen.add(job_id)

            try:

                self.plan(job_id, user_policy=user_policy)

            except ValueError as error:

                refused.append(
                    {
                        "job_id": job_id,
                        "reason": str(error),
                    }
                )

                continue

            planned.append({"job_id": job_id})

        return {
            "planned": planned,
            "refused": refused,
        }

    def run_selected(self, job_ids):
        """
        Execute several planned jobs serially, one at a time, in
        the order given.

        This is a thin loop over the single execution boundary
        (run); it adds no execution semantics of its own. Every
        job runs through the full safe sequence independently
        (freshness, disk preflight, FFmpeg, operation-aware
        verification, pre-swap revalidation, atomic replacement,
        new observation, measured savings). A terminal failure of
        one job never falsely marks another job successful and
        never prevents later jobs from running.

        Returns per-item results:

            {"succeeded": [{"job_id"}...],
             "failed":    [{"job_id", "state", "reason"}...]}
        """

        succeeded = []

        failed = []

        seen = set()

        for raw_id in job_ids or []:

            try:

                job_id = int(raw_id)

            except (TypeError, ValueError):

                failed.append(
                    {
                        "job_id": raw_id,
                        "state": None,
                        "reason": "invalid job id in bulk run",
                    }
                )

                continue

            if job_id in seen:

                failed.append(
                    {
                        "job_id": job_id,
                        "state": None,
                        "reason": (
                            "requested twice in the same "
                            "selection"
                        ),
                    }
                )

                continue

            seen.add(job_id)

            try:

                result = self.run(job_id)

            except ValueError as error:

                failed.append(
                    {
                        "job_id": job_id,
                        "state": None,
                        "reason": str(error),
                    }
                )

                continue

            if result.state == "succeeded":

                succeeded.append({"job_id": job_id})

            else:

                failed.append(
                    {
                        "job_id": job_id,
                        "state": result.state,
                        "reason": result.error,
                    }
                )

        return {
            "succeeded": succeeded,
            "failed": failed,
        }

    def _assert_not_duplicated(self, candidate):
        """
        Refuse approval that would double-queue or contradict an
        existing durable human decision. Uses the existing
        persistence authorities only; no new state is introduced.
        """

        active = (
            self.executions.list_active_for_media(
                candidate.media_id
            )
        )

        if active:

            raise ValueError(
                f"media {candidate.media_id} already has "
                f"execution job {active[0].id} in state "
                f"'{active[0].state}'; it cannot be queued "
                f"again until that job reaches a terminal state"
            )

        if self.recommendation_records is None:

            return

        records = (
            self.recommendation_records.get_by_run(
                candidate.analysis_run_id
            )
        )

        for record in records:

            if record.media_id != candidate.media_id:

                continue

            if record.state == "rejected":

                raise ValueError(
                    f"the recommendation for media "
                    f"{candidate.media_id} from run "
                    f"{candidate.analysis_run_id} was "
                    f"rejected; approve a newer analysis "
                    f"instead"
                )

            if record.state == "completed":

                raise ValueError(
                    f"the recommendation for media "
                    f"{candidate.media_id} from run "
                    f"{candidate.analysis_run_id} already "
                    f"completed optimisation"
                )

    def _find_recommendation_id(self, candidate):
        """
        The durable accepted recommendation id for the candidate's
        producing run, or None when recommendation records are not
        wired or no proposed record exists.
        """

        if self.recommendation_records is None:

            return None

        record = (
            self.recommendation_records
            .find_proposed_for_run(
                candidate.media_id,
                candidate.analysis_run_id,
            )
        )

        if record is None:

            return None

        return record.id

    def _build_transformation(
        self,
        candidate,
        *,
        recommendation_id,
        parameters,
        transformation_source=None,
        transformation_context=None,
    ):
        """
        The requested transformation for an approval.

        When a transformation service is wired, it derives the
        transformation from the candidate's surviving executable
        signals (or validates advanced parameters). When the service
        is absent or the candidate carries no executable signal
        (legacy fixtures), a remux_mp4 default transformation is used
        so existing behaviour is preserved.

        Provenance markers (`transformation_source` /
        `transformation_context`) are applied only to a
        successfully built transformation, never to the legacy
        fallback, so fallback rows keep their historical meaning.
        """

        if self.transformations is not None:

            try:

                transformation = (
                    self.transformations.build_from_candidate(
                        candidate,
                        recommendation_id=recommendation_id,
                        parameters=parameters,
                    )
                )

                return self._mark_transformation(
                    transformation,
                    source=transformation_source,
                    context=transformation_context,
                )

            except NoExecutablePropositionError:

                # No surviving executable proposition (legacy test
                # data without signals): fall back to the remux
                # default rather than refusing the existing approval
                # boundary. Parameter-validation ValueErrors are NOT
                # caught here: invalid parameters must propagate.
                pass

        return self._default_transformation(
            candidate,
            recommendation_id=recommendation_id,
        )

    @staticmethod
    def _mark_transformation(
        transformation, *, source=None, context=None
    ):
        """Apply optional provenance markers (no marking by default)."""

        if source is None and context is None:
            return transformation

        return dataclasses.replace(
            transformation,
            source=(
                source
                if source is not None
                else transformation.source
            ),
            context_detail=(
                dict(context)
                if context is not None
                else dict(transformation.context_detail)
            ),
        )

    def _build_advanced_transformation(
        self,
        candidate,
        *,
        operation,
        parameters,
        recommendation_id,
        transformation_source=None,
        transformation_context=None,
    ):
        """
        The requested transformation for an advanced approval:
        the user-selected operation validated against the closed
        registry via TransformationService.build_from_advanced.
        A missing transformation service, an unregistered
        operation, a non-executable operation, and invalid
        parameters all raise ValueError and create no job.
        Provenance markers behave as in _build_transformation.
        """

        if self.transformations is None:

            raise ValueError(
                "advanced approval is unavailable: no "
                "transformation service is wired"
            )

        transformation = self.transformations.build_from_advanced(
            operation=operation,
            parameters=parameters,
            recommendation_id=recommendation_id,
            captured_from_run_id=getattr(
                candidate, "analysis_run_id", None
            ),
            captured_from_observation_id=getattr(
                candidate, "observation_id", None
            ),
        )

        return self._mark_transformation(
            transformation,
            source=transformation_source,
            context=transformation_context,
        )

    def _default_transformation(
        self,
        candidate,
        *,
        recommendation_id,
    ):
        return RequestedTransformation(
            schema_version=1,
            source="recommendation",
            recommendation_id=recommendation_id,
            propositions=(
                TransformationProposition(
                    proposition="container_remux",
                    current_state=None,
                    target_state="mp4",
                    parameters={},
                ),
            ),
            operation=OPERATION_REMUX_MP4,
            preserve_resolution=True,
            preserve_hdr=True,
            audio_handling="copy",
            captured_from_run_id=getattr(
                candidate, "analysis_run_id", None
            ),
            captured_from_observation_id=getattr(
                candidate, "observation_id", None
            ),
            parameters={},
        )

    def _link_acceptance(
        self,
        *,
        job_id,
        candidate,
        approved_by,
        recommendation_id=None,
    ):
        """
        Freeze the accepted recommendation: the exact prioritised
        presentation values are snapshotted, the record moves to
        'accepted', and the durable execution linkage is written.
        """

        if self.recommendation_records is None:
            return

        record = (
            self.recommendation_records
            .find_proposed_for_run(
                candidate.media_id,
                candidate.analysis_run_id,
            )
        )

        if record is None:

            from app.utils.logger import logger

            logger.warning(
                f"no proposed recommendation found for "
                f"media {candidate.media_id} run "
                f"{candidate.analysis_run_id}; execution "
                f"job {job_id} proceeds unlinked"
            )

            return

        priority_score = None
        rank = None
        components = None
        rationale = None

        for item in (
            self.recommendations_service
            .get_prioritised_recommendations()
        ):

            if item.candidate.media_id == (
                candidate.media_id
            ):

                priority_score = item.priority_score
                rank = item.rank
                components = {
                    "score_component": (
                        item.components.score_component
                    ),
                    "confidence_component": (
                        item.components.confidence_component
                    ),
                    "savings_bytes_component": (
                        item.components.savings_bytes_component
                    ),
                    "risk_penalty": (
                        item.components.risk_penalty
                    ),
                    "calibrated_confidence": (
                        item.components.calibrated_confidence
                    ),
                    "risk_value": (
                        item.components.risk_value
                    ),
                    "cost_benefit_ratio": (
                        item.components.cost_benefit_ratio
                    ),
                }
                rationale = list(item.rationale)

                break

        self.recommendation_records \
            .attach_presentation_snapshot(
                record.id,
                priority_score=priority_score,
                rank_at_presentation=rank,
                components=components,
                rationale=rationale,
            )

        self.recommendation_records.transition(
            record.id,
            new_state="accepted",
            expected_current=("proposed",),
            actor=approved_by,
            detail=(
                f"accepted via execution job {job_id}"
            ),
            execution_job_id=job_id,
        )

        self.recommendation_records.link_execution(
            record.id,
            job_id,
        )

        self.executions.attach_recommendation(
            job_id,
            record.id,
        )

    # -------------------------------------------------
    # planning
    # -------------------------------------------------

    def plan(self, job_id, user_policy=None):
        """
        Validate policy against the approved operation and freeze a
        deterministic, transformation-aware plan snapshot onto the
        record.

        The plan derives the operation from the approved requested
        transformation (never from a hard-coded default), builds the
        operation's argv and verification expectations, and records
        transformation-aware predicted savings. Planning never
        silently changes the requested transformation.

        `user_policy` supplies the planning preferences (for example
        encoding speed). It is a downstream policy input: it never
        alters the approved recommendation or the observed facts; it
        determines the planning/cost semantics recorded on the plan.
        When omitted, the standard default policy applies.
        """

        job = self._get(job_id)

        if job.state not in ("approved", "planned"):

            raise ValueError(
                f"job {job_id} is '{job.state}'; only approved "
                f"jobs can be planned"
            )

        self._assert_fresh_notifying(job)

        transformation = RequestedTransformation.from_dict(
            job.requested_transformation
        ) or self._fallback_plan_transformation(job)

        operation = self._resolve_operation(transformation)

        decision = validate_policy(
            operation=operation,
            source_path=job.source_path,
            destination_path=job.source_path,
        )

        if not decision.allowed:

            self.executions.update_plan(
                job_id,
                plan={},
                policy_decision=decision.to_json(),
                state="approved",
            )

            raise ValueError(
                "policy rejected the planned execution: "
                + "; ".join(decision.reasons)
            )

        source_summary = self._prober(job.source_path)

        if not source_summary:

            raise ValueError(
                "planning failed: source could not be probed "
                "as valid media"
            )

        if operation in (
            OPERATION_CODEC_CONVERSION,
            OPERATION_CODEC_CONVERSION_MKV,
        ):

            source_codec = (
                (source_summary.get("video_codec") or "")
                .lower()
            )

            if source_codec not in HEVC_CONVERSION_SOURCE_CODECS:

                raise ValueError(
                    "operation precondition not met: source "
                    f"video codec '{source_codec}' is not "
                    "H.264; HEVC conversion is not applicable"
                )

        definition = require_operation(operation)

        expected = self._build_verification(
            operation,
            source_summary,
            job,
        )

        argv = build_argv(
            operation=operation,
            source_path=job.source_path,
            output_path="<staged-by-engine>",
            parameters=transformation.parameters,
            source_summary=source_summary,
        )

        effective_policy = (
            user_policy if user_policy is not None else UserPolicy.default()
        )

        proposition = _PLAN_OPERATION_PROPOSITIONS.get(
            operation,
            operation,
        )

        planning = EncodingSpeedPolicy.planning_semantics_for(
            effective_policy,
            proposition,
        )

        plan = build_plan(
            media_id=job.media_id,
            operation=operation,
            source_path=job.source_path,
            source_size_bytes=job.source_size_bytes,
            source_mtime_ns=job.source_mtime_ns,
            source_inode=job.source_inode,
            argv=argv,
            expected=expected,
            planning=planning,
            operation_version=definition.semantic_version,
        )

        from app.execution.operations import (
            OPERATION_REGISTRY_VERSION,
            registry_policy_values,
        )

        plan["registry_version"] = OPERATION_REGISTRY_VERSION

        plan["registry_policy"] = registry_policy_values()

        if self.predictor is not None:

            from app.services.savings_prediction_service import (
                PREDICTION_POLICY_VERSION,
            )

            plan["prediction_policy_version"] = (
                PREDICTION_POLICY_VERSION
            )

        predicted = self._predict(
            transformation,
            source_summary,
            job,
        )

        self.executions.update_plan(
            job_id,
            plan=plan,
            policy_decision=decision.to_json(),
            state="planned",
            predicted=predicted,
        )

        self._mirror_state(
            self._get(job_id),
            new_state="queued",
            expected_current=("accepted",),
            detail="plan frozen; queued for execution",
        )

        self._notify(
            "information",
            "Optimisation queued",
            f"{self._media_name(job.media_id)} · Plan frozen. "
            "Nothing runs until you start it.",
            media_id=job.media_id,
            job_id=job_id,
        )

        return self._get(job_id)

    def _fallback_plan_transformation(self, job):
        """
        A minimal remux transformation when the job predates
        requested-transformation persistence (legacy rows).
        """

        return RequestedTransformation(
            schema_version=1,
            source="recommendation",
            recommendation_id=job.recommendation_id,
            propositions=(
                TransformationProposition(
                    proposition="container_remux",
                    target_state="mp4",
                    parameters={},
                ),
            ),
            operation=OPERATION_REMUX_MP4,
            preserve_resolution=True,
            preserve_hdr=True,
            audio_handling="copy",
            captured_from_run_id=job.analysis_run_id,
            captured_from_observation_id=(
                job.source_observation_id
            ),
            parameters={},
        )

    def _resolve_operation(self, transformation) -> str:
        """
        Resolve and validate the transformation's operation against
        the closed registry. A non-executable or unregistered
        operation is refused (never silently re-targeted).
        """

        operation = transformation.operation

        definition = get_operation(operation)

        if definition is None:

            raise ValueError(
                f"transformation operation '{operation}' is not "
                "registered"
            )

        if operation not in EXECUTABLE_OPERATIONS:

            raise ValueError(
                f"transformation operation '{operation}' is not "
                "executable"
            )

        return operation

    def _build_verification(
        self,
        operation,
        source_summary,
        job,
    ) -> dict:
        """
        The operation-aware verification expectations for a plan.

        Merges the operation definition's verification policy with
        source-derived facts (duration, resolution, HDR, audio) and
        the storage expectation (a storage-saving output must be
        smaller than the source).
        """

        definition = require_operation(operation)

        verification = dict(definition.verification)

        verification["source_duration_s"] = float(
            source_summary.get("duration") or 0.0
        )

        verification["duration_tolerance_s"] = (
            _duration_tolerance(source_summary.get("duration"))
        )

        if operation in (
            OPERATION_CODEC_CONVERSION,
            OPERATION_CODEC_CONVERSION_MKV,
        ):

            verification["expected_width"] = (
                source_summary.get("width")
            )

            verification["expected_height"] = (
                source_summary.get("height")
            )

            if source_summary.get("hdr_format"):

                verification["expected_hdr_format"] = (
                    source_summary.get("hdr_format")
                )

            if source_summary.get("audio_codec"):

                verification["expected_audio_codec"] = (
                    source_summary.get("audio_codec")
                )

            if source_summary.get("audio_channels") is not None:

                verification["expected_audio_channels"] = (
                    source_summary.get("audio_channels")
                )

            verification["smaller_than_source"] = True

            verification["source_size_bytes"] = (
                job.source_size_bytes
            )

        if operation == OPERATION_CODEC_CONVERSION_MKV:

            subtitle_codecs = sorted(
                {
                    (stream.get("codec_name") or "").lower()
                    for stream in (
                        source_summary.get("streams") or []
                    )
                    if (stream.get("codec_type") or "")
                    == "subtitle"
                    and stream.get("codec_name")
                }
            )

            if subtitle_codecs:

                verification["expected_subtitle_codecs"] = (
                    subtitle_codecs
                )

            chapter_count = source_summary.get(
                "chapter_count", 0
            ) or 0

            try:
                chapter_count = int(chapter_count)
            except (TypeError, ValueError):
                chapter_count = 0

            if chapter_count > 0:

                verification["expected_chapter_count"] = (
                    chapter_count
                )

        return verification

    def _predict(self, transformation, source_summary, job) -> dict:
        """
        Predicted savings for the transformation. Uses the versioned
        prediction authority; never the old score*50 shortcut.
        """

        if self.predictor is None:

            from app.services.savings_prediction_service import (
                SavingsPredictionService,
            )

            self.predictor = SavingsPredictionService()

        return self.predictor.predict(
            transformation=transformation,
            source_summary=source_summary,
            source_size_bytes=job.source_size_bytes,
        )

    # -------------------------------------------------
    # execution
    # -------------------------------------------------

    def run(self, job_id):
        """
        Execute one planned/approved job synchronously through the
        full safe sequence. Returns the final job view.
        """

        job = self._get(job_id)

        if job.state == "approved":

            job = self.plan(job_id)

        if job.state != "planned":

            raise ValueError(
                f"job {job_id} is '{job.state}'; only planned "
                f"jobs can run"
            )

        self._assert_fresh_notifying(job)

        plan = job.plan

        # Plan/record integrity: the persisted plan must describe
        # exactly the approved record it belongs to. A divergent plan
        # is never executed.

        plan_fingerprint = (
            plan.get("source_fingerprint", {})
        )

        if (
            plan_fingerprint.get("size_bytes")
            != job.source_size_bytes
            or plan_fingerprint.get("mtime_ns")
            != job.source_mtime_ns
            or plan.get("source_path") != job.source_path
            or plan.get("media_id") != job.media_id
        ):

            raise ValueError(
                f"execution job {job.id} plan does not match "
                f"its approved record; refusing to execute"
            )

        operation = plan.get(
            "operation", OPERATION_REMUX_MP4
        )

        # Disk-space preflight: refuse before staging when the
        # working filesystem cannot safely hold the staged output
        # alongside the retained original.
        try:

            self._preflight_disk_space(job)

        except ValueError as error:

            self._notify(
                "attention",
                "Insufficient disk space",
                f"{self._media_name(job.media_id)} · {error}",
                media_id=job.media_id,
                job_id=job_id,
            )

            raise

        staged = None

        argv = []

        try:

            staged = make_temp_output(
                job.source_path
            )

            argv = build_argv(
                operation=operation,
                source_path=job.source_path,
                output_path=staged,
                parameters=(
                    plan.get("parameters")
                    or job.requested_transformation.get("parameters")
                    or {}
                ),
                # Always probe: the shared builders require the
                # source stream inventory to map streams
                # explicitly. A failed probe refuses truthfully
                # through the existing run error handling below.
                source_summary=(
                    self._prober(job.source_path)
                ),
            )

            self.executions.update_state(
                job_id,
                state="running",
                temp_output_path=staged,
            )

            self._notify(
                "working",
                "Optimisation running",
                f"{self._media_name(job.media_id)} · "
                "Progress/status",
                media_id=job.media_id,
                job_id=job_id,
            )

            self._mirror_state(
                self._get(job_id),
                new_state="executing",
                expected_current=("queued", "accepted"),
                detail="execution started",
            )

            returncode, _, stderr_tail = self._runner(argv)

            if returncode != 0:

                cleanup_path(staged)

                self.executions.update_state(
                    job_id,
                    state="failed_execution",
                    error=(
                        f"ffmpeg exited {returncode}: "
                        f"{stderr_tail.strip()[-500:]}"
                    ),
                )

                self._notify(
                    "error",
                    "Optimisation failed",
                    f"{self._media_name(job.media_id)} · "
                    "FFmpeg execution failed",
                    media_id=job.media_id,
                    job_id=job_id,
                )

                self._mirror_state(
                    self._get(job_id),
                    new_state="failed",
                    expected_current=("executing",),
                    detail="ffmpeg execution failed",
                )

                return self._get(job_id)

            self.executions.update_state(
                job_id, state="verifying"
            )

            ok, reasons, summary, checksum = (
                verify_output(
                    plan=plan,
                    output_path=staged,
                    prober=self._prober,
                )
            )

            if not ok:

                cleanup_path(staged)

                self.executions.update_state(
                    job_id,
                    state="failed_verification",
                    error="; ".join(reasons),
                    output_sha256=checksum,
                    verification={
                        "ok": False,
                        "reasons": list(reasons),
                        "output_sha256": checksum,
                    },
                )

                self._notify(
                    "error",
                    "Optimisation failed",
                    f"{self._media_name(job.media_id)} · "
                    "Output verification failed",
                    media_id=job.media_id,
                    job_id=job_id,
                )

                self._mirror_state(
                    self._get(job_id),
                    new_state="failed",
                    expected_current=("executing",),
                    detail=(
                        "output verification failed: "
                        + "; ".join(reasons)
                    ),
                )

                return self._get(job_id)

            # Critical safety case: the source may have changed while
            # the encode ran. Revalidate the source immediately before
            # the swap. A changed source can never be replaced.
            try:

                self._assert_source_unchanged_before_swap(job)

            except SourceDriftError as error:

                cleanup_path(staged)

                self.executions.update_state(
                    job_id,
                    state="failed_execution",
                    error=str(error),
                )

                self._notify(
                    "error",
                    "Optimisation failed",
                    f"{self._media_name(job.media_id)} · "
                    "Source drift during execution",
                    media_id=job.media_id,
                    job_id=job_id,
                )

                self._mirror_state(
                    self._get(job_id),
                    new_state="failed",
                    expected_current=("executing",),
                    detail=str(error),
                )

                return self._get(job_id)

            self.executions.update_state(
                job_id,
                state="replacing",
                output_sha256=checksum,
                backup_path=(
                    f"{job.source_path}"
                    f".namoa-original-{job_id}"
                ),
                verification={
                    "ok": True,
                    "reasons": [],
                    "output_sha256": checksum,
                },
            )

            backup_path = (
                f"{job.source_path}"
                f".namoa-original-{job_id}"
            )

            try:

                perform_replacement(
                    source_path=job.source_path,
                    staged_output_path=staged,
                    backup_path=backup_path,
                )

            except ReplacementFailed as failure:

                if failure.restored:

                    self.executions.update_state(
                        job_id,
                        state="failed_replacement",
                        error=str(failure),
                        backup_path=backup_path,
                    )

                    self._notify(
                        "error",
                        "Optimisation failed",
                        f"{self._media_name(job.media_id)} · "
                        "Replacement failed; original restored",
                        media_id=job.media_id,
                        job_id=job_id,
                    )

                    self._mirror_state(
                        self._get(job_id),
                        new_state="failed",
                        expected_current=("executing",),
                        detail=(
                            "replacement failed; original "
                            "restored"
                        ),
                    )

                else:

                    self.executions.update_state(
                        job_id,
                        state="interrupted",
                        error=(
                            f"{failure}; original preserved "
                            f"at {backup_path}; recovery "
                            f"required"
                        ),
                        backup_path=backup_path,
                    )

                    self._notify(
                        "attention",
                        "Optimisation interrupted",
                        f"{self._media_name(job.media_id)} · "
                        "Recovery required",
                        media_id=job.media_id,
                        job_id=job_id,
                    )

                    self._mirror_state(
                        self._get(job_id),
                        new_state="failed",
                        expected_current=("executing",),
                        detail=(
                            "interrupted during replacement; "
                            "recovery required"
                        ),
                    )

                return self._get(job_id)

            result_observation_id = (
                self._record_result_observation(
                    job.source_path, summary
                )
            )

            measured = self._build_measured(
                job,
                result_observation_id,
            )

            self.executions.update_state(
                job_id,
                state="succeeded",
                result_observation_id=result_observation_id,
                measured=measured,
            )

            self._notify(
                "success",
                "Optimisation complete",
                f"{self._media_name(job.media_id)} · "
                f"{self._measured_saved_text(self._get(job_id), result_observation_id)}",
                media_id=job.media_id,
                job_id=job_id,
            )

            self._mirror_state(
                self._get(job_id),
                new_state="completed",
                expected_current=("executing",),
                detail="optimisation completed and verified",
            )

            return self._get(job_id)

        except Exception as error:

            # Unexpected exception mid-sequence: never claim
            # success; classify honestly so recovery inspects
            # reality instead of trusting memory.

            cleanup_path(staged)

            current = self._get(job_id)

            if current.state == "replacing":

                # The swap may already have completed; keep the
                # replacing state so recovery can classify via the
                # recorded checksums instead of guessing.

                self.executions.update_state(
                    job_id,
                    state="replacing",
                    error=(
                        f"interrupted during/after "
                        f"replacement: {error}"
                    ),
                    temp_output_path=None,
                )

            else:

                self.executions.update_state(
                    job_id,
                    state="interrupted",
                    error=f"unexpected: {error}",
                )

                self._notify(
                    "attention",
                    "Optimisation interrupted",
                    f"{self._media_name(job.media_id)} · "
                    f"Unexpected interruption",
                    media_id=job.media_id,
                    job_id=job_id,
                )

                self._mirror_state(
                    self._get(job_id),
                    new_state="failed",
                    expected_current=("executing",),
                    detail=f"interrupted: {error}",
                )

            return self._get(job_id)

    # -------------------------------------------------
    # deletion lifecycle
    # -------------------------------------------------

    def delete_original(self, job_id):
        """
        Explicit, separate file-lifecycle action: delete the preserved
        original ONLY after verified successful replacement.

        The optimisation remains successful regardless of deletion
        outcome. If deletion fails, the original remains intact and is
        recorded as deletion_failed; the user is notified. Rollback is
        never offered after the original has been deleted.
        """

        job = self._get(job_id)

        if job.state != "succeeded":

            raise ValueError(
                f"only succeeded executions can delete the "
                f"original (job {job_id} is '{job.state}')"
            )

        self.executions.update_state(
            job_id,
            state="deleting_original",
            deletion_state="deleting_original",
        )

        reason = self._deletion_precondition_reason(job)

        if reason:

            self._record_deletion_failure(job_id, reason)

            return self._get(job_id)

        backup = job.backup_path

        try:

            os.unlink(backup)

        except OSError as error:

            self._record_deletion_failure(
                job_id,
                f"deletion failed: {error}",
            )

            return self._get(job_id)

        self.executions.update_state(
            job_id,
            state="original_deleted",
            deletion_state="original_deleted",
            original_deleted_at=_now_iso(),
        )

        # Lineage-level confirmed-deletion event (Phase 10): the
        # verified destruction above is recorded against the
        # affected lineage's history, distinct from observed
        # disappearance (which stays status='missing' and records
        # nothing here). Append-only; the lineage row itself is
        # untouched because it continues with the verified result.
        # Failed deletions return earlier and record nothing here.
        self.media_repository.record_confirmed_deletion(
            media_id=job.media_id,
            execution_job_id=job_id,
            source_observation_id=job.source_observation_id,
            deleted_path=backup,
            detail=(
                "preserved original removed after successful "
                "optimisation"
            ),
        )

        self._notify(
            "neutral",
            "Original deleted",
            f"{self._media_name(job.media_id)} · Preserved "
            "original removed after successful optimisation",
            media_id=job.media_id,
            job_id=job_id,
        )

        return self._get(job_id)

    def _deletion_precondition_reason(self, job):
        """
        A human-readable reason the preserved original cannot be
        deleted, or None when deletion is safe. Deletion is only safe
        when the result is the recorded output, the source observation
        link exists, and the preserved original still matches the
        approved source bytes.
        """

        if job.result_observation_id is None:

            return (
                "no recorded result observation; refusing "
                "deletion"
            )

        if not job.output_sha256:

            return (
                "no recorded output checksum; refusing "
                "deletion"
            )

        if not os.path.exists(job.source_path):

            return "result file is missing; refusing deletion"

        live_sha256 = sha256_of(job.source_path)

        if live_sha256 != job.output_sha256:

            return (
                "live result no longer matches this "
                "execution's recorded output; refusing "
                "deletion"
            )

        backup = job.backup_path

        if not backup or not os.path.exists(backup):

            return (
                "preserved original is missing; nothing to "
                "delete"
            )

        if job.source_sha256:

            backup_sha256 = sha256_of(backup)

            if backup_sha256 != job.source_sha256:

                return (
                    "preserved original no longer matches the "
                    "approved source bytes; refusing deletion"
                )

        return None

    def _record_deletion_failure(self, job_id, reason):

        self.executions.update_state(
            job_id,
            state="deletion_failed",
            deletion_state="deletion_failed",
            error=reason,
        )

        job = self._get(job_id)

        self._notify(
            "attention",
            "Deletion failed",
            f"{self._media_name(job.media_id)} · {reason}",
            media_id=job.media_id,
            job_id=job_id,
        )

    # -------------------------------------------------
    # queue worker
    # -------------------------------------------------

    def run_queue(self, *, limit=None):
        """
        Process the execution queue serially.

        - eligible unfinished jobs are recovered FIRST (application
          restart must not silently lose execution state and must not
          duplicate an execution)
        - then each approved/planned job is executed once, in id
          order, one at a time
        - a terminal failure of one job never falsely marks unrelated
          jobs successful; later approved jobs continue

        Returns a summary of what happened.
        """

        summary = {
            "recovered": [],
            "run": [],
            "failed": [],
            "skipped": [],
        }

        for job in self.executions.list_recoverable():

            try:

                self.recover(job.id)

                summary["recovered"].append(job.id)

            except ValueError as error:

                summary["skipped"].append(job.id)

        for job in self.executions.list_queueable():

            if limit is not None and (
                len(summary["run"]) + len(summary["failed"])
                >= int(limit)
            ):

                break

            try:

                result = self.run(job.id)

            except ValueError as error:

                summary["failed"].append(job.id)

                continue

            if result.state == "succeeded":

                summary["run"].append(job.id)

            else:

                summary["failed"].append(job.id)

        return summary

    # -------------------------------------------------
    # rollback / recovery
    # -------------------------------------------------

    def rollback(self, job_id):
        """
        Revert a SUCCEEDED job: restore the preserved original bytes
        atomically and record the restoration as its own filesystem
        observation. History is never rewritten; both eras remain
        observed facts.

        Rollback is never offered after the original has been
        explicitly deleted (original_deleted is terminal).
        """

        job = self._get(job_id)

        if job.state != "succeeded":

            raise ValueError(
                f"only succeeded executions can be rolled back "
                f"(job {job_id} is '{job.state}')"
            )

        backup = job.backup_path

        if not backup or not os.path.exists(backup):

            raise ValueError(
                f"backup for job {job_id} is missing; rollback "
                f"impossible"
            )

        # Destructive-operation integrity guard: rollback overwrites
        # the current file, so first prove that what exists NOW is
        # still the result of THIS execution. Drift is preserved and
        # reported, never silently overwritten.

        if not job.output_sha256:

            raise ValueError(
                f"job {job_id} has no recorded output "
                f"checksum; refusing destructive rollback"
            )

        live_sha256 = sha256_of(job.source_path)

        if live_sha256 != job.output_sha256:

            raise ValueError(
                f"refusing rollback for job {job_id}: the "
                f"current content at {job.source_path} does not "
                f"match this execution's recorded result "
                f"(sha mismatch). The filesystem has drifted "
                f"after execution; nothing was modified and the "
                f"backup at {backup} is preserved for manual "
                f"investigation."
            )

        summary = self._prober(backup)

        restore_original(
            source_path=job.source_path,
            backup_path=backup,
        )

        result_observation_id = (
            self._record_result_observation(
                job.source_path, summary
            )
        )

        self.executions.update_state(
            job_id,
            state="rolled_back",
            error=None,
            result_observation_id=result_observation_id,
        )

        self._notify(
            "information",
            "Optimisation rolled back",
            f"{self._media_name(job.media_id)} · "
            "Original restored",
            media_id=job.media_id,
            job_id=job_id,
        )

        self._mirror_state(
            self._get(job_id),
            new_state="failed",
            expected_current=("completed",),
            detail=(
                "succeeded execution rolled back to "
                "original bytes"
            ),
        )

        return self._get(job_id)

    def recover(self, job_id):
        """
        Resolve one interrupted/active job by inspecting the REAL
        filesystem instead of trusting the record. The recorded
        checksums classify what actually happened:

            live source == output_sha256
                replacement had COMPLETED; only the final
                persistence write was lost -> finalise honestly

            live source == source_sha256
                original still in place (replacement never
                started or already restored) -> close safely

            backup present, source absent
                swap interrupted mid-sequence -> restore original

            anything else
                filesystem drift: touch nothing, report it
        """

        job = self._get(job_id)

        if job.state not in (
            "interrupted", "running", "verifying", "replacing",
            "deleting_original",
        ):

            raise ValueError(
                f"job {job_id} is '{job.state}'; nothing to "
                f"recover"
            )

        notes = []

        temp_path = job.temp_output_path

        if temp_path:

            cleanup_path(temp_path)

            notes.append("temporary output removed")

        live_sha256 = None

        if os.path.exists(job.source_path):

            live_sha256 = sha256_of(job.source_path)

        # C: replacement completed but persistence did not reach its
        # final state. Only the 'replacing' state can legitimately
        # finalise to succeeded.

        if (
            live_sha256 is not None
            and job.output_sha256
            and live_sha256 == job.output_sha256
            and job.state == "replacing"
        ):

            notes.append(
                "output matches this execution's recorded "
                "checksum: replacement had completed"
            )

            result_observation_id = (
                job.result_observation_id
            )

            if result_observation_id is None:

                # The swap completed; the observation may already
                # have been committed before the crash. Reuse the
                # matching existing observation instead of recording
                # a duplicate.

                existing = find_existing_observation_id(
                    self.media_repository,
                    media_id=job.media_id,
                    path=job.source_path,
                )

                if existing is not None:

                    result_observation_id = existing

                    notes.append(
                        "existing result observation "
                        "reused"
                    )

                else:

                    summary = self._prober(job.source_path)

                    result_observation_id = (
                        self._record_result_observation(
                            job.source_path, summary
                        )
                    )

                    notes.append(
                        "result observation recorded now"
                    )

            else:

                notes.append(
                    "result observation already recorded"
                )

            measured = self._build_measured(
                self._get(job_id),
                result_observation_id,
            )

            self.executions.update_state(
                job_id,
                state="succeeded",
                result_observation_id=result_observation_id,
                measured=measured,
                error="; ".join(notes),
            )

            self._mirror_state(
                self._get(job_id),
                new_state="completed",
                expected_current=("executing", "failed"),
                detail="recovery finalised execution as "
                       "succeeded: " + "; ".join(notes),
            )

            return self._get(job_id)

        # A/B/E: source is still the approved original (or drifted).

        if live_sha256 is not None:

            if (
                job.source_sha256
                and live_sha256 == job.source_sha256
            ):

                notes.append(
                    "original still in place; no replacement "
                    "occurred"
                )

            else:

                notes.append(
                    "DRIFT: live content matches neither this "
                    "execution's result nor its approved "
                    "original; filesystem left untouched for "
                    "manual investigation"
                )

            self.executions.update_state(
                job_id,
                state="recovered",
                error="; ".join(notes),
            )

            self._mirror_state(
                self._get(job_id),
                new_state="failed",
                expected_current=(
                    "queued", "executing", "failed",
                ),
                detail="recovered: " + "; ".join(notes),
            )

            return self._get(job_id)

        # B: source missing mid-sequence but the preserved original
        # is available.

        if job.backup_path and os.path.exists(
            job.backup_path
        ):

            restore_original(
                source_path=job.source_path,
                backup_path=job.backup_path,
            )

            restored_sha = sha256_of(job.source_path)

            if (
                job.source_sha256
                and restored_sha != job.source_sha256
            ):

                notes.append(
                    "WARNING: restored bytes do not match the "
                    "approved original checksum"
                )

            notes.append(
                "original restored from recorded backup"
            )

            self.executions.update_state(
                job_id,
                state="recovered",
                error="; ".join(notes),
            )

            self._mirror_state(
                self._get(job_id),
                new_state="failed",
                expected_current=(
                    "queued", "executing", "failed",
                ),
                detail="recovered: " + "; ".join(notes),
            )

            return self._get(job_id)

        notes.append(
            "source and backup both absent; manual "
            "investigation required"
        )

        self.executions.update_state(
            job_id,
            state="recovered",
            error="; ".join(notes),
        )

        self._mirror_state(
            self._get(job_id),
            new_state="failed",
            expected_current=(
                "queued", "executing", "failed",
            ),
            detail="recovered: " + "; ".join(notes),
        )

        return self._get(job_id)

    # -------------------------------------------------
    # reads
    # -------------------------------------------------

    def get(self, job_id):

        return self._get(job_id)

    def list_jobs(self, limit=100):

        return self.executions.list(limit)

    def list_jobs_by_media(self, media_id):
        """
        Durable execution/outcome history for one lineage, newest
        first. Persistence read via the execution repository; no
        state is reinterpreted here.
        """

        return self.executions.list_by_media(media_id)

    # -------------------------------------------------
    # internals
    # -------------------------------------------------

    def _current_candidate(self, media_id):

        for item in (
            self.recommendations_service
            .get_current_queue()
        ):

            if item.media_id == media_id:

                return item

        raise ValueError(
            f"media {media_id} has no current-valid "
            f"optimisation recommendation; nothing to approve. "
            "The source may have changed, may be missing, or may "
            "no longer be an opportunity. Rescan and analyse the "
            "current source before approval."
        )

    def _get(self, job_id):

        job = self.executions.get(job_id)

        if job is None:

            raise ValueError(
                f"execution job {job_id} not found"
            )

        return job

    def _assert_fresh_notifying(self, job):
        """
        Freshness check that also notifies the user when the source
        became stale (a required failure notification).
        """

        try:

            self._assert_fresh(job)

        except ValueError as error:

            self._notify(
                "attention",
                "Source became stale",
                f"{self._media_name(job.media_id)} · {error}",
                media_id=job.media_id,
                job_id=job.id,
            )

            raise

    def _assert_fresh(self, job):
        """
        Stale-plan protection: the live file must still BE the exact
        file state that was approved. Compares the live stat to the
        approved snapshot (size, mtime, inode) and, where a sha256
        was captured at approval, the live content. It does NOT
        reimplement the currentness authority (which remains
        responsible for analysis validity).
        """

        if not os.path.exists(job.source_path):

            raise ValueError(
                f"source is gone: {job.source_path}"
            )

        stat = os.stat(job.source_path)

        drifted = (
            stat.st_size != job.source_size_bytes
            or stat.st_mtime_ns != job.source_mtime_ns
            or (
                job.source_inode is not None
                and stat.st_ino != job.source_inode
            )
        )

        if drifted:

            raise ValueError(
                f"execution job {job.id} is STALE: the source "
                f"changed since approval "
                f"(approved "
                f"{job.source_size_bytes}/"
                f"{job.source_mtime_ns}/"
                f"{job.source_inode}, "
                f"now {stat.st_size}/"
                f"{stat.st_mtime_ns}/"
                f"{stat.st_ino}); "
                f"approve the new state again"
            )

        if job.source_sha256:

            live_sha256 = sha256_of(job.source_path)

            if live_sha256 != job.source_sha256:

                raise ValueError(
                    f"execution job {job.id} is STALE: the "
                    f"source content (sha256) changed since "
                    f"approval; approve the new state again"
                )

    def _assert_source_unchanged_before_swap(self, job):
        """
        Critical safety case: revalidate the source immediately
        before the replacement swap. A long encode may have run for
        a long time; the source may have changed while it ran.

        The strongest available identity evidence is revalidated:
        size, mtime, inode, and SHA256 (when captured at approval).
        A source whose contents changed while retaining the same
        size, mtime and inode is therefore still detected.

        A changed source is NEVER replaced, never deleted, and never
        reported as success. Raises SourceDriftError.
        """

        if not os.path.exists(job.source_path):

            raise SourceDriftError(
                "source_drift_during_encode: source disappeared "
                "during encoding; staged output cleaned, source "
                "untouched"
            )

        stat = os.stat(job.source_path)

        drifted = (
            stat.st_size != job.source_size_bytes
            or stat.st_mtime_ns != job.source_mtime_ns
            or (
                job.source_inode is not None
                and stat.st_ino != job.source_inode
            )
        )

        if drifted:

            raise SourceDriftError(
                "source_drift_during_encode: source changed "
                "during encoding "
                f"(approved "
                f"{job.source_size_bytes}/"
                f"{job.source_mtime_ns}/"
                f"{job.source_inode}, "
                f"now {stat.st_size}/"
                f"{stat.st_mtime_ns}/"
                f"{stat.st_ino}); refusing to replace"
            )

        if job.source_sha256:

            live_sha256 = sha256_of(job.source_path)

            if live_sha256 != job.source_sha256:

                raise SourceDriftError(
                    "source_drift_during_encode: source content "
                    "(sha256) changed during encoding while its "
                    "size, mtime and inode were retained; "
                    "refusing to replace"
                )

    def _preflight_disk_space(self, job):
        """
        Refuse execution when the working filesystem cannot safely
        hold the staged output alongside the retained original.

        The staged output is never assumed smaller merely because the
        operation is expected to save space.
        """

        directory = os.path.dirname(
            os.path.abspath(job.source_path)
        ) or "."

        if not os.path.exists(directory):

            raise ValueError(
                f"working directory does not exist: {directory}"
            )

        usage = shutil.disk_usage(directory)

        required = int(
            (job.source_size_bytes or 0)
            + STAGING_HEADROOM_BYTES
        )

        if usage.free < required:

            raise ValueError(
                "insufficient disk space: "
                f"{usage.free} bytes free, {required} bytes "
                f"required for safe staged output; refusing "
                "to execute"
            )

    def _build_measured(
        self,
        job,
        result_observation_id,
    ) -> dict | None:
        """
        Measured savings derived from the actual source and result
        observations. None when the result observation cannot be
        resolved.
        """

        observation = self.media_repository.get_observation_by_id(
            result_observation_id
        )

        if (
            observation is None
            or observation.size_bytes is None
            or job.source_size_bytes is None
        ):

            return None

        source_size = int(job.source_size_bytes)

        result_size = int(observation.size_bytes)

        delta = source_size - result_size

        percent = (
            (delta / source_size * 100.0)
            if source_size > 0
            else 0.0
        )

        return {
            "measured_saved_bytes": delta,
            "measured_percent": round(percent, 2),
            "source_size_bytes": source_size,
            "result_size_bytes": result_size,
            "source_observation_id": job.source_observation_id,
            "result_observation_id": result_observation_id,
            "measured_at": _now_iso(),
        }

    def _record_result_observation(self, path, summary):

        _, _, observation_id = (
            record_execution_observation(
                self.media_repository,
                path=path,
                summary=summary,
            )
        )

        return observation_id


def _duration_tolerance(duration):

    value = float(duration or 0.0)

    return max(2.0, value * 0.1)