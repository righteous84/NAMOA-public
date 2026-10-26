"""
Page/API data handlers for the NAMOA GUI.

Each handler is a thin read assembly over the wired application
services. Handlers:

- never touch persistence, repositories, domain services or models
  directly (they receive only the application Services container)
- never implement validity, ranking, provenance or analysis logic
- raise NotFound to signal a missing item, which the server turns
  into a 404 (HTML or JSON)

The same data dicts feed both the HTML pages and the JSON API.
"""

import traceback

from app.application.queue_manifest import (
    build_queue_manifest,
)

from app.application.preview_service import (
    PreviewError,
)

from app.web.serializers import (
    candidate_to_dict,
    comparison_to_dict,
    confidence_distribution_to_dict,
    explanation_to_dict,
    execution_state_label,
    format_bytes,
    format_confidence,
    format_percent,
    library_health_to_dict,
    library_lineage_status_to_dict,
    library_statistics_to_dict,
    library_summary_to_dict,
    lineage_status_to_dict,
    measured_savings_to_dict,
    notification_to_dict,
    now_timestamp,
    observation_history_to_dict,
    observation_to_dict,
    organisation_decision_run_to_dict,
    organisation_events_to_dict,
    organisation_execution_continuity_to_dict,
    organisation_execution_state_label,
    organisation_execution_to_dict,
    organisation_proposal_to_dict,
    predicted_savings_to_dict,
    prioritised_recommendation_to_dict,
    provenance_to_dict,
    recommendation_events_to_dict,
    recommendation_record_to_dict,
    recommendation_set_to_dict,
    run_summary_to_dict,
    run_to_dict,
    savings_distribution_to_dict,
    savings_projection_to_dict,
    scan_meta_to_dict,
    scan_status_to_dict,
    standing_decision_to_dict,
    storage_consumption_to_dict,
    storage_summary_to_dict,
    transformation_to_dict,
)


