"""Bulk optimisation coordination (Phase 12).

Coordination ONLY for advanced and bulk optimisation workflows.
This service owns no safety logic of its own:

- it never approves, plans, validates, verifies, executes, or
  recovers anything itself
- it never touches the filesystem, FFmpeg, repositories, or
  intelligence layers
- every per-file decision delegates to the single-file boundaries
  on ExecutionService (approve / approve_advanced / plan / run /
  recover), which retain the authoritative per-file identity,
  source observation, approval, validation, provenance,
  verification, measured-result, and recovery semantics

Bulk processing is coordination, not blanket permission: each file
keeps its own identity, source observation, recommendation and
approval semantics, safety validation, execution provenance,
verification, measured result, and recovery state. A failure
affecting one file never erases, invalidates, or obscures the
state and provenance of other files, and bulk completion is never
treated as proof that every file succeeded.

No distributed execution is introduced: files are processed
serially, one at a time, through the existing execution boundary.
"""


class BulkOptimisationService:
    """
    Application-facing bulk coordination over ExecutionService.
    """

    def __init__(self, *, execution_service):

        self.executions = execution_service

    # -------------------------------------------------
    # bulk approval (recommendation path)
    # -------------------------------------------------

    def approve_many(
        self,
        media_ids,
        *,
        approved_by="human",
        delete_original_requested=False,
    ):
        """
        Coordinate approval for several lineages through the
        single approval boundary per file. Returns the
        per-file results verbatim.
        """

        return self.executions.approve_selected(
            media_ids,
            approved_by=approved_by,
            delete_original_requested=(
                delete_original_requested
            ),
        )

    # -------------------------------------------------
    # bulk approval (advanced path)
    # -------------------------------------------------

    def approve_many_advanced(
        self,
        requests,
        *,
        approved_by="human",
        delete_original_requested=False,
    ):
        """
        Coordinate advanced approval for several lineages through
        the single advanced approval boundary per file. Each
        request carries its own operation and parameters, each
        validated independently against the closed operation
        registry. Returns the per-file results verbatim.
        """

        return self.executions.approve_selected_advanced(
            requests,
            approved_by=approved_by,
            delete_original_requested=(
                delete_original_requested
            ),
        )

    # -------------------------------------------------
    # bulk planning
    # -------------------------------------------------

    def plan_many(self, job_ids, user_policy=None):
        """
        Coordinate planning for several jobs through the single
        planning boundary per job. Returns the per-job results
        verbatim.
        """

        return self.executions.plan_selected(
            job_ids,
            user_policy=user_policy,
        )

    # -------------------------------------------------
    # bulk execution
    # -------------------------------------------------

    def run_many(self, job_ids):
        """
        Coordinate serial execution for several jobs through the
        single execution boundary per job. Returns the per-job
        results verbatim.
        """

        return self.executions.run_selected(job_ids)

    def run_queue(self, *, limit=None):
        """
        Process the durable execution queue through the existing
        queue worker (recovery first, serial, one job at a time).
        Returns the worker summary verbatim.
        """

        return self.executions.run_queue(limit=limit)

    # -------------------------------------------------
    # bulk outcome description
    # -------------------------------------------------

    def describe_results(self, job_ids):
        """
        The independently explainable per-file outcome for each
        requested job, read from the durable job records only.

        Each entry preserves the per-file distinction between
        media identity, source observation, approved operation,
        execution, resulting observation, verification, and
        measured result. A file whose job cannot be resolved is
        reported as unresolved, never guessed.

        The bulk verdict is 'succeeded' only when every resolved
        file succeeded; otherwise it is 'incomplete'. Bulk
        completion is never treated as proof that every file
        succeeded.
        """

        files = []

        for raw_id in job_ids or []:

            try:

                job_id = int(raw_id)

            except (TypeError, ValueError):

                files.append(
                    {
                        "job_id": raw_id,
                        "resolved": False,
                        "reason": "invalid job id",
                    }
                )

                continue

            try:

                job = self.executions.get(job_id)

            except ValueError as error:

                files.append(
                    {
                        "job_id": job_id,
                        "resolved": False,
                        "reason": str(error),
                    }
                )

                continue

            transformation = (
                job.requested_transformation or {}
            )

            files.append(
                {
                    "job_id": job.id,
                    "resolved": True,
                    "media_id": job.media_id,
                    "state": job.state,
                    "succeeded": job.state == "succeeded",
                    "source_path": job.source_path,
                    "source_observation_id": (
                        job.source_observation_id
                    ),
                    "analysis_run_id": job.analysis_run_id,
                    "recommendation_id": (
                        job.recommendation_id
                    ),
                    "approved_operation": (
                        transformation.get("operation")
                    ),
                    "transformation_source": (
                        transformation.get("source")
                    ),
                    "result_observation_id": (
                        job.result_observation_id
                    ),
                    "verification": dict(
                        job.verification or {}
                    ),
                    "measured": dict(job.measured or {}),
                    "predicted": dict(job.predicted or {}),
                    "error": job.error,
                }
            )

        resolved = [entry for entry in files if entry.get("resolved")]

        verdict = (
            "succeeded"
            if files
            and resolved
            and len(resolved) == len(files)
            and all(entry["succeeded"] for entry in resolved)
            else "incomplete"
        )

        return {
            "verdict": verdict,
            "succeeded_count": sum(
                1 for entry in resolved if entry["succeeded"]
            ),
            "total_count": len(files),
            "files": files,
        }