class NotFound(Exception):
    """Raised when a requested item does not exist."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class UserError(ValueError):
    """User-facing form error carrying its display title."""

    def __init__(self, message, *, title="Invalid selection"):
        super().__init__(message)
        self.message = message
        self.title = title


def _not_found_from(message):
    return NotFound(message)


def _int_or_404(raw_value, what):
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise NotFound(f"Invalid {what}: {raw_value!r}")


# ---------------------------------------------------------
# Dashboard
# ---------------------------------------------------------


def _newest_job_by_media(jobs):
    """
    Newest execution job per lineage (presentation grouping only;
    the job lifecycle itself is untouched).
    """

    newest = {}

    for job in jobs or []:
        media_id = getattr(job, "media_id", None)

        if media_id is None:
            continue

        current = newest.get(media_id)

        if current is None or job.id > current.id:
            newest[media_id] = job

    return newest


def _job_visibility(job):
    """
    Cross-path visibility for one lineage's newest job: queued or
    in-progress work is shown as requested/running (never as
    completed), terminal success as completed. Uses the existing
    lifecycle state sets; the job lifecycle itself is untouched.
    Returns None when there is nothing informative to show.
    """

    from app.models.execution import (
        ACTIVE_STATES,
    )

    if job is None:
        return None

    state = job.state

    if (
        state in ACTIVE_STATES
        or state == "interrupted"
        or state == "succeeded"
    ):
        return execution_to_view(job)

    return None


def dashboard_data(services):
    summary = services.library_status_service.get_library_summary()

    storage = services.library_status_service.get_storage_summary()

    queue = services.recommendation_service.get_current_queue()

    prioritised = (
        services
        .recommendation_service
        .get_prioritised_recommendations()
    )

    runs = services.library_status_service.get_analysis_runs()

    scan_meta = services.library_status_service.get_scan_meta()

    jobs = services.execution_service.list_jobs()

    queue_counts = _execution_queue_counts(jobs)

    newest_jobs = _newest_job_by_media(jobs)

    cards = []

    for item in prioritised[:8]:
        card = prioritised_recommendation_to_dict(item)

        job = newest_jobs.get(item.candidate.media_id)

        card["active_job"] = _job_visibility(job)

        cards.append(card)

    return {
        "summary": library_summary_to_dict(summary),
        "storage": storage_summary_to_dict(storage),
        "queue": [candidate_to_dict(item) for item in queue[:8]],
        # Phase 3 actionable recommendation cards (the same
        # authoritative current-valid queue, prioritised, with the
        # rationale/narrative and change summary for the card
        # presentation). No second recommendation system.
        "cards": cards,
        "recent_runs": [
            run_summary_to_dict(item) for item in runs[:5]
        ],
        "scan_meta": scan_meta_to_dict(scan_meta),
        "queue_counts": queue_counts,
        "refreshed_at": now_timestamp(),
    }


def _execution_queue_counts(jobs):
    """
    Authoritative execution-queue counts (presentation grouping of the
    recorded job states; the lifecycle itself is untouched).
    """

    counts = {
        "approved": 0,
        "running": 0,
        "completed": 0,
        "attention": 0,
        "total": len(jobs),
    }

    for job in jobs:

        if job.state in ("approved", "planned"):
            counts["approved"] += 1
        elif job.state in ("running", "verifying", "replacing"):
            counts["running"] += 1
        elif job.state in (
            "succeeded",
            "rolled_back",
            "original_deleted",
        ):
            counts["completed"] += 1
        elif job.state in (
            "failed_execution",
            "failed_verification",
            "failed_replacement",
            "interrupted",
            "recovered",
            "deleting_original",
            "deletion_failed",
        ):
            counts["attention"] += 1

    return counts


# ---------------------------------------------------------
# Media inventory + detail
# ---------------------------------------------------------


def media_index_data(services):
    statuses = services.library_status_service.get_lineage_statuses()

    return {
        "entries": [
            lineage_status_to_dict(entry)
            for entry in statuses
        ],
        "refreshed_at": now_timestamp(),
    }


def media_detail_data(services, media_id):
    try:
        entry = (
            services
            .library_status_service
            .get_lineage_status(media_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    try:
        history = services.media_service.get_observation_history(
            media_id
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return {
        "entry": lineage_status_to_dict(entry),
        "history": observation_history_to_dict(history),
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Analysis status view
# ---------------------------------------------------------


def analysis_status_data(services):
    statuses = services.library_status_service.get_lineage_statuses()

    return {
        "entries": [
            lineage_status_to_dict(entry)
            for entry in statuses
        ],
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Scan view
# ---------------------------------------------------------


def scan_page_data(services):
    return {
        "meta": scan_meta_to_dict(
            services.library_status_service.get_scan_meta()
        ),
        "refreshed_at": now_timestamp(),
    }


def run_scan(services, path, database_path=None, scan_id=None):
    """
    Run a scan through ScanService.

    The scanner/pipeline are synchronous within the scan; the GUI runs
    this in a background worker (GUI/UX Phase 5) so the request does
    not block. Returns the honest scan report dict.

    `scan_id` may be supplied by a caller that already opened the
    durable Scan identity.
    """

    if not path or not path.strip():
        raise ValueError("A scan path is required")

    report = services.scan_service.scan_with_report(
        path.strip(),
        database_path=database_path,
        scan_id=scan_id,
    )

    return {
        "path": report["path"],
        "files_discovered": report["files_discovered"],
        "persisted_count": report["persisted_count"],
        "scan_id": report.get("scan_id"),
        "refreshed_at": now_timestamp(),
    }


def scan_status_data(services, scan_id):
    """
    The durable scan's current state (GUI/UX Phase 5): status, phase
    (discovering/analysing/completed/failed), incremental counts,
    honest percent (analysis phase only) and approximate ETA.
    """

    scan_id = _int_or_404(scan_id, "scan id")

    return scan_status_to_dict(
        services.scan_service.get_scan_status(scan_id)
    )


def filesystem_browse_data(
    services, path=None, include_files=False
):
    """
    Read-only directory listing for the folder browsers
    (GUI/UX Phase 5). Never starts a scan; server-side
    resolution only; cross-platform roots. With
    include_files, video/media files inside the
    directory are listed too, so file pickers such as
    Quick Find can offer a real file choice.
    """

    if include_files:
        return (
            services.filesystem_service
            .list_directory_contents(path, include_files=True)
        )

    return services.filesystem_service.list_directories(path)


# ---------------------------------------------------------
# Phase 4 notifications
# ---------------------------------------------------------


def notifications_data(services):
    """
    The active (undismissed) notifications, newest first.
    """

    return {
        "notifications": [
            notification_to_dict(item)
            for item in (
                services.notification_service.list_active()
            )
        ],
        "refreshed_at": now_timestamp(),
    }


def notification_dismiss_data(services, notification_id):
    """
    Dismiss one notification. Returns the dismissed id.
    """

    notification_id = _int_or_404(
        notification_id,
        "notification id",
    )

    services.notification_service.dismiss(notification_id)

    return {
        "dismissed": notification_id,
        "refreshed_at": now_timestamp(),
    }


def notification_dismiss_all_data(services):
    """
    Dismiss every active notification. Returns the count dismissed.
    """

    count = services.notification_service.dismiss_all()

    return {
        "dismissed": count,
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Opportunities
# ---------------------------------------------------------

def _standing_decision_input(body):
    if not isinstance(body, dict):
        raise ValueError("A standing decision request is required")

    raw_proposition = (body.get("proposition") or [None])[0]

    proposition = str(raw_proposition or "").strip()

    if not proposition:
        raise ValueError("A proposition is required")

    raw_actor = (body.get("actor") or [None])[0]

    actor = (
        str(raw_actor).strip()
        if raw_actor and str(raw_actor).strip()
        else "human"
    )

    raw_reason = (body.get("reason") or [None])[0]

    reason = (
        str(raw_reason).strip()
        if raw_reason and str(raw_reason).strip()
        else None
    )

    return proposition, actor, reason


def standing_decision_refuse_data(
    services,
    media_id,
    body,
):
    media_id = _int_or_404(
        media_id,
        "media id",
    )

    proposition, actor, reason = _standing_decision_input(body)

    decision = services.standing_decision_service.refuse(
        media_id,
        proposition,
        actor=actor,
        reason=reason,
    )

    return {
        "standing_decision": standing_decision_to_dict(
            decision
        ),
        "refreshed_at": now_timestamp(),
    }


def standing_decision_revoke_data(
    services,
    media_id,
    body,
):
    media_id = _int_or_404(
        media_id,
        "media id",
    )

    proposition, actor, reason = _standing_decision_input(body)

    decision = services.standing_decision_service.revoke(
        media_id,
        proposition,
        actor=actor,
        reason=reason,
    )

    return {
        "standing_decision": standing_decision_to_dict(
            decision
        ),
        "refreshed_at": now_timestamp(),
    }

def opportunities_data(services):
    queue = services.recommendation_service.get_current_queue()

    prioritised = (
        services
        .recommendation_service
        .get_prioritised_recommendations()
    )

    sets = services.recommendation_service.get_recommendation_sets()

    projection = (
        services.recommendation_service.get_savings_projection()
    )

    return {
        "queue": [candidate_to_dict(item) for item in queue],
        "prioritised": [
            prioritised_recommendation_to_dict(item)
            for item in prioritised
        ],
        "sets": [
            recommendation_set_to_dict(item)
            for item in sets
        ],
        "projection": savings_projection_to_dict(projection),
        "refreshed_at": now_timestamp(),
    }


def opportunity_detail_data(services, media_id):
    try:
        entry = (
            services
            .library_status_service
            .get_lineage_status(media_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    candidate = None

    for item in services.recommendation_service.get_current_queue():
        if item.media_id == media_id:
            candidate = item
            break

    prioritised_item = None

    for item in (
        services
        .recommendation_service
        .get_prioritised_recommendations()
    ):
        if item.candidate.media_id == media_id:
            prioritised_item = item
            break

    explanation = None

    if entry.valid_run_id is not None:
        try:
            explanation = services.provenance_service.explain(
                entry.valid_run_id
            )
        except ValueError:
            explanation = None

    # The newest DURABLE recommendation record for this lineage,
    # when one exists (records are produced by the pipeline per
    # run; lineages analysed before persistence have none). Its
    # state, produced payload and intelligence identity are shown
    # verbatim; nothing is fabricated for older data.
    record = (
        services.recommendation_service.get_latest_record(
            media_id
        )
    )

    record_view = (
        recommendation_record_to_dict(record)
        if record is not None
        else None
    )

    media_jobs = services.execution_service.list_jobs_by_media(
        media_id
    )

    newest_job = None

    for job in media_jobs:
        if newest_job is None or job.id > newest_job.id:
            newest_job = job

    return {
        "entry": lineage_status_to_dict(entry),
        "candidate": (
            candidate_to_dict(candidate)
            if candidate is not None
            else None
        ),
        "prioritised": (
            prioritised_recommendation_to_dict(prioritised_item)
            if prioritised_item is not None
            else None
        ),
        "record": record_view,
        "active_job": _job_visibility(newest_job),
        "explanation": (
            explanation_to_dict(explanation)
            if explanation is not None
            else None
        ),
        # Advanced controls render ONLY from the authoritative
        # executable-operation registry (Phase 6).
        "operations": (
            services.operation_service.executable_operations()
        ),
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Library intelligence (Sprint 7)
# ---------------------------------------------------------


def intelligence_data(services):
    """
    Authoritative library-intelligence reads surfaced through the
    application boundary (LibraryService).
    """

    statistics = services.library_service.get_statistics()

    storage = services.library_service.get_storage_consumption()

    health = services.library_service.get_library_health()

    savings = services.library_service.get_savings_distribution()

    confidence = (
        services.library_service.get_confidence_distribution()
    )

    return {
        "statistics": library_statistics_to_dict(statistics),
        "storage": storage_consumption_to_dict(storage),
        "health": library_health_to_dict(health),
        "savings": savings_distribution_to_dict(savings),
        "confidence": confidence_distribution_to_dict(confidence),
        "lineage_statuses": [
            library_lineage_status_to_dict(entry)
            for entry in (
                services.library_service.get_lineage_statuses()
            )
        ],
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 8 operational workflows (targeted analysis, queue export)
# ---------------------------------------------------------


def analyse_media_data(services, media_id):
    """
    Targeted analysis of one lineage through the application
    boundary. Currentness is decided entirely by the pipeline's
    validity gate; an already-valid analysis skips (files_processed
    0). No lineage state is mutated by this handler.
    """

    try:
        results = services.analysis_service.analyze_lineage(
            media_id
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    if len(results) == 0:

        message = (
            "Analysis is already valid for the current file "
            "state; the validity gate skipped a new run."
        )

    else:

        message = (
            "Targeted analysis completed; new analysis state "
            "was persisted by the pipeline."
        )

    return {
        "media_id": media_id,
        "files_processed": len(results),
        "message": message,
        "refreshed_at": now_timestamp(),
    }


def queue_export_data(services):
    """
    The non-destructive queue manifest, derived on demand from the
    authoritative current-valid prioritised recommendations.
    """

    return build_queue_manifest(
        services.recommendation_service
    )


# ---------------------------------------------------------
# Runs (analysis history + provenance detail + comparison)
# ---------------------------------------------------------


def runs_data(services, status=None, media_id=None):
    """
    Persisted analysis runs (newest first), optionally narrowed by
    the recorded run status and/or one media lineage.

    Filtering is applied to the AUTHORITATIVE persisted list only;
    no run state is reinterpreted and nothing is recomputed.
    """

    summaries = services.library_status_service.get_analysis_runs()

    if status:

        wanted = str(status).strip().lower()

        summaries = [
            item
            for item in summaries
            if item.run.status == wanted
        ]

    if media_id is not None:

        summaries = [
            item
            for item in summaries
            if item.run.media_id == media_id
        ]

    return {
        "runs": [
            run_summary_to_dict(item) for item in summaries
        ],
        "status_filter": status or None,
        "media_id_filter": media_id,
        "refreshed_at": now_timestamp(),
    }


def run_detail_data(services, run_id):
    run_id = _int_or_404(run_id, "run id")

    try:
        provenance = (
            services
            .provenance_service
            .get_analysis_provenance(run_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    explanation = services.provenance_service.explain(run_id)

    media = None

    if provenance.analysis_run.media_id is not None:
        try:
            media = services.media_service.get_media_item(
                provenance.analysis_run.media_id
            )
        except ValueError:
            media = None

    return {
        "run": run_to_dict(provenance.analysis_run),
        "provenance": provenance_to_dict(provenance),
        "explanation": explanation_to_dict(explanation),
        "media": (
            {
                "id": media.id,
                "file_name": media.file_name,
                "file_path": media.file_path,
                "status": media.status,
            }
            if media is not None
            else None
        ),
        "refreshed_at": now_timestamp(),
    }


def compare_runs_data(services, run_a_id, run_b_id):
    run_a_id = _int_or_404(run_a_id, "run id")
    run_b_id = _int_or_404(run_b_id, "run id")

    try:
        comparison = (
            services
            .provenance_service
            .compare_analysis_runs(run_a_id, run_b_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return {
        "comparison": comparison_to_dict(comparison),
        "refreshed_at": now_timestamp(),
    }


def compare_select_data(services, run_a_id):
    """
    Choose a second run to compare against Run #run_a_id.

    Only runs of the same media lineage are offered: cross-lineage
    comparison is rejected by the provenance authority. Raises
    NotFound when run_a_id does not exist.
    """

    run_a_id = _int_or_404(run_a_id, "run id")

    try:
        run_a = (
            services
            .provenance_service
            .get_analysis_provenance(run_a_id)
        ).analysis_run
    except ValueError as error:
        raise _not_found_from(str(error))

    runs = services.library_status_service.get_analysis_runs()

    others = [
        run_summary_to_dict(item)
        for item in runs
        if (
            item.run.id != run_a_id
            and item.run.media_id == run_a.media_id
        )
    ]

    return {
        "run_a_id": run_a_id,
        "others": others,
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 9 execution workflows (explicit approval boundary)
# ---------------------------------------------------------


# Presentation-only grouping of the execution state machine's
# states into queue sections. The lifecycle itself is untouched;
# this only decides WHERE a recorded state is displayed.
EXECUTION_QUEUE_GROUPS = [
    ("pending", "Awaiting action",
     ("approved", "planned"),
     "Approved jobs waiting to be planned and run. "
     "Nothing executes until you start it."),
    ("active", "In progress",
     ("running", "verifying", "replacing"),
     "Jobs currently executing or being verified."),
    ("completed", "Completed",
     ("succeeded", "rolled_back"),
     "Finished optimisations (including reverted ones)."),
    ("attention", "Needs attention",
     (
         "failed_execution",
         "failed_verification",
         "failed_replacement",
         "interrupted",
         "recovered",
     ),
     "Failed or interrupted jobs. Failures are honest and "
     "terminal; interrupted jobs can be recovered."),
]


def execution_to_view(job):

    policy = job.policy_decision or {}

    return {
        "id": job.id,
        "media_id": job.media_id,
        "state": job.state,
        "state_label": execution_state_label(job.state)[0],
        "state_badge": execution_state_label(job.state)[1],
        "opportunity": job.opportunity,
        "analysis_run_id": job.analysis_run_id,
        "recommendation_id": job.recommendation_id,
        "source_path": job.source_path,
        "source_size_bytes": job.source_size_bytes,
        "source_mtime_ns": job.source_mtime_ns,
        "source_observation_id": job.source_observation_id,
        "approved_by": job.approved_by,
        "operation": job.plan.get("operation"),
        "operation_version": job.plan.get("operation_version"),
        "backup_path": job.backup_path,
        "output_sha256": job.output_sha256,
        "result_observation_id": (
            job.result_observation_id
        ),
        "delete_original_requested": bool(
            job.delete_original_requested
        ),
        "deletion_state": job.deletion_state,
        "original_deleted_at": job.original_deleted_at,
        "requested_transformation": transformation_to_dict(
            job.requested_transformation
        ),
        "predicted": predicted_savings_to_dict(job.predicted),
        "measured": measured_savings_to_dict(job.measured),
        "verification": dict(job.verification or {}),
        "policy_decision_allowed": policy.get("allowed"),
        "policy_reasons": list(policy.get("reasons") or []),
        "error": job.error,
    }


def executions_list_data(services, state_filter_arg=None):

    jobs = services.execution_service.list_jobs()

    # Optional outcome filter: a raw recorded state or a queue
    # group key. Applied to the authoritative job list only; the
    # recorded states themselves are never reinterpreted.
    state_filter = None

    group_keys = {
        group[0]: set(group[2])
        for group in EXECUTION_QUEUE_GROUPS
    }

    if state_filter_arg:

        candidate = str(state_filter_arg).strip().lower()

        if candidate in group_keys:

            state_filter = group_keys[candidate]

        else:

            state_filter = {candidate}

    grouped = []

    grouped_ids = set()

    for key, title, states, description in (
        EXECUTION_QUEUE_GROUPS
    ):

        members = [
            execution_to_view(job)
            for job in jobs
            if job.state in states
            and (
                state_filter is None
                or job.state in state_filter
            )
        ]

        if state_filter is not None and not members:

            continue

        grouped.append(
            {
                "key": key,
                "title": title,
                "description": description,
                "executions": members,
            }
        )

        grouped_ids.update(states)

    filtered_states = state_filter

    # States outside every group would be hidden data; surface
    # them honestly in their own section instead.
    unexpected = [
        execution_to_view(job)
        for job in jobs
        if job.state not in grouped_ids
        and (
            filtered_states is None
            or job.state in filtered_states
        )
    ]

    def _matches(job):

        if state_filter is None:

            return True

        return job.state in state_filter or (
            job.state not in grouped_ids
            and job.state in state_filter
        )

    return {
        # Flat newest-first list preserved for the established JSON
        # mirror consumers; groups are the presentation view.
        "executions": [
            execution_to_view(job)
            for job in jobs
            if _matches(job)
        ],
        "groups": grouped,
        "unexpected_states": unexpected,
        "state_filter": state_filter_arg,
        "total_count": len(jobs),
        "refreshed_at": now_timestamp(),
    }


def execution_detail_data(services, job_id):

    try:

        job = services.execution_service.get(job_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "execution": execution_to_view(job),
        "before_after": _before_after_view(services, job),
        "refreshed_at": now_timestamp(),
    }


def _before_after_view(services, job):
    """
    Before/after execution visibility (Sprint 12).

    Pairs the two filesystem facts the execution record already
    links durably:

    - before: the observation of the producing analysis run
      (job.analysis_run_id), resolved through the lineage's
      authoritative observation history
    - after: the resulting observation recorded by the execution
      authority (job.result_observation_id)

    Both sides are read from persisted relationships only. When a
    side cannot be resolved (for example an interrupted job that
    never replaced anything) it is reported as absent rather than
    substituted or guessed.
    """

    before_run_id = job.analysis_run_id

    after_observation_id = job.result_observation_id

    if before_run_id is None and after_observation_id is None:

        return None

    try:

        history = (
            services.media_service.get_observation_history(
                job.media_id
            )
        )

    except ValueError:

        return None

    observations_by_id = {}

    run_to_observation = {}

    for entry in history.observations:

        observations_by_id[entry.observation.id] = (
            entry.observation
        )

        for run in entry.analysis_runs:

            run_to_observation[run.id] = entry.observation

    before_observation = (
        run_to_observation.get(before_run_id)
        if before_run_id is not None
        else None
    )

    after_observation = (
        observations_by_id.get(after_observation_id)
        if after_observation_id is not None
        else None
    )

    if before_observation is None and after_observation is None:

        return None

    return {
        "before_run_id": before_run_id,
        "before": (
            observation_to_dict(before_observation)
            if before_observation is not None
            else None
        ),
        "after": (
            observation_to_dict(after_observation)
            if after_observation is not None
            else None
        ),
    }


def execution_approve_data(services, media_id, body):

    approved_by = "human"

    delete_original_requested = False

    if isinstance(body, dict):

        raw = (body.get("approved_by") or [None])[0]

        if raw and raw.strip():

            approved_by = raw.strip()

        raw_delete = (body.get("delete_original") or [None])[0]

        delete_original_requested = bool(
            raw_delete
            and str(raw_delete).strip().lower()
            in ("1", "true", "yes", "on")
        )

    try:

        job_id = services.execution_service.approve(
            media_id,
            approved_by=approved_by,
            delete_original_requested=(
                delete_original_requested
            ),
        )

        job = services.execution_service.get(job_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "execution": execution_to_view(job),
        "refreshed_at": now_timestamp(),
    }


def execution_run_data(services, job_id):

    try:

        job = services.execution_service.run(job_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "execution": execution_to_view(job),
        "refreshed_at": now_timestamp(),
    }


def execution_rollback_data(services, job_id):

    try:

        job = services.execution_service.rollback(job_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "execution": execution_to_view(job),
        "refreshed_at": now_timestamp(),
    }


def execution_delete_original_data(services, job_id):

    try:

        job = services.execution_service.delete_original(job_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "execution": execution_to_view(job),
        "refreshed_at": now_timestamp(),
    }


def execution_run_queue_data(services, body):
    """
    Start the background execution queue. The queue worker executes
    one approved/planned job at a time, recovering eligible unfinished
    jobs first. Failures are terminal and truthful; later jobs
    continue.
    """

    summary = services.execution_service.run_queue()

    return {
        "summary": summary,
        "total": (
            len(summary["run"])
            + len(summary["failed"])
            + len(summary["recovered"])
        ),
        "refreshed_at": now_timestamp(),
    }


def execution_advanced_approve_data(services, media_id, body):
    """
    Advanced-path approval: approve a user-selected operation with
    validated parameters through the single advanced approval
    boundary. The operation must be registered and executable in
    the closed operation registry; every parameter is validated
    against that operation's definition before anything is
    recorded. No free-form FFmpeg input ever reaches execution.
    """

    operation = None

    parameters = {}

    delete_original_requested = False

    if isinstance(body, dict):

        raw_operation = (body.get("operation") or [None])[0]

        if raw_operation and str(raw_operation).strip():

            operation = str(raw_operation).strip()

        if operation is not None:

            try:

                schema = (
                    services.operation_service.operation_schema(
                        operation
                    )
                )

            except ValueError as error:

                raise _not_found_from(str(error))

            for param in schema.get("parameters") or []:

                name = param.get("name")

                if not name:

                    continue

                raw_values = body.get(f"param_{name}") or []

                if not raw_values:

                    continue

                value = raw_values[0]

                if value is None:

                    continue

                value = str(value).strip()

                if value == "":

                    continue

                parameters[name] = value

        # Legacy form encoding: bare "name=value" entries under the
        # shared "parameters" field. Preserved so previously
        # rendered forms still validate through the registry.
        raw_parameters = body.get("parameters") or []

        for raw in raw_parameters:

            if "=" in raw:

                key, _, value = raw.partition("=")

                parameters[str(key).strip()] = (
                    str(value).strip()
                )

        raw_delete = (body.get("delete_original") or [None])[0]

        delete_original_requested = bool(
            raw_delete
            and str(raw_delete).strip().lower()
            in ("1", "true", "yes", "on")
        )

    if not operation:

        # Legacy form encoding without an explicit operation
        # selection: validate the parameters against the
        # recommendation-derived operation through the single
        # approval boundary. Preserves the established
        # advanced-approve contract.
        try:

            job_id = services.execution_service.approve(
                media_id,
                approved_by="human",
                delete_original_requested=(
                    delete_original_requested
                ),
                parameters=parameters,
            )

            job = services.execution_service.get(job_id)

        except ValueError as error:

            raise _not_found_from(str(error))

        return {
            "execution": execution_to_view(job),
            "refreshed_at": now_timestamp(),
        }

    try:

        job_id = services.execution_service.approve_advanced(
            media_id,
            operation=operation,
            parameters=parameters,
            approved_by="human",
            delete_original_requested=(
                delete_original_requested
            ),
        )

        job = services.execution_service.get(job_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "execution": execution_to_view(job),
        "refreshed_at": now_timestamp(),
    }


def quick_find_page_data(services):
    """
    Quick Find page data: the executable operations exposed through
    the operation registry (presentation only; the GUI renders
    controls ONLY for executable operations).
    """

    return {
        "operations": services.operation_service.executable_operations(),
        "refreshed_at": now_timestamp(),
    }


def operations_data(services):
    """
    The closed executable-operation registry exposed to the GUI. The
    GUI renders advanced controls ONLY from this authoritative schema;
    it never constructs FFmpeg commands.
    """

    return {
        "operations": services.operation_service.executable_operations(),
        "all_operations": services.operation_service.list_operations(),
        "policy_values": services.operation_service.policy_values(),
        "refreshed_at": now_timestamp(),
    }


def quick_find_data(services, body):
    """
    Quick Find: analyse ONE media file through the existing pipeline
    and return its current-valid recommendation. The result flows
    through the existing approval and execution boundaries unchanged.
    """

    path = None

    if isinstance(body, dict):

        raw = (body.get("path") or [None])[0]

        if raw and raw.strip():

            path = raw.strip()

    if not path:

        raise _not_found_from("A media path is required")

    try:

        result = services.quick_find_service.find(path)

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "path": result["path"],
        "media_id": result["media_id"],
        "lineage_name": result["lineage_name"],
        "analysis_reported": result["analysis_reported"],
        "candidate": (
            candidate_to_dict(result["candidate"])
            if result["candidate"] is not None
            else None
        ),
        "has_candidate": result["candidate"] is not None,
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 11 optimisation experience & recommendation workflow
# ---------------------------------------------------------


def _selected_media_ids(body):
    """
    Parse the shared 'selected' form field into validated media
    ids. Duplicates are preserved so the confirmation page shows
    exactly what was submitted; the approval boundary reports a
    refusal for the repeat.
    """

    if not isinstance(body, dict):

        raise ValueError("No selection was submitted")

    raw_ids = body.get("selected") or []

    if isinstance(raw_ids, str):

        raw_ids = [raw_ids]

    try:

        ids = [int(raw) for raw in raw_ids]

    except (TypeError, ValueError):

        raise ValueError(
            "The selection contained an invalid media id"
        )

    if not ids:

        raise ValueError(
            "Select one or more recommendations first"
        )

    return ids


def accept_selected_confirmation_data(services, body):
    """
    Confirmation step for the Accept Selected workflow.

    This handler performs NO writes: it re-reads the authoritative
    current-valid queue and reports the facts the user is about to
    approve, including items that can no longer be approved. The
    actual approval happens only in accept_selected_apply_data via
    ExecutionService.approve_selected.
    """

    selected = _selected_media_ids(body)

    candidates = {
        item.media_id: item
        for item in (
            services.recommendation_service
            .get_current_queue()
        )
    }

    items = []

    still_approvable = []

    for media_id in selected:

        candidate = candidates.get(media_id)

        if candidate is None:

            items.append(
                {
                    "media_id": media_id,
                    "approvable": False,
                    "reason": (
                        "no current-valid recommendation; "
                        "the analysis may be stale or the "
                        "recommendation already handled"
                    ),
                }
            )

            continue

        candidate_view = candidate_to_dict(candidate)

        items.append(
            {
                "media_id": media_id,
                "approvable": True,
                "file_name": candidate.file_name,
                "file_path": candidate.file_path,
                "opportunity": candidate.opportunity,
                "confidence_percent": format_confidence(
                    candidate.confidence
                ),
                "saving_percent": format_percent(
                    candidate.estimated_saving_percent
                ),
                "estimated_saved_size": format_bytes(
                    candidate.estimated_saved_bytes
                ),
                "estimated_saved_bytes": (
                    candidate.estimated_saved_bytes
                ),
                "risk": candidate.risk,
                "analysis_run_id": candidate.analysis_run_id,
                "change_summary": candidate_view.get(
                    "change_summary"
                ),
            }
        )

        still_approvable.append(media_id)

    return {
        "items": items,
        "selected_ids": selected,
        "approvable_ids": still_approvable,
        "refreshed_at": now_timestamp(),
    }


def accept_selected_apply_data(services, body):
    """
    Perform the confirmed batch acceptance through the single
    execution approval boundary (approve -> per-item results).
    """

    selected = _selected_media_ids(body)

    delete_original_requested = False

    if isinstance(body, dict):

        raw_delete = (body.get("delete_original") or [None])[0]

        delete_original_requested = bool(
            raw_delete
            and str(raw_delete).strip().lower()
            in ("1", "true", "yes", "on")
        )

    results = services.execution_service.approve_selected(
        selected,
        approved_by="human",
        delete_original_requested=(
            delete_original_requested
        ),
    )

    approved_views = []

    jobs_by_id = {
        job.id: job
        for job in services.execution_service.list_jobs()
    }

    for entry in results["approved"]:

        job = jobs_by_id.get(entry["job_id"])

        approved_views.append(
            {
                "media_id": entry["media_id"],
                "job": (
                    execution_to_view(job)
                    if job is not None
                    else None
                ),
            }
        )

    return {
        "approved": approved_views,
        "refused": results["refused"],
        "refreshed_at": now_timestamp(),
    }


def _reject_candidate_view(services, media_id):
    """
    Candidate-level dashboard rejection for one media lineage.

    The server resolves the currently active propositions
    authoritatively at processing time; nothing from the
    rendered Dashboard page is trusted. When no proposition is
    currently active the lineage is reported as already handled
    and no refusal record is created. Otherwise every active
    proposition is refused atomically through the existing
    standing-decision semantics.
    """

    media_id = _int_or_404(media_id, "media id")

    try:
        media = services.media_service.get_media_item(
            media_id
        )
        file_name = media.file_name
    except ValueError:
        file_name = f"media {media_id}"

    propositions = (
        services
        .recommendation_service
        .active_propositions_for(media_id)
    )

    if not propositions:
        return {
            "media_id": media_id,
            "file_name": file_name,
            "rejected": False,
            "reason": (
                "Already handled: nothing currently active "
                "for this file."
            ),
        }

    services.standing_decision_service.refuse_propositions(
        media_id,
        propositions,
        actor="human",
        reason=None,
    )

    return {
        "media_id": media_id,
        "file_name": file_name,
        "rejected": True,
        "count": len(propositions),
    }


def dashboard_reject_data(services, media_id, body):
    """
    Confirmed single dashboard rejection. Renders the same
    rejection report as the bulk flow with exactly one item.
    Unexpected failures propagate to the existing error routing;
    only the already-handled case renders normally.
    """

    _ = body

    view = _reject_candidate_view(services, media_id)

    return {
        "rejected": [view] if view["rejected"] else [],
        "unactionable": [] if view["rejected"] else [view],
        "failed": [],
        "refreshed_at": now_timestamp(),
    }


def dashboard_reject_selected_data(services, body):
    """
    Confirmed bulk dashboard rejection over the shared selection
    model. Each selected lineage is processed independently with
    candidate-level semantics; one candidate's failure never
    prevents the remaining selections from being processed, and
    every item lands in exactly one outcome list.
    """

    selected = _selected_media_ids(body)

    rejected = []
    unactionable = []
    failed = []

    for media_id in selected:
        try:
            view = _reject_candidate_view(services, media_id)
        except Exception:
            traceback.print_exc()
            failed.append(
                {
                    "media_id": media_id,
                    "file_name": f"media {media_id}",
                }
            )
            continue

        if view["rejected"]:
            rejected.append(view)
        else:
            unactionable.append(view)

    return {
        "rejected": rejected,
        "unactionable": unactionable,
        "failed": failed,
        "refreshed_at": now_timestamp(),
    }


def recommendation_detail_data(services, recommendation_id):
    """
    One durable recommendation record with its lifecycle events,
    the lineage's authoritative validity state, and its execution
    job view when one is linked.

    All content is read through application boundaries from the
    existing authorities: recommendation records (pipeline-
    produced), validity (LibraryStatusService fields verbatim),
    and the execution service.
    """

    try:

        detail = services.recommendation_service \
            .get_recommendation(recommendation_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    record = detail["recommendation"]

    try:

        entry = (
            services
            .library_status_service
            .get_lineage_status(record.media_id)
        )

        lineage_view = lineage_status_to_dict(entry)

    except ValueError:

        lineage_view = None

    job_view = None

    if record.execution_job_id is not None:

        try:

            job_view = execution_to_view(
                services.execution_service.get(
                    record.execution_job_id
                )
            )

        except ValueError:

            job_view = None

    return {
        "record": recommendation_record_to_dict(record),
        "events": recommendation_events_to_dict(
            detail["events"]
        ),
        "lineage": lineage_view,
        "execution": job_view,
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 12 history, comparison & observability
# ---------------------------------------------------------


def media_history_data(services, media_id):
    """
    The consolidated historical timeline for one media lineage.

    Every section composes an EXISTING authoritative read:

    - current validity state   -> LibraryStatusService (fields
      used verbatim)
    - observations -> runs     -> MediaService observation
      history (ProvenanceQueryService reconstruction)
    - recommendation records   -> RecommendationService durable
      history (records + append-only events)
    - execution outcomes       -> ExecutionService per-media job
      history

    Nothing is reinterpreted, recomputed, or invented: a section
    is simply absent when the lineage has no data of that kind.
    """

    try:

        entry = (
            services
            .library_status_service
            .get_lineage_status(media_id)
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    try:

        history = services.media_service.get_observation_history(
            media_id
        )

        history_view = observation_history_to_dict(history)

    except ValueError:

        history_view = {"media": None, "observations": []}

    persisted = []

    if (
        services.recommendation_service.has_durable_records()
    ):

        for item in (
            services.recommendation_service
            .get_persisted_history(media_id)
        ):

            persisted.append(
                {
                    "record": recommendation_record_to_dict(
                        item["recommendation"]
                    ),
                    "events": recommendation_events_to_dict(
                        item["events"]
                    ),
                }
            )

    jobs = [
        execution_to_view(job)
        for job in (
            services.execution_service.list_jobs_by_media(
                media_id
            )
        )
    ]

    return {
        "entry": lineage_status_to_dict(entry),
        "history": history_view,
        "recommendations": persisted,
        "executions": jobs,
        "refreshed_at": now_timestamp(),
    }


def recommendation_compare_select_data(
    services,
    recommendation_id,
):
    """
    Choose a second durable recommendation of the SAME lineage to
    compare against. Only same-lineage records are offered because
    cross-lineage comparison is refused by the comparison workflow.
    """

    try:

        detail = services.recommendation_service \
            .get_recommendation(recommendation_id)

    except ValueError as error:

        raise _not_found_from(str(error))

    record = detail["recommendation"]

    others = []

    for item in (
        services.recommendation_service
        .get_persisted_history(record.media_id)
    ):

        other = item["recommendation"]

        if other.id == record.id:

            continue

        others.append(
            {
                "id": other.id,
                "state": other.state,
                "opportunity": other.opportunity,
                "created_at": other.created_at,
            }
        )

    return {
        "record": recommendation_record_to_dict(record),
        "others": others,
        "refreshed_at": now_timestamp(),
    }


def recommendation_compare_data(
    services,
    recommendation_id_a,
    recommendation_id_b,
):
    """
    Side-by-side comparison of two durable recommendations via the
    application-layer comparison workflow. ValueError (missing or
    incompatible records) becomes a 404 like run comparisons.
    """

    recommendation_id_a = _int_or_404(
        recommendation_id_a, "recommendation id"
    )

    recommendation_id_b = _int_or_404(
        recommendation_id_b, "recommendation id"
    )

    try:

        comparison = (
            services.recommendation_service
            .compare_recommendations(
                recommendation_id_a,
                recommendation_id_b,
            )
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    return {
        "comparison": comparison,
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 13 library organisation
#
# Handlers compose the organisation application boundary only:
# no persistence access, no rule logic, no filesystem access,
# and no second queue. Generation and acceptance are explicit
# user actions; acceptance records durable intent only.
# ---------------------------------------------------------


def _selected_proposal_ids(body):
    """
    Parse the shared 'selected' form field into validated
    proposal ids (same convention as _selected_media_ids).
    """

    if not isinstance(body, dict):

        raise ValueError("No selection was submitted")

    raw_ids = body.get("selected") or []

    if isinstance(raw_ids, str):

        raw_ids = [raw_ids]

    try:

        ids = [int(raw) for raw in raw_ids]

    except (TypeError, ValueError):

        raise ValueError("Invalid proposal selection")

    if not ids:

        raise ValueError(
            "Select at least one organisation proposal"
        )

    return ids


def organisation_data(services):
    """
    The current organisation view: the latest completed decision
    run, its proposals grouped by state, and honest coverage of
    hash evidence. Empty when no decision run exists yet.
    """

    current = services.organisation_service.get_current_proposals()

    decision_run_view = None

    proposals = []

    proposed_count = 0

    decided_count = 0

    if current is not None:

        decision_run = current["decision_run"]

        decision_run_view = (
            organisation_decision_run_to_dict(decision_run)
        )

        for record in current["proposals"]:

            view = organisation_proposal_to_dict(record)

            proposals.append(view)

            if record.state == "proposed":

                proposed_count += 1

            else:

                decided_count += 1

    return {
        "decision_run": decision_run_view,
        "proposals": proposals,
        "proposed_count": proposed_count,
        "decided_count": decided_count,
        "refreshed_at": now_timestamp(),
    }


def organisation_generate_data(services):
    """
    Run one deterministic organisation decision pass through the
    application boundary.

    This performs ZERO filesystem mutation: it reads persisted
    observations and writes durable proposals + their provenance
    anchor only.
    """

    summary = services.organisation_service.generate_proposals()

    return {
        "summary": summary,
        "refreshed_at": now_timestamp(),
    }


def proposal_detail_data(services, proposal_id):
    """
    One durable organisation proposal with its lifecycle events
    and the producing decision-run snapshot (rule versions,
    policy values, identity digest).
    """

    try:

        detail = services.organisation_service.get_proposal(
            int(proposal_id)
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    proposal = detail["proposal"]

    run_view = None

    try:

        run = services.organisation_service.get_decision_run(
            proposal.decision_run_id
        )

        if run is not None:

            run_view = (
                organisation_decision_run_to_dict(run)
            )

    except ValueError:

        run_view = None

    media_lineage = None

    try:

        lineage = services.media_service.get_media_item(
            proposal.media_id
        )

        media_lineage = {
            "id": lineage.id,
            "file_path": lineage.file_path,
            "file_name": lineage.file_name,
            "status": lineage.status,
        }

    except ValueError:

        media_lineage = None

    return {
        "proposal": organisation_proposal_to_dict(proposal),
        "events": organisation_events_to_dict(
            detail["events"]
        ),
        "decision_run": run_view,
        "media": media_lineage,
        "refreshed_at": now_timestamp(),
    }


def organisation_accept_confirmation_data(services, body):
    """
    Write-free confirmation step: re-reads the authoritative
    current proposals and reports exactly what acceptance will
    record, including selections that can no longer be accepted.
    """

    selected = _selected_proposal_ids(body)

    proposals_by_id = {}

    current = services.organisation_service.get_current_proposals()

    if current is not None:

        for record in current["proposals"]:

            proposals_by_id[record.id] = record

    items = []

    still_acceptable = []

    for proposal_id in selected:

        record = proposals_by_id.get(proposal_id)

        if record is None or record.state != "proposed":

            items.append(
                {
                    "proposal_id": proposal_id,
                    "acceptable": False,
                    "reason":
                        "not a currently-proposed "
                        "organisation proposal; it may be "
                        "superseded by a newer decision run "
                        "or already handled",
                }
            )

            continue

        view = organisation_proposal_to_dict(record)

        view["acceptable"] = True

        items.append(view)

        still_acceptable.append(proposal_id)

    return {
        "items": items,
        "selected_ids": selected,
        "acceptable_ids": still_acceptable,
        "refreshed_at": now_timestamp(),
    }


def organisation_accept_apply_data(services, body):
    """
    Perform the confirmed batch acceptance through the single
    organisation application boundary. Acceptance records
    durable approved intent ONLY; NAMOA performs no filesystem
    operation in Sprint 13.
    """

    selected = _selected_proposal_ids(body)

    results = services.organisation_service.accept_selected(
        selected,
        accepted_by="human",
    )

    return {
        "accepted": results["accepted"],
        "refused": results["refused"],
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Phase 7 organisation execution (GUI surface over the existing
# organisation execution authority; never a second execution
# mechanism)
# ---------------------------------------------------------


# Presentation-only grouping of the organisation execution state
# machine into queue sections. The lifecycle itself is untouched;
# this only decides WHERE a recorded state is displayed.
ORGANISATION_EXECUTION_QUEUE_GROUPS = [
    ("pending", "Awaiting execution",
     ("proposed", "approved"),
     "Approved organisation proposals that have not started "
     "executing. Nothing moves until you start it."),
    ("active", "In progress",
     ("precondition_verified", "executing", "verifying",
      "observation_persistence", "provenance_persistence"),
     "Organisation executions currently running or being "
     "verified."),
    ("completed", "Completed",
     ("succeeded",),
     "Finished, verified organisation changes."),
    ("attention", "Needs attention",
     ("failed", "interrupted", "recovery_required"),
     "Failed or uncertain organisation executions. Failures are "
     "honest and terminal; interrupted/uncertain executions must "
     "be recovered against real filesystem reality."),
]


def organisation_executions_data(services):
    """
    The organisation execution queue: every recorded execution
    grouped by state for presentation. Reads flow through the
    application boundary only.
    """

    executions = services.organisation_execution_service.list()

    grouped = []

    grouped_states = set()

    for key, title, states, description in (
        ORGANISATION_EXECUTION_QUEUE_GROUPS
    ):

        members = [
            organisation_execution_to_dict(execution)
            for execution in executions
            if execution.state in states
        ]

        grouped_states.update(states)

        if not members and key != "attention":
            continue

        grouped.append(
            {
                "key": key,
                "title": title,
                "description": description,
                "executions": members,
            }
        )

    unexpected = [
        organisation_execution_to_dict(execution)
        for execution in executions
        if execution.state not in grouped_states
    ]

    counts = {
        "pending": 0,
        "active": 0,
        "completed": 0,
        "attention": 0,
        "total": len(executions),
    }

    for execution in executions:

        for key, _, states, _ in ORGANISATION_EXECUTION_QUEUE_GROUPS:

            if execution.state in states:

                counts[key] += 1

                break

    return {
        "executions": [
            organisation_execution_to_dict(execution)
            for execution in executions
        ],
        "groups": grouped,
        "unexpected_states": unexpected,
        "counts": counts,
        "total_count": len(executions),
        "refreshed_at": now_timestamp(),
    }


def organisation_execution_detail_data(services, execution_id):
    """
    One organisation execution with its lifecycle events, the
    execution-authorised identity continuity, and the producing
    proposal context.
    """

    return _organisation_execution_detail(
        services,
        int(execution_id),
    )


def _organisation_execution_detail(services, execution_id):
    """
    Compose the full organisation execution detail view (execution,
    events, continuity, producing proposal) from the application
    boundary reads.
    """

    try:

        execution = (
            services.organisation_execution_service.get(
                execution_id
            )
        )

        events = (
            services.organisation_execution_service.events(
                execution_id
            )
        )

        continuity = (
            services.organisation_execution_service.continuity(
                execution_id
            )
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    proposal = None

    try:

        proposal = services.organisation_service.get_proposal(
            execution.proposal_id
        )["proposal"]

    except ValueError:

        proposal = None

    return {
        "execution": organisation_execution_to_dict(execution),
        "events": organisation_events_to_dict(events),
        "continuity": [
            organisation_execution_continuity_to_dict(entry)
            for entry in continuity
        ],
        "proposal": (
            organisation_proposal_to_dict(proposal)
            if proposal is not None
            else None
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_execution_execute_data(services, proposal_id, body):
    """
    Execute one approved organisation proposal through the existing
    execution authority. Explicit human action; the approval boundary
    is unchanged (only 'accepted' proposals execute).
    """

    actor = "human"

    if isinstance(body, dict):

        raw = (body.get("actor") or [None])[0]

        if raw and raw.strip():

            actor = raw.strip()

    try:

        execution = (
            services.organisation_execution_service.execute(
                int(proposal_id),
                actor=actor,
            )
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    return _organisation_execution_detail(
        services,
        execution.id,
    )


def organisation_execution_recover_data(services, execution_id):
    """
    Reconcile one interrupted/uncertain organisation execution
    against real filesystem reality through the existing recovery
    authority.
    """

    try:

        execution = (
            services.organisation_execution_service.recover(
                int(execution_id),
            )
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    return _organisation_execution_detail(
        services,
        execution.id,
    )


# ---------------------------------------------------------
# Sprint 15 integrations settings
#
# Thin reads/writes over the integration application
# boundary only. Credential values are never read back:
# only presence and source are surfaced.
# ---------------------------------------------------------


def _form_value(body, name):
    """First form value stripped, or None when absent."""

    if not isinstance(body, dict):
        return None

    raw = (body.get(name) or [None])[0]

    if raw is None:
        return None

    text = str(raw).strip()

    return text or None


def _form_flag(body, name):
    """Checkbox-style form flag (present and truthy)."""

    if not isinstance(body, dict):
        return False

    raw = (body.get(name) or [None])[0]

    return bool(
        raw
        and str(raw).strip().lower()
        in ("1", "true", "yes", "on")
    )


def organisation_integrations_data(services):
    """
    Public settings views for every provider (enabled,
    base URL, credential presence/source). No network
    access; credential values are never surfaced.
    """

    return {
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def _is_secret_store_failure(error):
    """True when an error comes from the secret store layer."""

    from app.security.secret_store import (
        SecretStoreError,
        SecretStoreUnavailableError,
    )

    seen = set()
    current = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(
            current,
            (
                SecretStoreError,
                SecretStoreUnavailableError,
            ),
        ):
            return True

        text = str(current).lower()

        if (
            "secret store" in text
            or "keyring backend failed" in text
            or "keyring package is not installed" in text
            or "no writable secret store" in text
            or "local app secret" in text
        ):
            return True

        current = getattr(current, "__cause__", None)

        if current is None:
            break

    return False


def _credential_user_error(action, error):
    """Build a titled credential error that never leaks values."""

    reason = str(error) or type(error).__name__

    return UserError(
        f"could not {action} the provider API key: "
        f"keyring unavailable and local fallback "
        f"failed ({reason}). Set the documented "
        f"NAMOA_<PROVIDER>_API_KEY environment override "
        f"or retry once the secret store is usable.",
        title="Integration credentials",
    )


def organisation_integrations_save_data(services, body):
    """
    Store one provider's non-secret configuration and,
    when supplied, its credential (secret store only).
    An absent/blank API key leaves the stored credential
    unchanged. Explicit human action only.
    """

    provider = _form_value(body, "provider")

    if not provider:
        raise ValueError("A provider is required")

    raw_key = None

    if isinstance(body, dict):
        raw_key = (body.get("api_key") or [None])[0]

    if raw_key is not None and not str(raw_key).strip():
        raw_key = None

    updated = None

    try:
        updated = (
            services.integration_service.configure_provider(
                provider.strip(),
                enabled=_form_flag(body, "enabled"),
                base_url=_form_value(body, "base_url") or "",
                api_key=raw_key,
            )
        )
    except UserError:
        raise
    except Exception as error:
        if _is_secret_store_failure(error):
            raise _credential_user_error("save", error)
        raise

    return {
        "updated": updated,
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_test_data(services, provider):
    """
    Live connection test for one provider using the
    resolved credential in memory only. The credential
    is never persisted, logged, or echoed.
    """

    try:
        result = (
            services.integration_service.test_connection(
                str(provider).strip()
            )
        )
    except UserError:
        raise
    except Exception as error:
        if _is_secret_store_failure(error):
            raise _credential_user_error("test", error)
        if isinstance(error, ValueError):
            raise _not_found_from(str(error))
        raise

    return {
        "result": result,
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_remove_credential_data(
    services,
    provider,
):
    """
    Delete one provider's stored credential. The
    configuration row is kept; disabling is a separate
    explicit action.
    """

    try:
        removed = (
            services.integration_service.remove_credential(
                str(provider).strip()
            )
        )
    except UserError:
        raise
    except Exception as error:
        if _is_secret_store_failure(error):
            raise _credential_user_error("remove", error)
        if isinstance(error, ValueError):
            raise _not_found_from(str(error))
        raise

    return {
        "removed": removed,
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_mapping_add_data(services, body):
    """
    Record one explicit provider-root to local-root
    relationship for deterministic association. Errors
    stay in context with the submitted input preserved.
    """

    provider = _form_value(body, "provider") or ""
    provider_root = _form_value(body, "provider_root") or ""
    local_root = _form_value(body, "local_root") or ""

    base = {
        "providers": (
            services.integration_service.list_providers()
        ),
        "mapping_input": {
            "provider": provider,
            "provider_root": provider_root,
            "local_root": local_root,
        },
        "refreshed_at": now_timestamp(),
    }

    try:
        saved = (
            services.integration_service.save_path_mapping(
                provider.strip().lower(),
                provider_root=provider_root,
                local_root=local_root,
            )
        )
    except Exception as error:
        base["form_error"] = {
            "title": "Unable to save this path mapping",
            "message": str(error) or type(error).__name__,
            "guidance": (
                "Use absolute paths such as /Movies for "
                "the provider root and /mnt/media/Movies "
                "for the local root. A provider root may "
                "have several local roots (one row per "
                "drive); saving the identical row again "
                "changes nothing."
            ),
            "status": 400,
        }

        return base

    saved["provider"] = provider.strip().lower()
    base["mapping_saved"] = saved

    return base


def organisation_integration_mapping_remove_data(
    services, body
):
    """Delete one explicit root mapping, then re-render."""

    provider = _form_value(body, "provider") or ""
    raw_id = _form_value(body, "mapping_id") or ""

    try:
        mapping_id = int(str(raw_id).strip())
    except (TypeError, ValueError):
        mapping_id = -1

    removed = (
        services.integration_service.delete_path_mapping(
            mapping_id
        )
        if mapping_id >= 0
        else False
    )

    return {
        "mapping_removed": {
            "provider": provider,
            "mapping_id": raw_id,
            "removed": bool(removed),
        },
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_tags_data(services, provider):
    """
    Live provider tag id-to-label inspection for the
    tag-mapping editor. Read-only; nothing persisted.
    Jellyfin tags are inline strings, so its map is
    empty by design. Failures render inline, never as
    a separate error page.
    """

    name = str(provider or "").strip().lower()

    try:
        labels = (
            services.integration_service
            .provider_tag_labels(name)
        )
    except Exception as error:
        labels = None
        failure = (
            f"{type(error).__name__}: {error}"
        )
    else:
        failure = None

    return {
        "tag_labels": {
            "provider": name,
            "labels": (
                sorted(
                    labels.items(), key=lambda item: item[0]
                )
                if isinstance(labels, dict)
                else []
            ),
            "error": failure,
        },
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_users_data(services):
    """
    Live Jellyfin user list for the explicit library-user
    picker. Read-only; nothing persisted. Failures render
    inline on the integrations page.
    """

    try:
        users = (
            services.integration_service.jellyfin_users()
        )
    except Exception as error:
        users = []
        failure = (
            f"{type(error).__name__}: {error}"
        )
    else:
        failure = None

    return {
        "jellyfin_users": {
            "users": users,
            "error": failure,
        },
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_user_save_data(services, body):
    """Persist the explicit Jellyfin library user id."""

    user_id = _form_value(body, "jellyfin_user_id") or ""

    base = {
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }

    try:
        saved = (
            services.integration_service.save_jellyfin_user(
                user_id
            )
        )
    except Exception as error:
        base["form_error"] = {
            "title": "Unable to save this library user",
            "message": str(error) or type(error).__name__,
            "guidance": (
                "Use Load users to see the available "
                "Jellyfin users, then save the id that "
                "owns the libraries NAMOA should read."
            ),
            "status": 400,
        }

        return base

    providers = (
        services.integration_service.list_providers()
    )

    return {
        "user_saved": saved,
        "providers": providers,
        "refreshed_at": now_timestamp(),
    }


def organisation_integration_sync_data(
    services,
    provider,
):
    """
    Validate one provider for a background metadata
    sync and return the re-rendered settings state.
    The actual sync runs off the request path; the
    server starts the worker after this returns. A
    disabled or unknown provider is refused with a
    clear message before anything starts.
    """

    name = str(provider or "").strip().lower()

    try:
        view = services.integration_service.get_provider(
            name
        )
    except Exception as error:
        if isinstance(error, ValueError):
            raise _not_found_from(str(error))
        raise

    if not view.get("enabled"):
        raise UserError(
            f"metadata sync for '{name}' needs the "
            f"provider enabled first: open the provider, "
            f"tick Enabled, save, then sync.",
            title="Provider not enabled",
        )

    return {
        "sync_started": {"provider": name},
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_integrations_sync_all_data(services):
    """
    Validate every enabled provider for a background
    Sync All run. Providers without credentials stay
    listed; the worker reports each result honestly.
    """

    providers = [
        view.get("provider")
        for view in (
            services.integration_service.list_providers()
        )
        if view.get("enabled")
    ]

    if not providers:
        raise UserError(
            "no enabled provider to sync: enable at "
            "least one provider first.",
            title="Nothing to sync",
        )

    return {
        "sync_started": {"provider": "all"},
        "sync_providers": providers,
        "providers": (
            services.integration_service.list_providers()
        ),
        "refreshed_at": now_timestamp(),
    }


def integration_sync_status_data(services, live):
    """
    Merge live background progress (server-owned, may
    be empty) with the durable per-provider ledger
    state. Read-only; counts only, never credentials.
    """

    live = dict(live or {})

    ledger = (
        services.integration_service
        .last_sync_summaries()
    )

    return {
        "running": bool(live.get("running")),
        "providers": list(live.get("providers") or []),
        "started_at": live.get("started_at"),
        "live": dict(live.get("live") or {}),
        "results": dict(live.get("results") or {}),
        "last_sync": {
            name: summary for name, summary in ledger.items()
        },
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 15 organisation profiles
#
# Reads and explicit saves over the organisation
# application boundary only. Validation errors are
# returned with the submitted input (nothing is lost);
# only a valid payload is ever saved.
# ---------------------------------------------------------


def organisation_profiles_data(services):
    """
    Saved profiles plus the built-in template
    catalogue, profile presets, and the
    guided-completion state of the empty editor.
    """

    return {
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "builtins": (
            services.organisation_service.builtin_templates()
        ),
        "presets": (
            services.organisation_service
            .list_profile_presets()
        ),
        "completion": (
            services.organisation_service
            .profile_completion({})
        ),
        "refreshed_at": now_timestamp(),
    }


def _profiles_form_extras(services, input_view):
    """
    Preset catalogue plus guided-completion state for
    every render of the profile editor. Completion is
    derived from the real validation rules applied to
    a candidate payload rebuilt from the entered
    input, so the checklist stays truthful.
    """

    candidate, synthetic = _input_to_payload_candidate(
        input_view,
        services.organisation_service.builtin_templates(),
        services,
    )

    completion = (
        services.organisation_service.profile_completion(
            candidate
        )
    )

    if synthetic:
        for problem in synthetic:
            if "tag mapping" in problem.lower():
                for section in completion["sections"]:
                    if section["key"] == "mappings":
                        section["detail"].append(problem)
                        section["complete"] = False

        completion["incomplete"] = [
            section["label"]
            for section in completion["sections"]
            if not section["complete"]
        ]
        completion["complete"] = not completion[
            "incomplete"
        ]

    return {
        "presets": (
            services.organisation_service
            .list_profile_presets()
        ),
        "completion": completion,
    }


def _filename_example(services, filename_policy):
    """Live extended-naming example for the editor."""

    policy = filename_policy or {}

    try:
        return (
            services.organisation_service
            .render_filename_example(
                policy.get("pattern"),
                policy.get("separator"),
            )
        )
    except Exception:
        return {
            "source": "",
            "base": "",
            "file_evidence": {},
            "result": "",
            "missing": [],
            "error": None,
        }


def _preset_to_input(payload, services=None):
    """
    Map a preset payload onto the profile editor form
    shape (same keys the save path reads). Pure;
    the preset itself is never mutated. Root rows and
    tokens resolve through the organisation service so
    this module stays on the application boundary.
    """

    templates = payload.get("templates") or {}

    selected_names = {
        "movie": payload.get("movie_template"),
        "tv": payload.get("tv_template"),
        "category": payload.get("category_template"),
    }

    def _pattern(key, fallback=""):
        # Resolve through the profile's selected template
        # name first (presets store "Basic Movies" style
        # names); fall back to any template of the
        # matching kind so the visible fields always
        # carry the real values that will be saved.
        wanted = selected_names.get(key)

        if (
            isinstance(wanted, str)
            and wanted
            and isinstance(templates.get(wanted), dict)
        ):
            return (
                templates[wanted].get("pattern") or fallback
            )

        kinds = {
            "movie": "movie",
            "tv": "tv",
            "category": "category",
        }

        for name in sorted(templates):
            template = templates.get(name) or {}

            if (
                isinstance(template, dict)
                and template.get("kind") == kinds.get(key)
                and template.get("pattern")
            ):
                return template.get("pattern")

        first = templates.get(wanted) or {}

        return first.get("pattern") or fallback

    categories = payload.get("categories") or {}

    mappings = payload.get("tag_mappings") or []

    naming = payload.get("naming") or {}

    map_rows = []

    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue

        labels = mapping.get("labels") or []

        map_rows.append(
            {
                "provider": mapping.get("provider") or "",
                "labels": ", ".join(
                    str(label) for label in labels
                ),
                "category": mapping.get("category") or "",
                "priority": str(
                    mapping.get("priority", 100)
                ),
                "override": (
                    "yes"
                    if mapping.get("override_policy")
                    else ""
                ),
            }
        )

    def _csv(values):
        return ", ".join(
            str(item)
            for item in (values or [])
            if isinstance(item, str) and item.strip()
        )

    rule_rows = []

    for rule in payload.get("organisation_rules") or []:
        if not isinstance(rule, dict):
            continue

        rule_rows.append(
            {
                "id": str(rule.get("id") or ""),
                "media_kind": str(
                    rule.get("media_kind") or "any"
                ),
                "certification": str(
                    rule.get("certification") or ""
                ),
                "collection": str(
                    rule.get("collection") or ""
                ),
                "genres": _csv(rule.get("genres")),
                "tags": _csv(rule.get("tags")),
                "provider": str(rule.get("provider") or ""),
                "category": str(rule.get("category") or ""),
                "fallback": (
                    "yes" if rule.get("fallback") else ""
                ),
            }
        )

    shown = (
        services.organisation_service.profile_root_rows(
            payload.get("roots")
        )
        if services is not None
        else {"rows": [], "tokens": ["{root}"]}
    )

    shown_rows = shown["rows"]
    shown_tokens = shown["tokens"] or ["{root}"]

    shown_sources = [
        entry if isinstance(entry, str) else str(
            entry.get("path") or ""
        )
        for entry in (payload.get("sources") or [])
    ]
    shown_sources = [
        path for path in shown_sources if path
    ]

    signal_rules = payload.get("intelligent_rules") or {}

    sig_rows = []
    for category in sorted(signal_rules):
        signals = signal_rules[category] or {}

        if not isinstance(signals, dict):
            continue

        sig_rows.append(
            {
                "category": str(category),
                "genres": ", ".join(
                    str(item)
                    for item in (
                        signals.get("genres") or []
                    )
                ),
                "collections": ", ".join(
                    str(item)
                    for item in (
                        signals.get("collections") or []
                    )
                ),
                "networks": ", ".join(
                    str(item)
                    for item in (
                        signals.get("networks") or []
                    )
                ),
                "provider_flags": ", ".join(
                    str(item)
                    for item in (
                        signals.get("provider_flags") or []
                    )
                ),
            }
        )

    cert_rows = []

    for rule in payload.get("certification_rules") or []:
        if not isinstance(rule, dict):
            continue

        cert_rows.append(
            {
                "certification": str(
                    rule.get("certification") or ""
                ),
                "media_kind": str(
                    rule.get("media_kind") or "any"
                ),
                "category": str(
                    rule.get("category") or ""
                ),
            }
        )

    coll_rows = []

    for rule in payload.get("collection_rules") or []:
        if not isinstance(rule, dict):
            continue

        coll_rows.append(
            {
                "collection": str(
                    rule.get("collection") or ""
                ),
                "category": str(
                    rule.get("category") or ""
                ),
            }
        )

    filename_stored = payload.get("filename_policy") or {}

    if isinstance(filename_stored, dict):
        stored_mode = str(
            filename_stored.get("mode") or "keep"
        )
        filename_policy = {
            "mode": stored_mode,
            "pattern": str(
                filename_stored.get("pattern") or ""
            ),
            "separator": str(
                filename_stored.get("separator") or " "
            ),
            "legacy_pattern": (
                str(filename_stored.get("pattern") or "")
                if stored_mode == "template"
                else ""
            ),
        }
    else:
        filename_policy = {
            "mode": "keep",
            "pattern": "",
            "separator": " ",
            "legacy_pattern": "",
        }

    return {
        "name": payload.get("name") or "",
        "origin_preset": (
            (payload.get("origin") or {}).get("preset") or ""
            if isinstance(payload.get("origin"), dict)
            else ""
        ),
        "sig_rows": sig_rows,
        "cert_rows": cert_rows,
        "coll_rows": coll_rows,
        "rule_rows": rule_rows,
        "filename_policy": filename_policy,
        "filename_example": (
            _filename_example(services, filename_policy)
            if services is not None
            else {}
        ),
        "roots": "\n".join(
            row["path"] for row in shown_rows
        ),
        "root_rows": shown_rows,
        "root_tokens": shown_tokens,
        "source_rows": shown_sources,
        "movie_template": _pattern("movie"),
        "tv_template": _pattern("tv"),
        "category_template": _pattern("category"),
        "tag_mappings": "",
        "categories": "",
        "cat_rows": [
            {"name": name, "folder": folder}
            for name, folder in categories.items()
        ],
        "map_rows": map_rows,
        "naming_separator": naming.get("separator", " "),
        "collision_policy": (
            payload.get("collision_policy") or "review"
        ),
        "platform": payload.get("platform") or "posix",
        "provider_priority": ", ".join(
            payload.get("provider_priority") or []
        ),
    }


def _input_to_payload_candidate(
    input_view, builtins=None, services=None
):
    """
    Rebuild a candidate payload from editor input.
    Built-in template patterns come from the caller
    (already fetched through the service boundary).
    """
    """
    Rebuild a profile payload from editor input for
    guided-completion checks. Mirrors the save path
    assembly without saving anything; unparseable
    mapping rows are skipped here (the save path
    reports them) but flagged through a synthetic
    problem carried on the candidate.
    """

    entered = input_view or {}
    problems = []

    raw_rows = entered.get("root_rows") or []
    roots = []

    for row in raw_rows:
        if isinstance(row, dict):
            path = str(row.get("path") or "").strip()
            alias = str(row.get("alias") or "").strip()

            if path or alias:
                roots.append({"path": path, "alias": alias})
        elif str(row).strip():
            roots.append(str(row).strip())

    raw_sources = entered.get("source_rows") or []
    sources = []

    for row in raw_sources:
        if isinstance(row, dict):
            path = str(row.get("path") or "").strip()
        else:
            path = str(row or "").strip()

        if path and path not in sources:
            sources.append(path)

    cat_rows = entered.get("cat_rows") or []
    categories = {}

    for row in cat_rows:
        if not isinstance(row, dict):
            continue

        label = str(row.get("name") or "").strip()
        folder = str(row.get("folder") or "").strip()

        if not label and not folder:
            continue

        if label and folder and label not in categories:
            categories[label] = folder

    mappings = []

    for index, row in enumerate(
        entered.get("map_rows") or []
    ):
        if not isinstance(row, dict):
            continue

        labels = [
            part.strip()
            for part in str(
                row.get("labels") or ""
            ).split(",")
            if part.strip()
        ]
        category = str(row.get("category") or "").strip()
        provider = str(row.get("provider") or "").strip()

        if not labels and not category and not provider:
            continue

        try:
            priority = int(
                str(row.get("priority") or "100").strip()
                or "100"
            )
        except (TypeError, ValueError):
            problems.append(
                f"tag mapping #{index} priority must be "
                f"an integer"
            )
            continue

        mappings.append(
            {
                "id": f"candidate-{index}",
                "provider": provider or None,
                "labels": labels,
                "category": category,
                "priority": priority,
                "override_policy": bool(
                    str(
                        row.get("override") or ""
                    ).strip().lower()
                    in ("yes", "true", "1", "on")
                ),
            }
        )

    builtins = builtins or {}

    builtin_fallback = {
        "movie": ("Basic Movies", "movie"),
        "tv": ("Basic TV", "tv"),
        "category": ("Basic Category", "category"),
    }

    def _template(key, kind):
        pattern = str(
            entered.get(f"{key}_template") or ""
        ).strip()

        if not pattern:
            fallback_name, _ = builtin_fallback.get(
                key, ("", kind)
            )
            builtin = builtins.get(fallback_name) or {}
            pattern = builtin.get("pattern", "")

        return {"kind": kind, "pattern": pattern}

    signal_rules = {}

    for row in entered.get("sig_rows") or []:
        if not isinstance(row, dict):
            continue

        category = str(row.get("category") or "").strip()

        if not category or category in signal_rules:
            continue

        signals = {}

        for key, field in (
            ("genres", "genres"),
            ("collections", "collections"),
            ("networks", "networks"),
            ("provider_flags", "provider_flags"),
        ):
            parts = [
                part.strip()
                for part in str(
                    row.get(field) or ""
                ).split(",")
                if part.strip()
            ]

            if parts:
                signals[key] = parts

        if signals:
            signal_rules[category] = signals

    organisation_rules = []
    seen_rule_ids = set()

    for index, row in enumerate(
        entered.get("rule_rows") or []
    ):
        if not isinstance(row, dict):
            continue

        rule_id = str(row.get("id") or "").strip()
        kind = str(
            row.get("media_kind") or "any"
        ).strip().casefold()
        cert = str(
            row.get("certification") or ""
        ).strip().upper()
        collection = str(
            row.get("collection") or ""
        ).strip()
        genres = [
            part.strip()
            for part in str(row.get("genres") or "").split(",")
            if part.strip()
        ]
        tags = [
            part.strip()
            for part in str(row.get("tags") or "").split(",")
            if part.strip()
        ]
        provider = str(row.get("provider") or "").strip()
        rule_category = str(
            row.get("category") or ""
        ).strip()
        fallback = str(
            row.get("fallback") or ""
        ).strip().lower() in ("yes", "true", "1", "on")

        if (
            not rule_id
            and not cert
            and not collection
            and not genres
            and not tags
            and not rule_category
            and not provider
        ):
            continue

        if not rule_id:
            rule_id = f"rule-{index}"

        if rule_id in seen_rule_ids:
            problems.append(
                f"organisation rule #{index} duplicates "
                f"rule id '{rule_id}'"
            )
            continue

        seen_rule_ids.add(rule_id)

        if kind in ("movies",):
            kind = "movie"
        elif kind in ("series", "show", "shows"):
            kind = "tv"
        elif kind not in ("movie", "tv", "any"):
            kind = "any"

        rule = {
            "id": rule_id,
            "media_kind": kind,
            "category": rule_category,
        }

        if cert:
            rule["certification"] = cert

        if collection:
            rule["collection"] = collection

        if genres:
            rule["genres"] = genres

        if tags:
            rule["tags"] = tags

        if provider:
            rule["provider"] = provider

        if fallback:
            rule["fallback"] = True

        organisation_rules.append(rule)

    filename_policy = {"mode": "keep"}
    filename_entered = entered.get("filename_policy") or {}

    if isinstance(filename_entered, dict):
        try:
            if services is None:
                raise ValueError(
                    "filename policy cannot be checked"
                )

            legacy = str(
                filename_entered.get("legacy_pattern") or ""
            ).strip()

            if (
                filename_entered.get("mode") == "template"
                or legacy
            ) and not str(
                filename_entered.get("pattern") or ""
            ).strip():
                filename_policy = (
                    services.organisation_service
                    .normalise_filename_policy(
                        {"mode": "template", "pattern": legacy}
                    )
                )
            else:
                filename_policy = (
                    services.organisation_service
                    .normalise_filename_policy(
                        {
                            "mode": filename_entered.get(
                                "mode"
                            ),
                            "pattern": filename_entered.get(
                                "pattern"
                            ),
                            "separator": filename_entered.get(
                                "separator"
                            ),
                        }
                    )
                )
        except ValueError as error:
            problems.append(str(error))
            filename_policy = {"mode": "keep"}

    certification_rules = []

    for index, row in enumerate(
        entered.get("cert_rows") or []
    ):
        if not isinstance(row, dict):
            continue

        cert = str(
            row.get("certification") or ""
        ).strip().upper()
        kind = str(
            row.get("media_kind") or "any"
        ).strip().casefold()
        category = str(row.get("category") or "").strip()

        if not cert and not category and kind in (
            "", "any",
        ):
            continue

        if kind in ("movies", "movie"):
            kind = "movie"
        elif kind in ("tv", "series", "show", "shows"):
            kind = "tv"
        else:
            kind = "any"

        if (cert and category) or problems is not None:
            if cert and category:
                certification_rules.append(
                    {
                        "id": f"cert-{index}",
                        "certification": cert,
                        "media_kind": kind,
                        "category": category,
                    }
                )
            else:
                problems.append(
                    f"certification rule #{index} needs "
                    f"both a rating and a target category"
                )

    collection_rules = []

    for index, row in enumerate(
        entered.get("coll_rows") or []
    ):
        if not isinstance(row, dict):
            continue

        collection = str(
            row.get("collection") or ""
        ).strip()
        category = str(row.get("category") or "").strip()

        if not collection and not category:
            continue

        if collection and category:
            collection_rules.append(
                {
                    "id": f"coll-{index}",
                    "collection": collection,
                    "category": category,
                }
            )
        else:
            problems.append(
                f"collection rule #{index} needs both a "
                f"collection name and a target category"
            )

    candidate = {
        "name": str(entered.get("name") or ""),
        "roots": roots,
        "sources": sources,
        "movie_template": "movie",
        "tv_template": "tv",
        "category_template": "category",
        "templates": {
            "movie": _template("movie", "movie"),
            "tv": _template("tv", "tv"),
            "category": _template("category", "category"),
        },
        "categories": categories,
        "intelligent_rules": signal_rules,
        "organisation_rules": organisation_rules,
        "certification_rules": certification_rules,
        "collection_rules": collection_rules,
        "filename_policy": filename_policy,
        "tag_mappings": mappings,
        "naming": {
            "separator": str(
                entered.get("naming_separator", " ")
            ),
            "case": "preserve",
        },
        "collision_policy": str(
            entered.get("collision_policy") or "review"
        ),
        "origin": (
            {"preset": entered["origin_preset"]}
            if entered.get("origin_preset")
            else None
        ),
        "provider_priority": _candidate_priority(
            services, entered.get("provider_priority"), problems
        ),
        "platform": str(
            entered.get("platform") or "posix"
        ),
    }

    return candidate, problems


def organisation_profile_preset_data(services, body):
    """
    Load one built-in preset into the profile editor:
    pre-fill every field the preset determines and let
    the operator complete library-specific values,
    then save as a new profile through the normal
    save path. The preset itself is never mutated
    and never saved directly.
    """

    raw_key = None

    if isinstance(body, dict):
        raw_key = (body.get("preset") or [None])[0]

    key = str(raw_key or "").strip()

    preset = (
        services.organisation_service.get_profile_preset(
            key
        )
    )

    if preset is None:
        raise ValueError(
            f"unknown profile preset '{key}'"
        )

    payload = dict(preset.get("payload") or {})
    entered = _preset_to_input(payload, services)
    entered["origin_preset"] = key
    candidate, _ = _input_to_payload_candidate(
        entered,
        services.organisation_service.builtin_templates(),
        services,
    )

    return {
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "builtins": (
            services.organisation_service.builtin_templates()
        ),
        "presets": (
            services.organisation_service
            .list_profile_presets()
        ),
        "preset_loaded": preset.get("name"),
        "saved": None,
        "errors": [],
        "input": entered,
        "completion": (
            services.organisation_service.profile_completion(
                candidate
            )
        ),
        "refreshed_at": now_timestamp(),
    }


def _profile_preview_values():
    return {
        "Title": "Example Movie",
        "Year": "2024",
        "Series": "Example Show",
        "Season": "01",
        "Category": "Movies",
        "TitleOrSeries": "Example Movie",
    }


def organisation_profile_detail_data(services, profile_id):
    """
    One saved profile with its full payload, digest, and
    a live structural preview of every built-in template
    rendered over sample values.
    """

    try:
        profile = services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    builtins = (
        services.organisation_service.builtin_templates()
    )

    values = _profile_preview_values()

    previews = []

    for name, template in builtins.items():
        rendered = services.organisation_service.render_preview(
            dict(template),
            dict(values),
            root="/library",
        )

        previews.append(
            {
                "name": name,
                "kind": template.get("kind"),
                "pattern": template.get("pattern"),
                "destination": rendered.get("destination"),
                "error": rendered.get("error"),
            }
        )

    root_rows = (
        services.organisation_service.profile_root_rows(
            (profile.get("payload") or {}).get("roots")
        )
    )

    edit_input = _preset_to_input(
        dict(profile.get("payload") or {}), services
    )
    edit_completion = _profiles_form_extras(
        services, edit_input
    )["completion"]

    return {
        "profile": profile,
        "problems": [],
        "previews": previews,
        "root_rows": root_rows,
        "edit": {
            "input": edit_input,
            "completion": edit_completion,
            "errors": [],
            "saved": None,
        },
        "refreshed_at": now_timestamp(),
    }


def organisation_profile_update_data(
    services, body, profile_id
):
    """
    Save Changes for one saved user profile: every
    editable field at once (including an optional
    rename, still unique) through the single update
    path. The stored configuration is updated in
    place; the profile keeps its identity and no new
    profile is created. Invalid input re-renders the
    same detail editor with input preserved.
    """

    try:
        record = services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    result = organisation_profile_save_data(
        services,
        dict(body or {}),
        update_id=int(record.get("id")),
    )

    saved = result.get("saved") or {}

    # Render the updated profile, not a stale row.
    detail = organisation_profile_detail_data(
        services, saved.get("id") or profile_id
    )

    detail["saved"] = result.get("saved")
    detail["errors"] = result.get("errors") or []

    if result.get("errors"):
        preserved = result.get("input") or {}
        detail["edit"] = {
            "input": preserved,
            "completion": _profiles_form_extras(
                services, preserved
            )["completion"],
            "errors": result.get("errors") or [],
            "error_sections": result.get("error_sections")
            or [],
            "saved": None,
        }

    return detail


def organisation_profile_autofill_data(
    services, body, profile_id
):
    """
    Suggest tag mappings from real observed provider
    tags. Suggestions merge into the detail editor as
    ordinary rows for operator review; nothing is
    saved until Save Changes. Optional: standard
    presets already work without it.
    """

    try:
        record = services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    payload = dict(record.get("payload") or {})

    suggested = (
        services.organisation_service.recommend_tag_mappings(
            payload
        )
    )

    detail = organisation_profile_detail_data(
        services, profile_id
    )

    edit_input = dict((detail.get("edit") or {}).get(
        "input") or {})

    existing_rows = list(edit_input.get("map_rows") or [])

    covered = {
        (
            str(row.get("provider") or "").strip().lower(),
            tuple(
                sorted(
                    part.strip().lower()
                    for part in str(
                        row.get("labels") or ""
                    ).split(",")
                    if part.strip()
                ),
            ),
        )
        for row in existing_rows
        if isinstance(row, dict)
    }

    added = 0

    for suggestion in suggested.get("suggestions") or []:
        key = (
            str(suggestion.get("provider") or "").lower(),
            tuple(
                sorted(
                    label.strip().lower()
                    for label in (
                        suggestion.get("labels") or []
                    )
                ),
            ),
        )

        if key in covered:
            continue

        covered.add(key)
        added += 1
        existing_rows.append(
            {
                "provider": suggestion.get("provider") or "",
                "labels": ", ".join(
                    suggestion.get("labels") or []
                ),
                "category": suggestion.get("category") or "",
                "priority": str(
                    suggestion.get("priority", 100)
                ),
            }
        )

    edit_input["map_rows"] = existing_rows
    detail["edit"] = {
        "input": edit_input,
        "completion": _profiles_form_extras(
            services, edit_input
        )["completion"],
        "errors": [],
        "saved": None,
    }
    detail["autofill"] = {
        "message": (
            f"{added} recommended tag rule(s) added "
            f"below for review from real observed "
            f"provider tags. Save Changes to keep them, "
            f"or edit/remove them first."
            if added
            else "No new tag recommendations: every "
            "observed provider tag is already covered "
            "by this profile."
        ),
    }

    return detail


def organisation_profile_delete_data(
    services, body, profile_id
):
    """
    Delete exactly one user-created profile by id
    with explicit confirmation. Built-in presets are
    never stored rows and cannot be reached here.
    Returns to the list data with a success notice
    on completion.
    """

    confirmed = False

    if isinstance(body, dict):
        values = body.get("confirm") or []
        confirmed = any(
            str(value).strip().lower() in ("yes", "true", "1")
            for value in values
        )

    if not confirmed:
        detail = organisation_profile_detail_data(
            services, profile_id
        )
        detail["delete_confirm"] = True

        return detail

    try:
        removed = (
            services.organisation_service.delete_profile(
                int(profile_id)
            )
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    listing = organisation_profiles_data(services)
    listing["deleted"] = removed

    return listing


def organisation_profile_clone_data(services, profile_id):
    """
    Clone one saved profile into the create editor:
    the source configuration pre-fills the form
    under a suggested derived name the operator can
    still edit; nothing is stored until Save
    Profile. The source profile is never altered,
    and the clone is independent once saved.
    """

    try:
        source = services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    payload = dict(source.get("payload") or {})
    entered = _preset_to_input(payload, services)
    entered["name"] = (
        services.organisation_service.suggest_profile_name(
            source.get("name")
        )
    )
    entered["origin_preset"] = ""
    extras = _profiles_form_extras(services, entered)

    return {
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "builtins": (
            services.organisation_service.builtin_templates()
        ),
        "presets": extras["presets"],
        "preset_loaded": None,
        "cloned_from": source.get("name"),
        "saved": None,
        "errors": [],
        "error_sections": [],
        "input": entered,
        "completion": extras["completion"],
        "refreshed_at": now_timestamp(),
    }


def _optional_profile_id(body):
    raw = _form_value(body, "profile_id")

    if raw is None:
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("Invalid profile selection")


def _profile_detail_or_404(services, profile_id):
    try:
        return services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))


def _update_profile_or_404(services, profile_id, payload):
    try:
        return services.organisation_service.update_profile(
            int(profile_id), payload
        )
    except ValueError as error:
        raise _not_found_from(str(error))


def _save_profile_version_or_404(services, payload):
    raise NotImplementedError(
        "versioned profile saves were removed; "
        "use _update_profile_or_404"
    )


def _input_signal_rows(body):
    """Editor signal rows with input preserved verbatim."""

    if not isinstance(body, dict):
        return []

    categories = body.get("sig_category") or []
    genres = body.get("sig_genres") or []
    collections = body.get("sig_collections") or []
    networks = body.get("sig_networks") or []
    flags = body.get("sig_provider_flags") or []

    rows = []

    for index in range(
        max(
            len(categories),
            len(genres),
            len(collections),
            len(networks),
            len(flags),
            1,
        )
    ):
        row = {
            "category": (
                str(categories[index]).strip()
                if index < len(categories)
                else ""
            ),
            "genres": (
                str(genres[index]).strip()
                if index < len(genres)
                else ""
            ),
            "collections": (
                str(collections[index]).strip()
                if index < len(collections)
                else ""
            ),
            "networks": (
                str(networks[index]).strip()
                if index < len(networks)
                else ""
            ),
            "provider_flags": (
                str(flags[index]).strip()
                if index < len(flags)
                else ""
            ),
        }

        if any(row.values()):
            rows.append(row)

    return rows or [
        {
            "category": "",
            "genres": "",
            "collections": "",
            "networks": "",
            "provider_flags": "",
        }
    ]


def _candidate_priority(services, raw, problems):
    """
    Candidate priority for completion checks: invalid
    input becomes a synthetic completion problem
    instead of an exception.
    """

    if services is None:
        return None

    try:
        return _parse_priority_field(services, raw)
    except ValueError as error:
        problems.append(str(error))
        return None


def _parse_priority_field(services, raw):
    """
    Provider priority from the Advanced editor field
    through the organisation service (the web layer
    stays on the application boundary): blank means
    the default order, invalid input raises
    ValueError with guidance.
    """

    text = str(raw or "").strip()

    if not text:
        return None

    return (
        services.organisation_service.normalise_provider_priority(
            text
        )
    )


def _parse_signal_rows(body):
    """
    Structured intelligent-signal rows from the shared
    profile editor into the intelligent_rules mapping.
    Empty rows are skipped; rows naming no category are
    skipped the same way blank category rows are.
    """

    if not isinstance(body, dict):
        return {}

    categories = body.get("sig_category") or []
    genres = body.get("sig_genres") or []
    collections = body.get("sig_collections") or []
    networks = body.get("sig_networks") or []
    flags = body.get("sig_provider_flags") or []

    rules = {}

    for index in range(
        max(
            len(categories),
            len(genres),
            len(collections),
            len(networks),
            len(flags),
        )
    ):
        category = (
            str(categories[index]).strip()
            if index < len(categories)
            else ""
        )

        if not category:
            continue

        signals = {
            "genres": _split_csv_list(
                genres[index] if index < len(genres) else ""
            ),
            "collections": _split_csv_list(
                collections[index]
                if index < len(collections)
                else ""
            ),
            "networks": _split_csv_list(
                networks[index] if index < len(networks) else ""
            ),
            "provider_flags": _split_csv_list(
                flags[index] if index < len(flags) else ""
            ),
        }

        if any(signals.values()):
            rules[category] = signals

    return rules


def _parse_cert_rule_rows(body):
    """
    Structured certification-policy rows from the
    shared profile editor into certification_rules.
    Empty rows are skipped; the save path reports
    half-filled rows through validation.
    """

    if not isinstance(body, dict):
        return []

    certs = body.get("cert_cert") or []
    kinds = body.get("cert_kind") or []
    categories = body.get("cert_category") or []

    rules = []

    for index in range(
        max(len(certs), len(kinds), len(categories))
    ):
        cert = (
            str(certs[index]).strip().upper()
            if index < len(certs)
            else ""
        )
        kind = (
            str(kinds[index]).strip().casefold()
            if index < len(kinds)
            else "any"
        )
        category = (
            str(categories[index]).strip()
            if index < len(categories)
            else ""
        )

        if not cert and not category and kind in (
            "", "any",
        ):
            continue

        if kind in ("movies", "movie"):
            kind = "movie"
        elif kind in ("tv", "series", "show", "shows"):
            kind = "tv"
        else:
            kind = "any"

        rules.append(
            {
                "id": f"cert-{len(rules)}",
                "certification": cert,
                "media_kind": kind,
                "category": category,
            }
        )

    return rules


def _parse_collection_rule_rows(body):
    """
    Structured collection-policy rows from the shared
    profile editor into collection_rules. Empty rows
    are skipped.
    """

    if not isinstance(body, dict):
        return []

    names = body.get("coll_collection") or []
    categories = body.get("coll_category") or []

    rules = []

    for index in range(max(len(names), len(categories))):
        collection = (
            str(names[index]).strip()
            if index < len(names)
            else ""
        )
        category = (
            str(categories[index]).strip()
            if index < len(categories)
            else ""
        )

        if not collection and not category:
            continue

        rules.append(
            {
                "id": f"coll-{len(rules)}",
                "collection": collection,
                "category": category,
            }
        )

    return rules


def _input_cert_rows(body):
    """Editor certification rows with input preserved."""

    if not isinstance(body, dict):
        return []

    certs = body.get("cert_cert") or []
    kinds = body.get("cert_kind") or []
    categories = body.get("cert_category") or []

    rows = []

    for index in range(
        max(len(certs), len(kinds), len(categories), 1)
    ):
        row = {
            "certification": (
                str(certs[index]).strip()
                if index < len(certs)
                else ""
            ),
            "media_kind": (
                str(kinds[index]).strip()
                if index < len(kinds)
                else "any"
            ),
            "category": (
                str(categories[index]).strip()
                if index < len(categories)
                else ""
            ),
        }

        if (
            row["certification"]
            or row["category"]
            or row["media_kind"] not in ("", "any")
        ):
            rows.append(row)

    return rows or [
        {"certification": "", "media_kind": "any",
         "category": ""}
    ]


def _input_coll_rows(body):
    """Editor collection rows with input preserved."""

    if not isinstance(body, dict):
        return []

    names = body.get("coll_collection") or []
    categories = body.get("coll_category") or []

    rows = []

    for index in range(max(len(names), len(categories), 1)):
        row = {
            "collection": (
                str(names[index]).strip()
                if index < len(names)
                else ""
            ),
            "category": (
                str(categories[index]).strip()
                if index < len(categories)
                else ""
            ),
        }

        if row["collection"] or row["category"]:
            rows.append(row)

    return rows or [{"collection": "", "category": ""}]


def _split_csv_list(raw):
    return [
        part.strip()
        for part in str(raw or "").split(",")
        if part.strip()
    ]


def organisation_profile_signal_save_data(
    services, body, profile_id
):
    """
    Structured edit of one intelligent-classification
    signal set: merges comma-separated genre, collection,
    network/studio and provider-flag signals into the
    profile's intelligent_rules for one category, then
    updates the stored profile in place.
    No raw JSON required.
    """

    try:
        source = services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    category = (_form_value(body, "signal_category") or "").strip()

    if not category:
        raise ValueError(
            "A category name is required for the signal set"
        )

    signals = {
        "genres": _split_csv_list(
            _form_value(body, "signal_genres")
        ),
        "collections": _split_csv_list(
            _form_value(body, "signal_collections")
        ),
        "networks": _split_csv_list(
            _form_value(body, "signal_networks")
        ),
        "provider_flags": _split_csv_list(
            _form_value(body, "signal_provider_flags")
        ),
    }

    if not any(signals.values()):
        raise ValueError(
            "At least one genre, collection, network or "
            "provider flag is required"
        )

    payload = dict(source.get("payload") or {})
    rules = dict(payload.get("intelligent_rules") or {})
    rules[category] = signals
    payload["intelligent_rules"] = rules

    try:
        services.organisation_service.update_profile(
            int(profile_id), payload
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return organisation_profile_detail_data(
        services, profile_id
    )


def organisation_profile_category_add_data(
    services, body, profile_id
):
    """
    Structured addition of one category folder mapping,
    updating the stored profile in place.
    No name = folder lines required.
    """

    source = _profile_detail_or_404(services, profile_id)

    label = (_form_value(body, "category_name") or "").strip()
    folder = (
        _form_value(body, "category_folder") or ""
    ).strip()

    if not label or not folder:
        raise ValueError(
            "Both a category name and a folder are required"
        )

    payload = dict(source.get("payload") or {})
    categories = dict(payload.get("categories") or {})

    if label in categories:
        raise ValueError(
            f"category '{label}' is already defined"
        )

    categories[label] = folder
    payload["categories"] = categories

    saved = _update_profile_or_404(
        services, profile_id, payload
    )

    return organisation_profile_detail_data(
        services, saved["id"]
    )


def organisation_profile_category_remove_data(
    services, body, profile_id
):
    """
    Remove one category folder mapping, updating the
    stored profile in place.
    """

    source = _profile_detail_or_404(services, profile_id)

    label = (_form_value(body, "category_name") or "").strip()

    if not label:
        raise ValueError("A category name is required")

    payload = dict(source.get("payload") or {})
    categories = dict(payload.get("categories") or {})

    if label not in categories:
        raise ValueError(
            f"category '{label}' is not defined"
        )

    del categories[label]
    payload["categories"] = categories

    saved = _update_profile_or_404(
        services, profile_id, payload
    )

    return organisation_profile_detail_data(
        services, saved["id"]
    )


def organisation_profile_mapping_remove_data(
    services, body, profile_id
):
    """
    Remove one explicit tag mapping by id, updating
    the stored profile in place.
    """

    source = _profile_detail_or_404(services, profile_id)

    mapping_id = (
        _form_value(body, "mapping_id") or ""
    ).strip()

    if not mapping_id:
        raise ValueError("A mapping id is required")

    payload = dict(source.get("payload") or {})
    mappings = list(payload.get("tag_mappings") or [])

    kept = [
        mapping for mapping in mappings
        if not (
            isinstance(mapping, dict)
            and mapping.get("id") == mapping_id
        )
    ]

    if len(kept) == len(mappings):
        raise ValueError(
            f"tag mapping '{mapping_id}' was not found"
        )

    payload["tag_mappings"] = kept

    saved = _update_profile_or_404(
        services, profile_id, payload
    )

    return organisation_profile_detail_data(
        services, saved["id"]
    )


def organisation_profile_mapping_add_data(
    services, body, profile_id
):
    """
    Structured addition of one explicit tag mapping:
    provider scope, comma-separated tag labels, target
    category and priority. Appends to the profile's tag
    mappings and updates the stored profile in place.
    No raw JSON required.
    """

    try:
        source = services.organisation_service.get_profile(
            int(profile_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    payload = dict(source.get("payload") or {})
    mappings = list(payload.get("tag_mappings") or [])

    raw_provider = (
        _form_value(body, "mapping_provider") or ""
    ).strip().lower()

    provider = raw_provider or None

    if provider not in (None, "jellyfin", "radarr", "sonarr"):
        raise ValueError(
            "Provider scope must be any provider, "
            "jellyfin, radarr or sonarr"
        )

    labels = _split_csv_list(_form_value(body, "mapping_labels"))

    if not labels:
        raise ValueError(
            "At least one tag label is required"
        )

    category = (_form_value(body, "mapping_category") or "").strip()

    if not category:
        raise ValueError("A target category is required")

    raw_priority = (_form_value(body, "mapping_priority") or "").strip()

    try:
        priority = int(raw_priority) if raw_priority else 100
    except (TypeError, ValueError):
        raise ValueError("Priority must be an integer")

    existing_ids = {
        mapping.get("id")
        for mapping in mappings
        if isinstance(mapping, dict)
    }

    raw_id = (_form_value(body, "mapping_id") or "").strip()
    mapping_id = raw_id or f"m{len(mappings) + 1}"

    suffix = 1
    while mapping_id in existing_ids:
        suffix += 1
        mapping_id = f"{raw_id or f'm{len(mappings) + 1}'}-{suffix}"

    mappings.append(
        {
            "id": mapping_id,
            "provider": provider,
            "labels": labels,
            "category": category,
            "priority": priority,
        }
    )
    payload["tag_mappings"] = mappings

    try:
        saved = services.organisation_service.update_profile(
            int(profile_id), payload
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return organisation_profile_detail_data(
        services, saved["id"]
    )


def _form_values(body, name):
    """All submitted values for a repeated field, stripped."""

    if not isinstance(body, dict):
        return []

    return [
        str(value).strip()
        for value in (body.get(name) or [])
        if str(value).strip()
    ]


def _form_values_positional(body, name):
    """
    Submitted values for a repeated field with blanks
    preserved positionally (parallel arrays such as
    root paths and root aliases stay aligned).
    """

    if not isinstance(body, dict):
        return []

    return [
        str(value).strip() if value is not None else ""
        for value in (body.get(name) or [])
    ]


def _parse_filename_policy(body):
    """
    Filename policy from the File Naming editor
    section: keep / clean / extended / legacy
    custom template. Empty means keep (today's
    behaviour).
    """

    if not isinstance(body, dict):
        return {"mode": "keep"}

    mode = str(
        (body.get("filename_mode") or ["keep"])[0]
    ).strip().casefold()
    pattern = str(
        (body.get("filename_extended") or [""])[0]
    ).strip()
    separator = str(
        (body.get("filename_separator") or [" "])[0]
    )

    # An explicit extended pattern selects extended
    # mode even if the radio state is stale; a legacy
    # custom pattern preserves older template-mode
    # profiles; otherwise the radio selects
    # keep/clean/extended and anything unknown falls
    # back to keep (safe default).
    if pattern:
        return {
            "mode": "extended",
            "pattern": pattern,
            "separator": separator or " ",
        }

    legacy = str(
        (body.get("filename_legacy_pattern") or [""])[0]
    ).strip()

    if legacy:
        return {"mode": "template", "pattern": legacy}

    if mode == "clean":
        return {"mode": "clean"}

    if mode == "extended":
        return {
            "mode": "extended",
            "separator": separator or " ",
        }

    return {"mode": "keep"}


def _input_filename_policy(body):
    """Editor filename inputs with input preserved."""

    if not isinstance(body, dict):
        return {"mode": "keep", "pattern": "", "separator": " "}

    mode = str(
        (body.get("filename_mode") or ["keep"])[0]
    ).strip().casefold()
    pattern = str(
        (body.get("filename_extended") or [""])[0]
    )
    separator = str(
        (body.get("filename_separator") or [" "])[0]
    ) or " "
    legacy = str(
        (body.get("filename_legacy_pattern") or [""])[0]
    )

    if pattern.strip():
        mode = "extended"
    elif legacy.strip():
        return {
            "mode": "template",
            "pattern": legacy.strip(),
            "separator": separator,
        }
    elif mode not in ("keep", "clean", "extended"):
        mode = "keep"

    return {
        "mode": mode,
        "pattern": pattern,
        "separator": separator,
        "legacy_pattern": legacy,
    }


def _error_sections(errors) -> list:
    """
    Editor section keys implicated by save errors so
    the form can highlight the affected sections.
    Pure presentation mapping over human-readable
    messages.
    """

    sections = []

    for error in errors or []:
        text = str(error).lower()

        if "profile name" in text or "naming" in text:
            key = "profile"
        elif "organisation rule" in text:
            key = "rules"
        elif "library source" in text or "source location" in text:
            key = "sources"
        elif (
            "organisation destination" in text
            or "organisation root" in text
            or "root alias" in text
            or "root tag" in text
            or "destination tag" in text
        ):
            key = "destinations"
        elif "folder structure" in text:
            key = "structure"
        elif "filename" in text:
            key = "naming-file"
        elif "categor" in text:
            key = "categories"
        elif "certification" in text or "rating" in text:
            key = "ratings"
        elif "collection" in text:
            key = "collections"
        elif "tag mapping" in text or "tag row" in text:
            key = "tags"
        elif "provider" in text or "priority" in text:
            key = "advanced"
        elif "collision" in text or "platform" in text:
            key = "profile"
        else:
            key = "profile"

        if key not in sections:
            sections.append(key)

    return sections


def organisation_profile_save_data(services, body, update_id=None):
    """
    Validate and store an organisation profile from
    the settings form: create a new profile, or when
    update_id names a stored profile, update it in
    place (rename allowed, still unique). Structured
    repeat rows (roots, category folders, tag
    mappings, rating/collection rules) merge with
    the legacy advanced text fields; invalid input
    returns errors with the submitted input
    preserved; nothing is saved.
    """

    name = _form_value(body, "name") or ""

    raw_roots = None

    if isinstance(body, dict):
        raw_roots = (body.get("roots") or [None])[0]

    roots = [
        line.strip()
        for line in str(raw_roots or "").splitlines()
        if line.strip()
    ]

    root_rows = _form_values(body, "root")
    root_aliases = _form_values_positional(body, "root_alias")

    for index, row in enumerate(root_rows):
        path = str(row or "").strip()
        alias = str(
            root_aliases[index]
            if index < len(root_aliases)
            else ""
        ).strip()

        if not path and not alias:
            continue

        entry = {"path": path, "alias": alias}

        if entry not in roots:
            roots.append(entry)

    builtins = (
        services.organisation_service.builtin_templates()
    )

    builtin_list = list(builtins.values())

    movie_builtin = builtin_list[0] if builtin_list else {}
    tv_builtin = (
        builtin_list[1] if len(builtin_list) > 1 else {}
    )
    category_builtin = (
        builtin_list[2] if len(builtin_list) > 2 else {}
    )

    movie_pattern = _form_value(body, "movie_template")
    tv_pattern = _form_value(body, "tv_template")
    category_pattern = _form_value(body, "category_template")

    templates = {
        "movie": {
            "kind": movie_builtin.get("kind", "movie"),
            "pattern": (
                movie_pattern
                or movie_builtin.get("pattern", "")
            ),
        },
        "tv": {
            "kind": tv_builtin.get("kind", "tv"),
            "pattern": (
                tv_pattern or tv_builtin.get("pattern", "")
            ),
        },
        "category": {
            "kind": category_builtin.get(
                "kind", "category"
            ),
            "pattern": (
                category_pattern
                or category_builtin.get("pattern", "")
            ),
        },
    }

    raw_mappings = None

    if isinstance(body, dict):
        raw_mappings = (body.get("tag_mappings") or [None])[0]

    raw_mappings_text = str(raw_mappings or "").strip()

    raw_categories = None

    if isinstance(body, dict):
        raw_categories = (body.get("categories") or [None])[0]

    raw_categories_text = str(raw_categories or "").strip()

    categories = {}
    category_errors = []

    def _add_category(label, folder, where):
        if not label or not folder:
            category_errors.append(
                f"{where} needs both a category name "
                f"and a folder"
            )
            return

        if label in categories:
            category_errors.append(
                f"category '{label}' is defined twice"
            )
            return

        categories[label] = folder

    if isinstance(body, dict):
        cat_names = body.get("cat_name") or []
        cat_folders = body.get("cat_folder") or []

        for index, (raw_name, raw_folder) in enumerate(
            zip(cat_names, cat_folders), start=1
        ):
            label = str(raw_name or "").strip()
            folder = str(raw_folder or "").strip()

            if not label and not folder:
                continue

            _add_category(
                label, folder, f"category row {index}"
            )

    for lineno, line in enumerate(
        raw_categories_text.splitlines(), start=1
    ):
        text = line.strip()

        if not text:
            continue

        if "=" not in text:
            category_errors.append(
                f"category line {lineno} must look like "
                f"'name = folder'"
            )
            continue

        name_part, _, folder_part = text.partition("=")

        _add_category(
            name_part.strip(),
            folder_part.strip(),
            f"category line {lineno}",
        )

    def _input_view():
        map_names = (
            body.get("map_provider") or []
            if isinstance(body, dict) else []
        )
        map_labels = (
            body.get("map_labels") or []
            if isinstance(body, dict) else []
        )
        map_categories = (
            body.get("map_category") or []
            if isinstance(body, dict) else []
        )
        map_priorities = (
            body.get("map_priority") or []
            if isinstance(body, dict) else []
        )
        map_overrides = (
            body.get("map_override") or []
            if isinstance(body, dict) else []
        )

        map_rows = []

        for index in range(
            max(
                len(map_names),
                len(map_labels),
                len(map_categories),
                len(map_priorities),
                len(map_overrides),
            )
        ):
            row = {
                "provider": (
                    str(map_names[index])
                    if index < len(map_names) else ""
                ),
                "labels": (
                    str(map_labels[index])
                    if index < len(map_labels) else ""
                ),
                "category": (
                    str(map_categories[index])
                    if index < len(map_categories)
                    else ""
                ),
                "priority": (
                    str(map_priorities[index])
                    if index < len(map_priorities)
                    else "100"
                ),
                "override": (
                    str(map_overrides[index])
                    if index < len(map_overrides)
                    else ""
                ),
            }

            if (
                row["labels"].strip()
                or row["category"].strip()
                or row["provider"].strip()
            ):
                map_rows.append(row)

        def _rule_list(name):
            return (
                body.get(name) or []
                if isinstance(body, dict) else []
            )

        rule_ids = _rule_list("rule_id")
        rule_kinds = _rule_list("rule_kind")
        rule_certs = _rule_list("rule_cert")
        rule_colls = _rule_list("rule_collection")
        rule_genres = _rule_list("rule_genres")
        rule_tags = _rule_list("rule_tags")
        rule_providers = _rule_list("rule_provider")
        rule_categories = _rule_list("rule_category")
        rule_fallbacks = _rule_list("rule_fallback")

        rule_rows = []

        for index in range(
            max(
                len(rule_ids),
                len(rule_kinds),
                len(rule_certs),
                len(rule_colls),
                len(rule_genres),
                len(rule_tags),
                len(rule_providers),
                len(rule_categories),
                len(rule_fallbacks),
                1,
            )
        ):
            def _at(values):
                return (
                    str(values[index]).strip()
                    if index < len(values)
                    else ""
                )

            row = {
                "id": _at(rule_ids),
                "media_kind": _at(rule_kinds) or "any",
                "certification": _at(rule_certs),
                "collection": _at(rule_colls),
                "genres": _at(rule_genres),
                "tags": _at(rule_tags),
                "provider": _at(rule_providers),
                "category": _at(rule_categories),
                "fallback": _at(rule_fallbacks),
            }

            if (
                row["id"]
                or row["certification"]
                or row["collection"]
                or row["genres"]
                or row["tags"]
                or row["category"]
                or row["provider"]
            ):
                rule_rows.append(row)

        if not rule_rows:
            rule_rows = [
                {
                    "id": "",
                    "media_kind": "any",
                    "certification": "",
                    "collection": "",
                    "genres": "",
                    "tags": "",
                    "provider": "",
                    "category": "",
                    "fallback": "",
                }
            ]

        cat_names_in = (
            body.get("cat_name") or []
            if isinstance(body, dict) else []
        )
        cat_folders_in = (
            body.get("cat_folder") or []
            if isinstance(body, dict) else []
        )

        cat_rows = []

        for index in range(
            max(len(cat_names_in), len(cat_folders_in))
        ):
            cat_rows.append(
                {
                    "name": (
                        str(cat_names_in[index])
                        if index < len(cat_names_in)
                        else ""
                    ),
                    "folder": (
                        str(cat_folders_in[index])
                        if index < len(cat_folders_in)
                        else ""
                    ),
                }
            )

        root_aliases_in = _form_values_positional(
            body, "root_alias"
        )

        root_rows_in = []

        for index in range(
            max(len(root_rows), len(root_aliases_in))
        ):
            path = str(
                root_rows[index]
                if index < len(root_rows)
                else ""
            ).strip()
            alias = str(
                root_aliases_in[index]
                if index < len(root_aliases_in)
                else ""
            ).strip()

            if path or alias:
                root_rows_in.append(
                    {"path": path, "alias": alias}
                )

        shown_aliases = (
            services.organisation_service.profile_root_rows(
                root_rows_in
            )["tokens"]
            or ["{root}"]
        )

        source_rows_in = [
            value
            for value in _form_values(body, "source")
            if value
        ]

        return {
            "name": name,
            "roots": "\n".join(
                entry.get("path", "")
                if isinstance(entry, dict)
                else str(entry)
                for entry in roots
            ),
            "root_tokens": shown_aliases,
            "root_rows": (
                root_rows_in or [
                    {"path": line.strip(), "alias": ""}
                    for line in str(
                        raw_roots or ""
                    ).splitlines()
                    if line.strip()
                ]
            ),
            "source_rows": source_rows_in,
            "movie_template": templates["movie"]["pattern"],
            "tv_template": templates["tv"]["pattern"],
            "category_template": (
                templates["category"]["pattern"]
            ),
            "tag_mappings": raw_mappings_text,
            "categories": raw_categories_text,
            "cat_rows": cat_rows,
            "map_rows": map_rows,
            "rule_rows": rule_rows,
            "sig_rows": _input_signal_rows(body),
            "cert_rows": _input_cert_rows(body),
            "coll_rows": _input_coll_rows(body),
            "filename_policy": _input_filename_policy(body),
            "filename_example": _filename_example(
                services,
                _input_filename_policy(body),
            ),
            "naming_separator": (
                _form_value(body, "naming_separator") or " "
            ),
            "collision_policy": (
                _form_value(body, "collision_policy")
                or "review"
            ),
            "platform": (
                _form_value(body, "platform") or "posix"
            ),
            "provider_priority": (
                _form_value(body, "provider_priority") or ""
            ),
            "origin_preset": (
                _form_value(body, "origin_preset") or ""
            ),
        }

    if category_errors:
        cat_input = _input_view()
        cat_extras = _profiles_form_extras(
            services, cat_input
        )

        return {
            "saved": None,
            "errors": category_errors,
            "error_sections": _error_sections(
                category_errors
            ),
            "input": cat_input,
            "profiles": (
                services.organisation_service
                .list_profiles()
            ),
            "builtins": builtins,
            "presets": cat_extras["presets"],
            "completion": cat_extras["completion"],
            "refreshed_at": now_timestamp(),
        }

    input_view = _input_view()

    extras = _profiles_form_extras(services, input_view)

    import json as _json

    if not raw_mappings_text:
        mappings = []
    else:
        try:
            mappings = _json.loads(raw_mappings_text)
        except ValueError:
            return {
                "saved": None,
                "errors": [
                    "tag mappings must be valid JSON text"
                ],
                "error_sections": ["tags"],
                "input": input_view,
                "profiles": (
                    services.organisation_service
                    .list_profiles()
                ),
                "builtins": builtins,
                "presets": extras["presets"],
                "completion": extras["completion"],
                "refreshed_at": now_timestamp(),
            }

    structured_rows = []

    if isinstance(body, dict):
        row_providers = body.get("map_provider") or []
        row_labels = body.get("map_labels") or []
        row_categories = body.get("map_category") or []
        row_priorities = body.get("map_priority") or []
        row_overrides = body.get("map_override") or []

        for index in range(
            max(
                len(row_providers),
                len(row_labels),
                len(row_categories),
                len(row_priorities),
                len(row_overrides),
            )
        ):
            provider_raw = (
                str(row_providers[index]).strip().lower()
                if index < len(row_providers) else ""
            )
            labels_raw = (
                str(row_labels[index])
                if index < len(row_labels) else ""
            )
            category_raw = (
                str(row_categories[index]).strip()
                if index < len(row_categories) else ""
            )
            priority_raw = (
                str(row_priorities[index]).strip()
                if index < len(row_priorities) else ""
            )
            override_raw = (
                str(row_overrides[index]).strip().lower()
                if index < len(row_overrides) else ""
            )

            labels = _split_csv_list(labels_raw)

            # Priority and override carry defaults even
            # on untouched rows, so they never count
            # as content: a blank Tags condition means
            # "do not use tags", not an error.
            if (
                not provider_raw
                and not labels
                and not category_raw
            ):
                continue

            if provider_raw not in (
                "", "jellyfin", "radarr", "sonarr"
            ):
                return {
                    "saved": None,
                    "errors": [
                        f"tag row {index + 1}: provider "
                        f"scope must be empty (any "
                        f"provider), jellyfin, radarr or "
                        f"sonarr"
                    ],
                    "error_sections": ["tags"],
                    "input": input_view,
                    "profiles": (
                        services.organisation_service
                        .list_profiles()
                    ),
                    "builtins": builtins,
                    "presets": extras["presets"],
                    "completion": extras["completion"],
                    "refreshed_at": now_timestamp(),
                }

            if not labels:
                return {
                    "saved": None,
                    "errors": [
                        f"tag row {index + 1}: at least "
                        f"one tag label is required"
                    ],
                    "error_sections": ["tags"],
                    "input": input_view,
                    "profiles": (
                        services.organisation_service
                        .list_profiles()
                    ),
                    "builtins": builtins,
                    "presets": extras["presets"],
                    "completion": extras["completion"],
                    "refreshed_at": now_timestamp(),
                }

            if not category_raw:
                return {
                    "saved": None,
                    "errors": [
                        f"tag row {index + 1}: a target "
                        f"category is required"
                    ],
                    "error_sections": ["tags"],
                    "input": input_view,
                    "profiles": (
                        services.organisation_service
                        .list_profiles()
                    ),
                    "builtins": builtins,
                    "presets": extras["presets"],
                    "completion": extras["completion"],
                    "refreshed_at": now_timestamp(),
                }

            try:
                priority = (
                    int(priority_raw) if priority_raw
                    else 100
                )
            except (TypeError, ValueError):
                return {
                    "saved": None,
                    "errors": [
                        f"tag row {index + 1}: priority "
                        f"must be a whole number"
                    ],
                    "error_sections": ["tags"],
                    "input": input_view,
                    "profiles": (
                        services.organisation_service
                        .list_profiles()
                    ),
                    "builtins": builtins,
                    "presets": extras["presets"],
                    "completion": extras["completion"],
                    "refreshed_at": now_timestamp(),
                }

            structured_rows.append(
                {
                    "id": f"m{len(mappings) + len(structured_rows) + 1}",
                    "provider": provider_raw or None,
                    "labels": labels,
                    "category": category_raw,
                    "priority": priority,
                    "override_policy": override_raw
                    in ("yes", "true", "1", "on"),
                }
            )

    mappings = list(mappings) + structured_rows

    organisation_rules = []

    for index, row in enumerate(
        input_view.get("rule_rows") or []
    ):
        if not isinstance(row, dict):
            continue

        rule_id = str(row.get("id") or "").strip()
        kind = str(
            row.get("media_kind") or "any"
        ).strip().casefold()
        cert = str(
            row.get("certification") or ""
        ).strip().upper()
        collection = str(
            row.get("collection") or ""
        ).strip()
        genres = [
            part.strip()
            for part in str(
                row.get("genres") or ""
            ).split(",")
            if part.strip()
        ]
        tags = [
            part.strip()
            for part in str(row.get("tags") or "").split(",")
            if part.strip()
        ]
        provider = str(row.get("provider") or "").strip()
        rule_category = str(
            row.get("category") or ""
        ).strip()
        fallback = str(
            row.get("fallback") or ""
        ).strip().lower() in ("yes", "true", "1", "on")

        if (
            not rule_id
            and not cert
            and not collection
            and not genres
            and not tags
            and not rule_category
            and not provider
        ):
            continue

        if kind in ("movies",):
            kind = "movie"
        elif kind in ("series", "show", "shows"):
            kind = "tv"
        elif kind not in ("movie", "tv", "any"):
            kind = "any"

        rule = {
            "id": rule_id or f"rule-{index}",
            "media_kind": kind,
            "category": rule_category,
        }

        if cert:
            rule["certification"] = cert

        if collection:
            rule["collection"] = collection

        if genres:
            rule["genres"] = genres

        if tags:
            rule["tags"] = tags

        if provider:
            rule["provider"] = provider

        if fallback:
            rule["fallback"] = True

        organisation_rules.append(rule)

    payload = {
        "name": name.strip(),
        "roots": roots,
        "sources": input_view.get("source_rows") or [],
        "movie_template": "movie",
        "tv_template": "tv",
        "category_template": "category",
        "templates": templates,
        "categories": categories,
        "intelligent_rules": _parse_signal_rows(body),
        "organisation_rules": organisation_rules,
        "certification_rules": _parse_cert_rule_rows(body),
        "collection_rules": _parse_collection_rule_rows(
            body
        ),
        "tag_mappings": mappings,
        "filename_policy": _parse_filename_policy(body),
        "naming": {
            "separator": input_view["naming_separator"],
            "case": "preserve",
        },
        "collision_policy": input_view[
            "collision_policy"
        ],
        "platform": input_view["platform"],
        "provider_priority": _parse_priority_field(
            services, _form_value(body, "provider_priority")
        ),
        "origin": (
            {"preset": input_view["origin_preset"]}
            if input_view.get("origin_preset")
            else None
        ),
    }

    try:
        if update_id is not None:
            saved = (
                services.organisation_service.update_profile(
                    int(update_id), payload
                )
            )
        else:
            saved = (
                services.organisation_service.create_profile(
                    payload
                )
            )
    except ValueError as error:
        errors = [str(error)]
        return {
            "saved": None,
            "errors": errors,
            "error_sections": _error_sections(errors),
            "input": input_view,
            "profiles": (
                services.organisation_service.list_profiles()
            ),
            "builtins": builtins,
            "presets": extras["presets"],
            "completion": extras["completion"],
            "refreshed_at": now_timestamp(),
        }

    return {
        "saved": saved,
        "errors": [],
        "error_sections": [],
        "input": input_view,
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "builtins": builtins,
        "presets": extras["presets"],
        "completion": extras["completion"],
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 15 What-If planning (zero mutation)
#
# Read-only planning over the shared planning semantics.
# Handlers add no mutation; the service layer guarantees
# planning never persists.
# ---------------------------------------------------------


def organisation_whatif_data(services):
    """Empty What-If form state plus saved profiles."""

    return {
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "refreshed_at": now_timestamp(),
    }


def _whatif_metadata_scope(body):
    scope = _form_value(body, "metadata_scope") or "cached"

    if scope not in ("cached", "live"):
        raise ValueError(
            "metadata scope must be 'cached' or 'live'"
        )

    return scope


def _whatif_form_state(services):
    """Shared What-If form state for redisplay after an error."""

    return {
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "refreshed_at": now_timestamp(),
    }


def _whatif_run_mode(body):
    """
    Run intent for one What-If preview: profile
    default, folders-only (keep), clean, extended,
    or template, plus an optional per-run filename
    policy assembled from the run configuration
    fields. Returns (filename_mode,
    filename_policy, identify). filename_policy is
    None unless the run carries its own extended
    or template pattern.
    """

    raw = _form_value(body, "run_mode") or "profile"
    mode = str(raw).strip().casefold()

    if mode in ("", "profile", "default"):
        filename_mode = None
    elif mode in ("folders", "keep"):
        filename_mode = "folders"
    elif mode == "clean":
        filename_mode = "clean"
    elif mode == "extended":
        filename_mode = "extended"
    elif mode == "template":
        filename_mode = "template"
    else:
        raise ValueError(
            "run mode must be profile default, "
            "folders only, clean, extended, or template"
        )

    filename_policy = None

    if isinstance(body, dict) and mode in (
        "extended", "template",
    ):
        if mode == "extended":
            pattern = str(
                (body.get("filename_pattern") or [""])[0]
            ).strip()
            separator = str(
                (body.get("filename_separator") or [" "])[0]
            ) or " "

            if pattern:
                filename_policy = {
                    "mode": "extended",
                    "pattern": pattern,
                    "separator": separator,
                }
        else:
            pattern = str(
                (
                    body.get("filename_template_pattern")
                    or [""]
                )[0]
            ).strip()

            if pattern:
                filename_policy = {
                    "mode": "template",
                    "pattern": pattern,
                }

    identify = any(
        str(value).strip().lower() in ("yes", "true", "1", "on")
        for value in (
            (body.get("identify") or [])
            if isinstance(body, dict)
            else []
        )
    )

    return filename_mode, filename_policy, identify


def organisation_whatif_file_data(services, body):
    """
    Single-file What-If for one Media ID with an
    optional saved profile. No persistence, no mutation.
    Input problems return the form state with an
    in-context error instead of navigating away.
    """

    raw_media = _form_value(body, "media_id")
    raw_path_form = _form_value(body, "file_path")

    input_mode = (
        str(_form_value(body, "input_mode") or "media")
        .strip()
        .casefold()
    )

    # Exactly one primary input: the inactive field
    # is ignored even if a stale value posts.
    if input_mode == "file":
        raw_media = None
    else:
        raw_path_form = None

    profile_id = None
    metadata_scope = "cached"
    filename_mode = None
    filename_policy = None
    identify = False

    try:
        profile_id = _optional_profile_id(body)
        metadata_scope = _whatif_metadata_scope(body)
        filename_mode, filename_policy, identify = (
            _whatif_run_mode(body)
        )
    except ValueError as error:
        return {
            **_whatif_form_state(services),
            "input": {
                "media_id": raw_media or "",
                "file_path": raw_path_form or "",
                "profile_id": None,
                "metadata_scope": metadata_scope,
                "run_mode": _form_value(body, "run_mode") or "profile",
                "input_mode": _form_value(body, "input_mode") or "media",
                "identify": identify,
            },
            "form_error": {
                "title": "Check your selection",
                "message": str(error),
                "guidance": (
                    "Pick a profile from the list and "
                    "try again."
                ),
                "status": 400,
            },
        }

    if raw_media is None:
        raw_path = _form_value(body, "file_path")

        if raw_path:
            try:
                if identify:
                    plan = (
                        services.organisation_service
                        .identify_and_plan(
                            raw_path,
                            profile=profile_id,
                            filename_mode=filename_mode,
                            filename_policy=filename_policy,
                        )
                    )
                else:
                    plan = (
                        services.organisation_service
                        .plan_ephemeral_file(
                            raw_path,
                            profile=profile_id,
                            snapshots=None,
                            filename_mode=filename_mode,
                            filename_policy=filename_policy,
                        )
                    )
            except ValueError as error:
                return {
                    **_whatif_form_state(services),
                    "input": {
                        "media_id": "",
                        "file_path": raw_path,
                        "profile_id": profile_id,
                        "metadata_scope": metadata_scope,
                        "run_mode": _form_value(body, "run_mode") or "profile",
                "input_mode": _form_value(body, "input_mode") or "media",
                        "identify": identify,
                    },
                    "form_error": {
                        "title": "Unable to use this file",
                        "message": str(error),
                        "guidance": (
                            "Browse to a video file NAMOA "
                            "can read, then preview again. "
                            "Nothing was saved or changed."
                        ),
                        "status": 400,
                    },
                }

            return {
                "media_id": None,
                "file_path": raw_path,
                "profile_id": profile_id,
                "metadata_scope": metadata_scope,
                "run_mode": _form_value(body, "run_mode") or "profile",
                "input_mode": _form_value(body, "input_mode") or "media",
                "identify": identify,
                "plan": plan,
                "profile_summary": _whatif_profile_summary(
                    services, profile_id
                ),
                "refreshed_at": now_timestamp(),
            }

        return {
            **_whatif_form_state(services),
            "input": {
                "media_id": "",
                "file_path": "",
                "profile_id": profile_id,
                "metadata_scope": metadata_scope,
                "run_mode": _form_value(body, "run_mode") or "profile",
                "input_mode": _form_value(body, "input_mode") or "media",
                "identify": identify,
            },
            "form_error": {
                "title": "Media ID needed",
                "message": (
                    "Enter the Media ID of the item you "
                    "want to preview, or browse to a file "
                    "path instead."
                ),
                "guidance": (
                    "Open the item on the Media page or "
                    "find it with Quick Find, then enter "
                    "its Media ID here. Alternatively, "
                    "use the file path field for files "
                    "NAMOA has never seen."
                ),
                "status": 400,
            },
        }

    try:
        media_id = int(raw_media)
    except (TypeError, ValueError):
        return {
            **_whatif_form_state(services),
            "input": {
                "media_id": raw_media,
                "file_path": raw_path_form or "",
                "profile_id": profile_id,
                "metadata_scope": metadata_scope,
                "run_mode": _form_value(body, "run_mode") or "profile",
                "input_mode": _form_value(body, "input_mode") or "media",
                "identify": identify,
            },
            "form_error": {
                "title": "Media ID not understood",
                "message": (
                    f"'{raw_media}' is not a valid Media ID."
                ),
                "guidance": (
                    "A Media ID is a plain number, shown "
                    "on the Media page for each item."
                ),
                "status": 400,
            },
        }

    try:
        plan = services.organisation_service.plan_file(
            media_id,
            profile=profile_id,
            metadata_scope=metadata_scope,
            filename_mode=filename_mode,
            filename_policy=filename_policy,
        )
    except ValueError:
        return {
            **_whatif_form_state(services),
            "input": {
                "media_id": raw_media,
                "file_path": raw_path_form or "",
                "profile_id": profile_id,
                "metadata_scope": metadata_scope,
                "run_mode": _form_value(body, "run_mode") or "profile",
                "input_mode": _form_value(body, "input_mode") or "media",
                "identify": identify,
            },
            "form_error": {
                "title": "Media ID not found",
                "message": (
                    f"Media ID {media_id} does not exist "
                    f"in the current library."
                ),
                "guidance": (
                    "Check the ID and try again, or "
                    "select the item from the "
                    "Media/Quick Find screens."
                ),
                "status": 404,
            },
        }

    return {
        "media_id": media_id,
        "profile_id": profile_id,
        "metadata_scope": metadata_scope,
        "run_mode": _form_value(body, "run_mode") or "profile",
        "identify": identify,
        "plan": plan,
        "profile_summary": _whatif_profile_summary(
            services, profile_id
        ),
        "refreshed_at": now_timestamp(),
    }


def _whatif_profile_summary(services, profile_id):
    """
    Profile name plus saved filename policy mode
    for What-If result presentation. Never raises:
    unknown profiles yield empty labels.
    """

    try:
        profile = services.organisation_service.get_profile(
            int(profile_id)
        )
    except (TypeError, ValueError):
        return {"name": "", "filename_mode": ""}

    policy = (profile.get("payload") or {}).get(
        "filename_policy"
    ) or {}

    return {
        "name": profile.get("name") or "",
        "filename_mode": policy.get("mode") or "keep",
    }


def organisation_scan_handoff_data(services, directory):
    """
    Confirmation data for handing one directory to
    the existing /scan workflow. Shows the exact
    selected path; nothing starts here. Read-only.
    """

    directory = (directory or "").strip()

    if not directory:
        raise ValueError(
            "A directory is required for scan handoff."
        )

    return {
        "directory": directory,
        "refreshed_at": now_timestamp(),
    }


def organisation_whatif_sample_data(services, body):
    """
    Random directory sampler What-If: up to `limit`
    eligible files rendered through the shared scope
    planning semantics. No persistence, no mutation.
    """

    directory = _form_value(body, "directory")

    profile_id = None
    metadata_scope = "cached"

    try:
        profile_id = _optional_profile_id(body)
        metadata_scope = _whatif_metadata_scope(body)
    except ValueError as error:
        return {
            **_whatif_form_state(services),
            "input": {
                "directory": directory or "",
                "limit": _form_value(body, "limit") or "10",
                "seed": _form_value(body, "seed") or "",
                "profile_id": None,
                "metadata_scope": metadata_scope,
            },
            "form_error": {
                "title": "Check your selection",
                "message": str(error),
                "guidance": (
                    "Pick a profile from the list and "
                    "try again."
                ),
                "status": 400,
            },
        }

    if not directory:
        return {
            **_whatif_form_state(services),
            "input": {
                "directory": "",
                "limit": _form_value(body, "limit") or "10",
                "seed": _form_value(body, "seed") or "",
                "profile_id": profile_id,
                "metadata_scope": metadata_scope,
            },
            "form_error": {
                "title": "Directory needed",
                "message": (
                    "Choose the directory you want to "
                    "sample."
                ),
                "guidance": (
                    "Use Browse to navigate to the folder, "
                    "select it, then run the sample."
                ),
                "status": 400,
            },
        }

    raw_limit = _form_value(body, "limit")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return {
                **_whatif_form_state(services),
                "input": {
                    "directory": directory,
                    "limit": raw_limit,
                    "seed": (
                        _form_value(body, "seed") or ""
                    ),
                    "profile_id": profile_id,
                    "metadata_scope": metadata_scope,
                },
                "form_error": {
                    "title": "Sample size not understood",
                    "message": (
                        f"'{raw_limit}' is not a valid "
                        f"sample size."
                    ),
                    "guidance": (
                        "Enter a whole number from 1 to 10."
                    ),
                    "status": 400,
                },
            }

    limit = max(1, min(10, limit))

    raw_seed = _form_value(body, "seed")

    if raw_seed is None:
        seed = None
    else:
        try:
            seed = int(raw_seed)
        except (TypeError, ValueError):
            return {
                **_whatif_form_state(services),
                "input": {
                    "directory": directory,
                    "limit": raw_limit or "10",
                    "seed": raw_seed,
                    "profile_id": profile_id,
                    "metadata_scope": metadata_scope,
                },
                "form_error": {
                    "title": "Seed not understood",
                    "message": (
                        f"'{raw_seed}' is not a valid seed."
                    ),
                    "guidance": (
                        "Leave the seed blank for a fresh "
                        "random sample, or enter a whole "
                        "number to repeat a sample."
                    ),
                    "status": 400,
                },
            }

    try:
        sample = services.organisation_service.sample_what_if(
            directory,
            limit=limit,
            seed=seed,
            profile=profile_id,
            metadata_scope=metadata_scope,
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    if isinstance(sample, dict) and sample.get("error"):
        return {
            **_whatif_form_state(services),
            "input": {
                "directory": directory,
                "limit": raw_limit or "10",
                "seed": (
                    "" if raw_seed is None else raw_seed
                ),
                "profile_id": profile_id,
                "metadata_scope": metadata_scope,
            },
            "form_error": {
                "title": "Directory not sampled",
                "message": str(sample["error"]),
                "guidance": (
                    "Use Browse to pick a directory "
                    "NAMOA can read, then try again."
                ),
                "status": 404,
            },
        }

    return {
        "directory": directory,
        "limit": limit,
        "profile_id": profile_id,
        "metadata_scope": metadata_scope,
        "sample": sample,
        "refreshed_at": now_timestamp(),
    }


# ---------------------------------------------------------
# Sprint 15 reconciliation, preflight, scope actions and
# scope executions
#
# Preview is ephemeral (plan_scope, no writes). The
# confirm step persists via generate_reconciliation and
# then accepts every actionable item explicitly through
# the bulk boundary with per-item results.
# ---------------------------------------------------------


def organisation_reconcile_data(services):
    """Reconciliation form state plus saved profiles."""

    return {
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "refreshed_at": now_timestamp(),
    }


def _reconcile_scope_body(body):
    scope = _form_value(body, "scope") or ""

    if not scope:
        raise ValueError("A scope path is required")

    return scope


def organisation_reconcile_preview_data(services, body):
    """
    Ephemeral scope preview via plan_scope: strategy,
    counts, review conditions and per-file rows.
    Persists nothing. A missing scope redisplays the
    reconcile form with an in-context error.
    """

    scope = (_form_value(body, "scope") or "").strip()

    if not scope:
        return {
            "profiles": (
                services.organisation_service.list_profiles()
            ),
            "input": {"scope": ""},
            "form_error": {
                "title": "Scope needed",
                "message": (
                    "Choose the directory scope you want "
                    "to preview."
                ),
                "guidance": (
                    "Use Browse to navigate to the folder, "
                    "select it, then preview the scope."
                ),
                "status": 400,
            },
            "refreshed_at": now_timestamp(),
        }

    profile_id = _optional_profile_id(body)

    try:
        preview = services.organisation_service.plan_scope(
            {"path": scope},
            profile=profile_id,
            metadata_scope="cached",
        )
        profile = services.organisation_service.get_profile(
            profile_id
        ) if profile_id is not None else None
    except ValueError as error:
        raise _not_found_from(str(error))

    filename_policy = (
        (profile.get("payload") or {}).get("filename_policy")
        if profile else {}
    ) or {}

    return {
        "scope": scope,
        "profile_id": profile_id,
        "profile_name": (
            profile.get("name") if profile else None
        ),
        "filename_mode": filename_policy.get("mode", "keep"),
        "preview": preview,
        "refreshed_at": now_timestamp(),
    }


def organisation_reconcile_confirm_data(services, body):
    """
    Persist one reconciliation run (proposals plus scope
    actions) then bulk-accept every actionable item with
    per-item results. Each step is an explicit human
    action; failures stay per item.
    """

    scope = _reconcile_scope_body(body)

    profile_id = _optional_profile_id(body)

    try:
        summary = (
            services.organisation_service
            .generate_reconciliation(
                profile=profile_id,
                metadata_scope="cached",
                scope={"path": scope},
            )
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    acceptance = (
        services.bulk_organisation_service.accept_many(
            proposal_ids=summary.get("proposal_ids") or [],
            scope_action_ids=(
                summary.get("scope_action_ids") or []
            ),
            accepted_by="human",
        )
    )

    try:
        profile = (
            services.organisation_service.get_profile(
                profile_id
            )
            if profile_id is not None
            else None
        )
    except ValueError:
        profile = None

    filename_policy = (
        (profile.get("payload") or {}).get("filename_policy")
        if profile
        else {}
    ) or {}

    return {
        "scope": scope,
        "profile_id": profile_id,
        "profile_name": (
            profile.get("name") if profile else None
        ),
        "filename_mode": filename_policy.get("mode", "keep"),
        "summary": summary,
        "acceptance": acceptance,
        "refreshed_at": now_timestamp(),
    }


def organisation_preflight_data(services, body=None):
    """
    Advisory Organisation Preflight over the configured
    setup. Read-only; creates no probe artifacts. An
    optional profile and scope path focus the checks on
    the setup the user is about to use; otherwise the
    saved default profile and its roots apply.
    """

    profile_id = None
    scope = ""

    if body is not None:
        scope = (_form_value(body, "scope") or "").strip()

        try:
            profile_id = _optional_profile_id(body)
        except ValueError as error:
            return {
                "preflight": (
                    services.organisation_service.preflight(
                        None
                    )
                ),
                "profiles": (
                    services.organisation_service
                    .list_profiles()
                ),
                "profile_id": None,
                "scope": scope,
                "form_error": {
                    "title": "Check your selection",
                    "message": str(error),
                    "guidance": (
                        "Pick a profile from the list and "
                        "run the checks again."
                    ),
                    "status": 400,
                },
                "refreshed_at": now_timestamp(),
            }

    roots = [scope] if scope else None

    return {
        "preflight": (
            services.organisation_service.preflight(
                profile_id, roots=roots
            )
        ),
        "profiles": (
            services.organisation_service.list_profiles()
        ),
        "profile_id": profile_id,
        "scope": scope,
        "refreshed_at": now_timestamp(),
    }


def organisation_scope_action_detail_data(
    services,
    action_id,
):
    """
    One durable scope action with its lifecycle events.
    """

    from app.web.serializers import (
        organisation_events_to_dict,
        scope_action_to_dict,
    )

    try:
        action_id = int(action_id)

        detail = (
            services.organisation_service.get_scope_action(
                action_id
            )
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return {
        "action": scope_action_to_dict(detail["action"]),
        "events": organisation_events_to_dict(
            detail["events"]
        ),
        "refreshed_at": now_timestamp(),
    }


def organisation_scope_action_accept_data(
    services,
    action_id,
):
    """
    Accept one scope action (atomically accepting its
    covered descendant proposals) through the single
    organisation application boundary, then return the
    refreshed detail view.
    """

    try:
        action_id = int(action_id)

        services.organisation_service.accept_scope_action(
            action_id,
            accepted_by="human",
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return organisation_scope_action_detail_data(
        services,
        action_id,
    )


def organisation_scope_executions_data(services):
    """
    Every recorded scope execution. Reads flow through
    the application boundary only.
    """

    from app.web.serializers import (
        scope_execution_to_dict,
    )

    executions = (
        services.organisation_execution_service
        .list_scope_executions()
    )

    return {
        "executions": [
            scope_execution_to_dict(execution)
            for execution in executions
        ],
        "total_count": len(executions),
        "refreshed_at": now_timestamp(),
    }


def _scope_execution_detail(services, execution_id):
    from app.web.serializers import (
        organisation_events_to_dict,
        scope_action_to_dict,
        scope_execution_to_dict,
    )

    try:
        execution_id = int(execution_id)

        execution = (
            services.organisation_execution_service
            .get_scope_execution(execution_id)
        )

        events = (
            services.organisation_execution_service
            .scope_execution_events(execution_id)
        )

        continuity = (
            services.organisation_execution_service
            .scope_continuity(execution_id)
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    action = None

    try:
        detail = (
            services.organisation_service.get_scope_action(
                execution.scope_action_id
            )
        )

        action = scope_action_to_dict(detail["action"])
    except ValueError:
        action = None

    return {
        "execution": scope_execution_to_dict(execution),
        "events": organisation_events_to_dict(events),
        "continuity": [dict(entry) for entry in continuity],
        "action": action,
        "refreshed_at": now_timestamp(),
    }


def organisation_scope_execution_detail_data(
    services,
    execution_id,
):
    """
    One scope execution with its lifecycle events,
    continuity records, and the producing scope action.
    """

    return _scope_execution_detail(services, execution_id)


def organisation_scope_action_execute_data(
    services,
    action_id,
    body,
):
    """
    Execute one approved scope action through the
    existing organisation execution authority.
    Explicit human action; only 'accepted' scope
    actions execute.
    """

    actor = "human"

    if isinstance(body, dict):

        raw = (body.get("actor") or [None])[0]

        if raw and raw.strip():

            actor = raw.strip()

    try:

        execution = (
            services.organisation_execution_service
            .execute_scope_action(
                int(action_id),
                actor=actor,
            )
        )

    except ValueError as error:

        raise _not_found_from(str(error))

    return _scope_execution_detail(
        services,
        execution.id,
    )


def organisation_scope_execution_recover_data(    services,
    execution_id,
):
    """
    Reconcile one interrupted/uncertain scope execution
    against real filesystem reality through the existing
    recovery authority.
    """

    try:
        execution = (
            services.organisation_execution_service
            .recover_scope_execution(int(execution_id))
        )
    except ValueError as error:
        raise _not_found_from(str(error))

    return _scope_execution_detail(services, execution.id)


# ----------------------------------------------------------------------
# Phase 16 preference experience (wizard, centre, review).
#
# Thin assemblies over services.preference_service only. Every action
# routes through the Phase 15 backend contracts (sampler, compiler,
# coverage, suggestion lifecycle, continuity); nothing here
# reconstructs rules, coverage, matching, scoring, or compatibility.
# Returned dicts are JSON-safe and feed both HTML and /api JSON.
# ----------------------------------------------------------------------


def _preference_form_error(message, *, title="Preference action needed"):
    return {
        "title": title,
        "message": message,
        "guidance": (
            "The preference backend refused this action. No "
            "preferences were changed by the failed attempt."
        ),
        "status": 400,
    }


def preferences_data(services):
    """Preference Centre read: intent defaults, rules, coverage."""

    data = services.preference_service.centre_view()
    data["refreshed_at"] = now_timestamp()

    return data


def preferences_wizard_intro(services):
    """Wizard opening state: explanation plus intent vocabulary."""

    view = services.preference_service.wizard_intro_view()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_data(services, session_id=None):
    """GET wizard: intro without a session, live view with one."""

    if not session_id:
        return preferences_wizard_intro(services)

    try:
        view = services.preference_service.wizard_view(session_id)
    except ValueError as error:
        raise _not_found_from(str(error))

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def _wizard_view_or_intro(services, session_id, message):
    """Recoverable wizard failure: re-render with an error panel."""

    try:
        view = services.preference_service.wizard_view(session_id)
    except ValueError:
        view = preferences_wizard_intro(services)

    view["form_error"] = _preference_form_error(message)

    return view


def preferences_wizard_start_data(services, body):
    """Open a session from the intent triple; show first question."""

    preference_service = services.preference_service

    mode = _form_value(body, "mode") or "fresh"

    try:
        view = preference_service.wizard_start_view(
            compatibility=_form_value(body, "compatibility"),
            quality_ceiling=_form_value(body, "quality_ceiling"),
            optimisation=_form_value(body, "optimisation"),
            mode=mode,
        )
    except ValueError as error:
        view = preferences_wizard_intro(services)
        view["form_error"] = _preference_form_error(
            str(error) or "Those intent choices are not valid."
        )

        return view

    if view.get("mode") == "empty":
        view = preferences_wizard_intro(services)
        view["form_error"] = _preference_form_error(
            "No analysable media was found, so the wizard has "
            "nothing to ask about yet. Scan the library first.",
            title="Nothing to ask about",
        )

        return view

    view["vocab"] = preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_answer_data(services, body):
    """Record one explicit answer; show the next question or finish."""

    session_id = _form_value(body, "session_id")
    media_id = _form_value(body, "media_id")
    answer = _form_value(body, "answer")

    if not session_id or not media_id or not answer:
        raise UserError(
            "A session, media item, and answer are all required.",
            title="Incomplete answer",
        )

    try:
        view = services.preference_service.wizard_answer_view(
            session_id, media_id, answer
        )
    except ValueError as error:
        return _wizard_view_or_intro(
            services, session_id, str(error) or "That answer was refused."
        )

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_undo_data(services, body):
    """Drop the most recent answer; re-show its question."""

    session_id = _form_value(body, "session_id")

    if not session_id:
        raise UserError(
            "A session is required to go back.",
            title="Incomplete request",
        )

    try:
        view = services.preference_service.wizard_undo_view(
            session_id
        )
    except ValueError as error:
        return _wizard_view_or_intro(
            services, session_id, str(error) or "Cannot go back."
        )

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_finish_data(services, body):
    """Mark the session finished (early or at sufficiency)."""

    session_id = _form_value(body, "session_id")

    if not session_id:
        raise UserError(
            "A session is required to finish.",
            title="Incomplete request",
        )

    try:
        view = services.preference_service.wizard_finish_view(
            session_id
        )
    except ValueError as error:
        return _wizard_view_or_intro(
            services, session_id, str(error) or "Cannot finish."
        )

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_cancel_data(services, body):
    """Drop the session without persisting anything."""

    session_id = _form_value(body, "session_id")

    if not session_id:
        raise UserError(
            "A session is required to cancel.",
            title="Incomplete request",
        )

    try:
        view = services.preference_service.wizard_cancel_view(
            session_id
        )
    except ValueError as error:
        return _wizard_view_or_intro(
            services, session_id, str(error) or "Cannot cancel."
        )

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_reset_data(services, body):
    """Explicit Wizard reset: clear durable progress only."""

    try:
        view = services.preference_service.reset_wizard()
    except ValueError as error:
        view = preferences_wizard_intro(services)
        view["form_error"] = _preference_form_error(
            str(error) or "The Wizard could not be reset."
        )

        return view

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_wizard_save_data(services, body):
    """Propose the finished session's suggestions for review."""

    session_id = _form_value(body, "session_id")

    if not session_id:
        raise UserError(
            "A session is required to save.",
            title="Incomplete request",
        )

    try:
        view = services.preference_service.wizard_save_view(
            session_id, actor="human"
        )
    except ValueError as error:
        return _wizard_view_or_intro(
            services,
            session_id,
            str(error) or "Those answers cannot be saved.",
        )

    view["vocab"] = services.preference_service.intent_vocab()
    view["refreshed_at"] = now_timestamp()

    return view


def _review_view_with_error(services, message):
    """Recoverable review failure: re-render the list with a panel."""

    view = services.preference_service.review_view()
    view["form_error"] = _preference_form_error(message)
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_data(services, view="needs"):
    """Review read: proposed suggestions plus lifecycle history."""

    if view not in (
        "needs",
        "recommendations",
        "context",
        "waiting",
        "all",
    ):
        view = "needs"

    data = services.preference_service.review_view(view=view)
    data["refreshed_at"] = now_timestamp()

    return data


def preferences_review_specify_data(services, body):
    """Specify an explicit recommendation for a Needs More Context item."""

    suggestion_id = _form_value(body, "suggestion_id")
    answer = _form_value(body, "new_answer")

    if not suggestion_id or not answer:
        raise UserError(
            "A suggestion and a recommendation are both required.",
            title="Incomplete recommendation",
        )

    try:
        services.preference_service.specify_recommendation(
            suggestion_id, answer, actor="human"
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error)
            or "That recommendation cannot be saved.",
        )

    view = services.preference_service.review_view()
    view["notice"] = (
        "Recommendation saved. You made an explicit decision; "
        "NAMOA has not executed any optimisation."
    )
    view["refreshed_at"] = now_timestamp()

    return view


def _manual_selection_from_body(body):
    """Collect the Manual Choice field selection from a form body."""

    selection = {}

    for name, values in (body or {}).items():
        if isinstance(name, str) and name.startswith("field_"):
            raw = (
                values[0]
                if isinstance(values, list) and values
                else values
            )

            selection[name[len("field_"):]] = raw

    raw_leave = (body or {}).get("leave_alone")

    selection["leave_alone"] = (
        raw_leave[0]
        if isinstance(raw_leave, list) and raw_leave
        else raw_leave
    )

    raw_answer = _form_value(body, "answer")

    if raw_answer:
        selection["answer"] = raw_answer

    return selection


def _carousel_after_decision(services, body, message):
    """Render the next carousel item after a persisted decision."""

    index = _form_value(body, "index") or "0"

    view = services.preference_service.carousel_view(
        index, advance=True
    )

    view["notice"] = message
    view["refreshed_at"] = now_timestamp()

    return view


def _carousel_error(services, body, message):
    """Re-render the current carousel item with an error panel."""

    index = _form_value(body, "index") or "0"

    view = services.preference_service.carousel_view(index)

    view["form_error"] = _preference_form_error(message)
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_carousel_data(services, index=None):
    """Optimisation Carousel read: one unresolved review item."""

    try:
        position = int(index) if index not in (None, "") else 0
    except (TypeError, ValueError):
        position = 0

    data = services.preference_service.carousel_view(position)
    data["refreshed_at"] = now_timestamp()

    return data


def preferences_carousel_accept_data(services, body):
    """Accept the carousel item through the shared review lifecycle."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required for acceptance.",
            title="Incomplete acceptance",
        )

    try:
        services.preference_service.accept_suggestion(
            suggestion_id, actor="human"
        )
    except ValueError as error:
        return _carousel_error(
            services,
            body,
            str(error) or "That suggestion cannot be accepted.",
        )

    return _carousel_after_decision(
        services,
        body,
        "Accepted: this is now an established preference. "
        "Nothing has been executed.",
    )


def preferences_carousel_reject_data(services, body):
    """Reject the carousel item through the shared review lifecycle."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required to reject.",
            title="Incomplete request",
        )

    try:
        services.preference_service.reject_suggestion(
            suggestion_id,
            actor="human",
            reason=_form_value(body, "reason"),
        )
    except ValueError as error:
        return _carousel_error(
            services,
            body,
            str(error) or "That suggestion cannot be rejected.",
        )

    return _carousel_after_decision(
        services,
        body,
        "Rejected: recorded as your decision against this "
        "recommendation. Nothing has been executed.",
    )


def preferences_carousel_manual_data(services, body):
    """Save a Manual Choice from the carousel via the shared lifecycle."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required.",
            title="Incomplete request",
        )

    try:
        services.preference_service.manual_choice(
            suggestion_id,
            _manual_selection_from_body(body),
            actor="human",
        )
    except ValueError as error:
        return _carousel_error(
            services,
            body,
            str(error) or "That manual choice cannot be saved.",
        )

    return _carousel_after_decision(
        services,
        body,
        "Manual choice saved: the original recommendation was "
        "superseded and a replacement awaits review. Nothing has "
        "been executed.",
    )


def preferences_review_manual_data(services, body):
    """Save a Manual Choice from the Review Suggestions list."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required.",
            title="Incomplete request",
        )

    try:
        services.preference_service.manual_choice(
            suggestion_id,
            _manual_selection_from_body(body),
            actor="human",
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error) or "That manual choice cannot be saved.",
        )

    view = services.preference_service.review_view()
    view["notice"] = (
        "Manual choice saved: the original recommendation was "
        "superseded and a replacement awaits review. Nothing has "
        "been executed."
    )
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_refresh_data(services, body):
    """Generate suggestions from accepted rules (idempotent)."""

    try:
        result = services.preference_service.refresh_suggestions(
            actor="human"
        )
    except ValueError as error:
        return _review_view_with_error(
            services, str(error) or "Suggestions cannot be refreshed."
        )

    view = services.preference_service.review_view()
    view["refresh"] = {
        "generated": result["generated"],
        "stored_total": result["stored_total"],
    }
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_accept_data(services, body):
    """Accept one suggestion; proof comes from observed state."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required for acceptance.",
            title="Incomplete acceptance",
        )

    try:
        accepted, _ = (
            services.preference_service.accept_suggestion(
                suggestion_id,
                actor="human",
            )
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error) or "That suggestion cannot be accepted.",
        )

    view = services.preference_service.review_view()
    view["notice"] = (
        "Accepted: this is now an established preference."
    )
    view["accepted_id"] = accepted.suggestion_id
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_reject_data(services, body):
    """Reject one proposed suggestion (records the decision only)."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required to reject.",
            title="Incomplete request",
        )

    try:
        services.preference_service.reject_suggestion(
            suggestion_id,
            actor="human",
            reason=_form_value(body, "reason"),
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error) or "That suggestion cannot be rejected.",
        )

    view = services.preference_service.review_view()
    view["notice"] = "Rejected: this suggestion will not return."
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_change_data(services, body):
    """Resolve one suggestion to a different explicit answer."""

    suggestion_id = _form_value(body, "suggestion_id")
    new_answer = _form_value(body, "new_answer")

    if not suggestion_id or not new_answer:
        raise UserError(
            "A suggestion and a replacement answer are required.",
            title="Incomplete change",
        )

    try:
        replacement = services.preference_service.change_suggestion(
            suggestion_id, new_answer, actor="human"
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error) or "That suggestion cannot be changed.",
        )

    view = services.preference_service.review_view()
    view["notice"] = (
        "Changed: the replacement awaits its own review."
    )
    view["replacement_id"] = replacement.suggestion_id
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_reopen_data(services, body):
    """Return one rejected suggestion to proposed (reopen only)."""

    suggestion_id = _form_value(body, "suggestion_id")

    if not suggestion_id:
        raise UserError(
            "A suggestion is required to reopen.",
            title="Incomplete request",
        )

    try:
        services.preference_service.reopen_suggestion(
            suggestion_id, actor="human"
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error) or "That suggestion cannot be reopened.",
        )

    view = services.preference_service.review_view()
    view["notice"] = "Reopened: this suggestion is proposed again."
    view["refreshed_at"] = now_timestamp()

    return view


def preferences_review_accept_all_data(services, body):
    """Atomic bulk acceptance; proof derived server-side per row."""

    try:
        accepted = (
            services.preference_service.accept_all_suggestions(
                actor="human"
            )
        )
    except ValueError as error:
        return _review_view_with_error(
            services,
            str(error) or "Bulk acceptance cannot proceed.",
        )

    view = services.preference_service.review_view()
    view["notice"] = (
        "Accepted %d suggestion(s). Each acceptance is "
        "attributed individually; nothing else was approved."
        % len(accepted)
    )
    view["refreshed_at"] = now_timestamp()

    return view


# ---------------------------------------------------------
# Phase 17 optimisation preview.
#
# Thin assemblies over services.preview_service only. Preview
# generation never mutates library state; only an explicit
# Accept queues through the existing approval boundary.
# ---------------------------------------------------------


def _preview_error(message, token=None):
    return {
        "preview": None,
        "token": token,
        "form_error": {
            "title": "Preview unavailable",
            "message": message,
        },
    }


def _preview_view(services, context):
    data = {
        "preview": context.to_view(),
        "token": context.token,
        "settings": services.preview_service.settings.to_dict(),
        "refreshed_at": now_timestamp(),
    }

    try:
        data["operations"] = (
            services.operation_service.executable_operations()
        )
    except (AttributeError, ValueError):
        data["operations"] = []

    try:
        data["operation_schema"] = (
            services.operation_service.operation_schema(
                context.to_view().get("operation") or ""
            )
        )
    except (AttributeError, ValueError):
        data["operation_schema"] = None

    return data


def preview_new_data(services, origin=None, ref=None):
    """Create a preview context from an explicit origin reference."""

    preview_service = services.preview_service

    try:
        if origin == "wizard":
            if not ref:
                raise UserError(
                    "A suggestion is required to preview a "
                    "Wizard recommendation.",
                    title="Incomplete preview request",
                )

            context = preview_service.create_wizard_preview(
                ref, actor="human"
            )
        else:
            if not ref:
                raise UserError(
                    "A media item is required to preview an "
                    "Analysis recommendation.",
                    title="Incomplete preview request",
                )

            try:
                media_id = int(ref)
            except (TypeError, ValueError):
                raise UserError(
                    "The media reference is not valid.",
                    title="Incomplete preview request",
                )

            context = preview_service.create_analysis_preview(
                media_id, actor="human"
            )
    except PreviewError as error:
        return _preview_error(str(error))

    return _preview_view(services, context)


def preview_page_data(services, token=None):
    """Render one preview context (no generation, no decisions)."""

    try:
        context = services.preview_service.get_context(token)
    except PreviewError as error:
        return _preview_error(str(error), token=token)

    return _preview_view(services, context)


def preview_generate_data(services, body):
    """Generate (or regenerate) the bounded preview segment.

    Accepts an optional ``start_seconds`` form value selecting
    the comparison position; absent means the established
    automatic position. The position changes only the temporary
    sample, never the transformation or approval state.
    """

    token = _form_value(body, "token")
    raw_start = _form_value(body, "start_seconds")

    start_seconds = None

    if raw_start is not None:
        try:
            start_seconds = float(raw_start)
        except (TypeError, ValueError):
            return _preview_error(
                "The preview position must be a number.",
                token=token,
            )

        if not (start_seconds == start_seconds):
            return _preview_error(
                "The preview position must be a finite number.",
                token=token,
            )

    try:
        context = services.preview_service.generate_preview(
            token, start_seconds=start_seconds
        )
    except PreviewError as error:
        # Generation failures persist the failed context
        # (retention assessment and alternatives stay attached),
        # so return the normal view with the error instead of
        # discarding it: the template can still offer verified
        # preservation alternatives.
        try:
            context = services.preview_service.get_context(
                token
            )
        except PreviewError:
            context = None

        if context is None:
            return _preview_error(str(error), token=token)

        data = _preview_view(services, context)
        data["form_error"] = {
            "title": "Preview unavailable",
            "message": str(error),
        }

        return data

    data = _preview_view(services, context)
    data["notice"] = (
        "Preview generated. It is a temporary sample only; "
        "nothing was accepted, queued, or executed."
    )

    return data


def _preview_failure_view(services, token, error):
    """Normal Preview view for a failed generation attempt.

    Regeneration paths (initial generate, preserve fallback,
    explicit override, position change) all persist the failed
    PreviewContext before raising, so the normal page — with
    its current operation, retention state, alternatives, and
    decision controls — stays available. Only when no context
    exists at all (unknown/closed token) is the standalone
    error shape returned. The raw message is preserved
    verbatim; the template decides how to present it.
    """

    try:
        context = services.preview_service.get_context(token)
    except PreviewError:
        context = None

    if context is None:
        return _preview_error(str(error), token=token)

    data = _preview_view(services, context)
    data["form_error"] = {
        "title": "Preview unavailable",
        "message": str(error),
    }

    return data


def preview_override_data(services, body):
    """Apply an explicit user override and regenerate the preview."""

    token = _form_value(body, "token")
    operation = _form_value(body, "operation")

    parameters = {}

    if isinstance(body, dict):
        for name, values in body.items():
            if not isinstance(name, str):
                continue

            if not name.startswith("param_"):
                continue

            raw = (values or [None])[0]

            if raw is None or str(raw).strip() == "":
                continue

            parameters[name[len("param_"):]] = str(raw).strip()

    try:
        services.preview_service.apply_override(
            token,
            operation=operation,
            parameters=parameters,
        )
        context = services.preview_service.generate_preview(
            token
        )
    except PreviewError as error:
        return _preview_failure_view(services, token, error)

    data = _preview_view(services, context)
    data["notice"] = (
        "Override applied and preview regenerated. The "
        "override is now the authoritative context for "
        "Preview, Accept, execution, and provenance."
    )

    return data


def preview_accept_data(services, body):
    """Accept the pinned preview context (queues, then verifies)."""

    token = _form_value(body, "token")
    delete_original = _form_flag(body, "delete_original")

    try:
        result = services.preview_service.accept_preview(
            token,
            actor="human",
            delete_original_requested=delete_original,
        )
        context = services.preview_service.get_context(token)
    except PreviewError as error:
        return _preview_error(str(error), token=token)

    data = _preview_view(services, context)
    data["accepted"] = result
    data["notice"] = (
        "Accepted and queued as execution job "
        f"#{result['job_id']}. The preview itself was "
        "deleted; the queued job carries the previewed "
        "transformation."
    )

    return data


def preview_acknowledge_data(services, body):
    """Record explicit user acceptance of assessed retention loss."""

    token = _form_value(body, "token")

    try:
        context = services.preview_service.acknowledge_retention(
            token, actor="human"
        )
    except PreviewError as error:
        return _preview_error(str(error), token=token)

    data = _preview_view(services, context)
    data["notice"] = (
        "Loss acknowledged. Accept will now queue this "
        "transformation with your acknowledgement recorded "
        "in its provenance."
    )

    return data


def preview_preserve_data(services, body):
    """Select a preservation alternative as the override."""

    token = _form_value(body, "token")
    operation = _form_value(body, "operation")

    parameters = {}

    if isinstance(body, dict):
        for name, values in body.items():
            if not isinstance(name, str):
                continue

            if not name.startswith("param_"):
                continue

            raw = (values or [None])[0]

            if raw is None or str(raw).strip() == "":
                continue

            parameters[name[len("param_"):]] = str(raw).strip()

    try:
        context = services.preview_service.get_context(token)

        offered = {
            alternative.get("operation")
            for alternative in (context.alternatives or [])
        }

        if operation not in offered:
            raise PreviewError(
                "That preservation alternative was not offered "
                "for this preview. Nothing changed."
            )

        known = {
            alternative.get("operation"): dict(
                alternative.get("parameters") or {}
            )
            for alternative in (context.alternatives or [])
        }

        if not parameters:
            parameters = known.get(operation) or {}

        services.preview_service.apply_override(
            token,
            operation=operation,
            parameters=parameters,
        )
        context = services.preview_service.generate_preview(
            token
        )
    except PreviewError as error:
        return _preview_failure_view(services, token, error)

    data = _preview_view(services, context)
    data["notice"] = (
        "Preservation alternative applied as your override "
        "and preview regenerated. Accept will queue exactly "
        "what the preview shows."
    )

    return data


def preview_reject_data(services, body):
    """Reject through the existing rejection paths; clean preview."""

    token = _form_value(body, "token")
    reason = _form_value(body, "reason")

    try:
        services.preview_service.reject_preview(
            token, actor="human", reason=reason
        )
        context = services.preview_service.get_context(token)
    except PreviewError as error:
        return _preview_error(str(error), token=token)

    data = _preview_view(services, context)
    data["notice"] = (
        "Rejected through the existing rejection path. The "
        "transient preview was deleted; this is not reported "
        "as a preview failure."
    )

    return data


def preview_close_data(services, body):
    """Close a preview without changing any decision."""

    token = _form_value(body, "token")
    origin = _form_value(body, "origin") or "analysis"
    media_id = _form_value(body, "media_id")
    suggestion_id = _form_value(body, "suggestion_id")

    try:
        services.preview_service.close_preview(token)
    except PreviewError:
        pass

    return {
        "preview": None,
        "closed": True,
        "origin": origin,
        "media_id": media_id,
        "suggestion_id": suggestion_id,
        "refreshed_at": now_timestamp(),
    }
