"""
Presentation serializers for the NAMOA GUI.

Converts application-service read models into JSON-safe dicts for
the HTML pages and the JSON API. This is the presentation layer:

- formatting (bytes, percents, timestamps) lives here, never in the
  application layer
- status labels are derived HERE from the authoritative validity
  fields (reason, analysis_required, incomplete run states) - the
  fingerprint/validity rules themselves are never reimplemented
- no intelligence, no persistence, no validity computation
"""

import html
from datetime import datetime, timezone

# ---------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------


def format_bytes(value):
    """Human-readable size. None renders as an em dash."""

    if value is None:
        return "—"

    try:
        value = int(value)
    except (TypeError, ValueError):
        return "—"

    if value < 0:
        return "—"

    if value == 0:
        return "0 B"

    units = ["B", "KiB", "MiB", "GiB", "TiB"]

    amount = float(value)

    for unit in units:

        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} B"
            return f"{amount:.2f} {unit}"

        amount /= 1024

    return f"{amount:.2f} {units[-1]}"


def format_percent(value, digits=1):
    """Human-readable percentage. None renders as an em dash."""

    if value is None:
        return "—"

    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"

    return f"{value:.{digits}f}%"


def format_timestamp(value):
    """Normalise a stored SQLite timestamp for display."""

    if not value:
        return "—"

    text = str(value)

    if "T" in text:
        text = text.replace("T", " ")

    if "." in text and len(text.split(".")[1]) > 0:
        text = text.split(".")[0]

    return text


def format_duration(value):
    """Duration in seconds -> H:MM:SS. None renders as an em dash."""

    if value is None:
        return "—"

    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return "—"

    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours}:{minutes:02d}:{seconds:02d}"


def format_confidence(value):
    """Confidence 0..1 -> percent. None renders as an em dash."""

    if value is None:
        return "—"

    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"

    return f"{value * 100:.0f}%"


# ---------------------------------------------------------
# Human-facing display mappings (presentation only)
#
# These map stored domain values to normal user-facing wording.
# The stored values, calculations, ranking, and API payloads are
# never altered here; templates apply these mappings for display.
# ---------------------------------------------------------


OPPORTUNITY_LABELS = {
    "media_optimisation": ("Video optimisation", "opportunity"),
}


def opportunity_label(opportunity):
    """
    Human-facing (label, badge kind) for one stored opportunity
    value. Unknown values fall back to the raw value with a
    neutral badge so no opportunity is ever hidden.
    """

    return OPPORTUNITY_LABELS.get(
        opportunity or "",
        (opportunity or "Unknown", "unknown"),
    )


OPPORTUNITY_SET_LABELS = {
    "high_confidence": (
        "High confidence",
        "Recommendations NAMOA is most sure about.",
    ),
    "high_impact": (
        "High impact",
        "Recommendations expected to free the most space.",
    ),
    "low_risk": (
        "Low risk",
        "Recommendations with the lowest risk of problems.",
    ),
}


def opportunity_set_display(name, description=None):
    """
    Human-facing (title, description) for one recommendation set.
    The internal set name still keys membership, ordering, and
    tests of the underlying data; only the displayed words change.
    Unknown sets fall back to the stored name and description.
    """

    title, blurb = OPPORTUNITY_SET_LABELS.get(
        name or "", (None, None)
    )

    return (
        title or name or "Recommendations",
        blurb or description or "",
    )


def format_bytes_human(value):
    """
    Approximate decimal storage size for normal user-facing
    estimates. Presentation only: stored byte counts and the
    technical format_bytes behaviour are unchanged.

    Rules: exact bytes below 1000 (no approximation marker);
    whole MB below 1 GB; GB at and above 1 GB (one decimal
    below 10 GB, whole numbers at and above); TB likewise.
    None, unparseable, and negative values render as a plain
    missing-value marker, keeping new lines free of the legacy
    em dash convention used by format_bytes.
    """

    if value is None:
        return "n/a"

    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "n/a"

    if amount != amount or amount == float("inf"):
        return "n/a"

    if amount < 0:
        return "n/a"

    if amount < 1000:
        return f"{int(amount)} B"

    if amount < 1e9:
        return f"~{amount / 1e6:.0f} MB"

    if amount < 1e12:
        gb = amount / 1e9

        if gb >= 10:
            return f"~{gb:.0f} GB"

        return f"~{gb:.1f} GB"

    tb = amount / 1e12

    if tb >= 10:
        return f"~{tb:.0f} TB"

    return f"~{tb:.1f} TB"


def priority_band(score):
    """
    Display-only priority band for a stored priority score.

    Bands (High >= 0.60, Medium >= 0.40, otherwise Low) describe
    only how the score is presented. Ranking, sorting, stored
    priority, calculations, and queue decisions never consult
    this helper. This is intentionally distinct from the
    opportunity_level/priority_label model, which describes the
    assessed opportunity strength rather than the priority score.
    """

    try:
        value = float(score)
    except (TypeError, ValueError):
        return "Unknown"

    if value != value:
        return "Unknown"

    if value >= 0.60:
        return "High"

    if value >= 0.40:
        return "Medium"

    return "Low"


RISK_LABELS = {
    "low": ("Low", "risk-low"),
    "medium": ("Medium", "risk-medium"),
    "high": ("High", "risk-high"),
}

def risk_display(risk):
    """
    Human-facing (label, CSS class) for one stored categorical
    risk value. The risk value and calculation stay authoritative;
    only the displayed capitalisation and dedicated styling change.
    The CSS classes are risk-specific (risk-low/risk-medium/
    risk-high) and deliberately do not reuse the Current/Stale/
    Failed badge vocabulary, which already means freshness and
    execution state elsewhere.
    """

    return RISK_LABELS.get(
        str(risk or "").lower(),
        ("Unknown", "risk-unknown"),
    )


# ---------------------------------------------------------
# Status labels (presentation mapping over authoritative fields)
# ---------------------------------------------------------


def status_label(entry):
    """
    Derive a display label and badge class from the authoritative
    validity fields carried by a LineageStatusEntry.

    The validity rules themselves stay with the validity authority;
    this function only maps its fields to presentation strings.
    """

    reason = entry.get("reason") or ""
    required = bool(entry.get("analysis_required"))
    incomplete = entry.get("incomplete_run_states") or ()
    media_status = entry.get("media_status") or ""

    if media_status == "missing":
        return ("Missing", "missing")

    if media_status == "unavailable":
        return ("Unavailable", "stale")

    if not required:
        return ("Current", "current")

    if "failed" in incomplete:
        return ("Failed", "failed")

    if "abandoned" in incomplete:
        return ("Abandoned", "abandoned")

    if "cancelled" in incomplete:
        return ("Cancelled", "cancelled")

    if "running" in incomplete:
        return ("Running", "running")

    if "pending" in incomplete:
        return ("Pending", "pending")

    if reason == "no_current_observation":
        return ("Stale", "stale")

    return ("Not analysed", "stale")


def run_status_label(status):
    """Direct label for a run status value."""

    labels = {
        "pending": ("Pending", "pending"),
        "running": ("Running", "running"),
        "completed": ("Completed", "current"),
        "failed": ("Failed", "failed"),
        "cancelled": ("Cancelled", "cancelled"),
        "abandoned": ("Abandoned", "abandoned"),
    }

    return labels.get(status, (status or "Unknown", "unknown"))


# ---------------------------------------------------------
# Sprint 11 optimisation-workflow presentation helpers
# ---------------------------------------------------------


# Presentation mapping over the execution state machine's states.
# The lifecycle itself is owned by the execution authority; this
# only maps each recorded state to a display label and badge kind.
EXECUTION_STATE_LABELS = {
    "approved": ("Approved", "stale"),
    "planned": ("Planned", "stale"),
    "running": ("Running", "warn"),
    "verifying": ("Verifying", "warn"),
    "replacing": ("Replacing", "warn"),
    "succeeded": ("Succeeded", "current"),
    "rolled_back": ("Rolled back", "current"),
    "failed_execution": ("FFmpeg failed", "missing"),
    "failed_verification": ("Verification failed", "missing"),
    "failed_replacement": ("Replacement failed", "missing"),
    "interrupted": ("Interrupted", "warn"),
    "recovered": ("Recovered", "warn"),
    "deleting_original": ("Deleting original", "warn"),
    "original_deleted": ("Original deleted", "current"),
    "deletion_failed": ("Deletion failed", "missing"),
}


def execution_state_label(state):
    """Label and badge kind for one execution job state."""

    return EXECUTION_STATE_LABELS.get(
        state, (state or "Unknown", "unknown")
    )


def predicted_savings_to_dict(predicted):
    """
    Presentation-safe predicted-savings snapshot. Compatibility-only
    operations (no predicted storage saving) are represented honestly
    rather than as a zero figure.
    """

    payload = dict(predicted or {})

    if not payload:

        return None

    saved_bytes = payload.get("predicted_saved_bytes")

    return {
        "predicted_saved_bytes": saved_bytes,
        "predicted_saved_size": (
            format_bytes(saved_bytes)
            if saved_bytes is not None
            else None
        ),
        "predicted_percent": payload.get("predicted_percent"),
        "predicted_saving_text": (
            format_percent(payload.get("predicted_percent"))
            if payload.get("predicted_percent") is not None
            else None
        ),
        "basis": payload.get("basis"),
        "confidence": payload.get("confidence"),
        "compatibility_only": bool(
            payload.get("compatibility_only")
        ),
    }


def measured_savings_to_dict(measured):
    """
    Presentation-safe measured-savings snapshot derived from actual
    source/result observations.
    """

    payload = dict(measured or {})

    if not payload:

        return None

    saved_bytes = payload.get("measured_saved_bytes")

    return {
        "measured_saved_bytes": saved_bytes,
        "measured_saved_size": (
            format_bytes(abs(saved_bytes))
            if saved_bytes is not None
            else None
        ),
        "measured_percent": payload.get("measured_percent"),
        "measured_saving_text": (
            format_percent(payload.get("measured_percent"))
            if payload.get("measured_percent") is not None
            else None
        ),
        "source_size_bytes": payload.get("source_size_bytes"),
        "result_size_bytes": payload.get("result_size_bytes"),
        "source_observation_id": payload.get(
            "source_observation_id"
        ),
        "result_observation_id": payload.get(
            "result_observation_id"
        ),
    }


def transformation_to_dict(transformation):
    """
    Presentation-safe requested-transformation snapshot. Shows the
    operation, its source, and the selected propositions/parameters.
    """

    payload = dict(transformation or {})

    if not payload:

        return None

    propositions = [
        {
            "proposition": p.get("proposition"),
            "current_state": p.get("current_state"),
            "target_state": p.get("target_state"),
            "parameters": dict(p.get("parameters") or {}),
        }
        for p in (payload.get("propositions") or [])
        if isinstance(p, dict)
    ]

    return {
        "operation": payload.get("operation"),
        "source": payload.get("source"),
        "recommendation_id": payload.get("recommendation_id"),
        "propositions": propositions,
        "preserve_resolution": bool(
            payload.get("preserve_resolution", True)
        ),
        "preserve_hdr": bool(payload.get("preserve_hdr", True)),
        "audio_handling": payload.get("audio_handling"),
        "parameters": dict(payload.get("parameters") or {}),
    }


# Durable recommendation lifecycle states mapped for presentation.
# The lifecycle is owned by the recommendation records; this only
# maps the persisted state value to a display label and badge kind.
RECOMMENDATION_STATE_LABELS = {
    "proposed": ("Proposed", "stale"),
    "accepted": ("Accepted", "warn"),
    "rejected": ("Rejected", "missing"),
    "queued": ("Queued", "warn"),
    "executing": ("Executing", "warn"),
    "completed": ("Completed", "current"),
    "failed": ("Failed", "missing"),
}


def recommendation_state_label(state):
    """Label and badge kind for one recommendation record state."""

    return RECOMMENDATION_STATE_LABELS.get(
        state, (state or "Unknown", "unknown")
    )


def recommendation_record_to_dict(record):
    """
    Serialize one durable RecommendationRecord (the historical
    result AS PRODUCED BY ITS RUN). All fields are shown verbatim;
    nothing is re-derived.
    """

    label, kind = recommendation_state_label(record.state)

    return {
        "id": record.id,
        "media_id": record.media_id,
        "analysis_run_id": record.analysis_run_id,
        "file_observation_id": record.file_observation_id,
        "opportunity": record.opportunity,
        "opportunity_level": record.opportunity_level,
        "opportunity_score": record.opportunity_score,
        "confidence": record.confidence,
        "confidence_percent": format_confidence(
            record.confidence
        ),
        "estimated_saving_percent": (
            record.estimated_saving_percent
        ),
        "saving_percent": format_percent(
            record.estimated_saving_percent
        ),
        "estimated_saved_bytes": record.estimated_saved_bytes,
        "estimated_saved_size": format_bytes(
            record.estimated_saved_bytes
        ),
        "risk": record.risk,
        "summary": record.summary,
        "priority_score": record.priority_score,
        "rank_at_presentation": record.rank_at_presentation,
        "components": dict(record.components or {}),
        "rationale": list(record.rationale or []),
        "contributing_rules": list(
            record.contributing_rules or []
        ),
        "intelligence_identity": record.intelligence_identity,
        "state": record.state,
        "state_label": label,
        "state_badge": kind,
        "execution_job_id": record.execution_job_id,
        "created_at": format_timestamp(record.created_at),
        "updated_at": format_timestamp(record.updated_at),
    }


def recommendation_events_to_dict(events):
    """Serialize an append-only recommendation event ledger."""

    serialized = []

    for event in events:

        label, kind = recommendation_state_label(
            event.get("new_state")
        )

        serialized.append(
            {
                "event_type": event.get("event_type"),
                "previous_state": event.get("previous_state"),
                "new_state": event.get("new_state"),
                "new_state_label": label,
                "new_state_badge": kind,
                "execution_job_id": event.get(
                    "execution_job_id"
                ),
                "actor": event.get("actor"),
                "detail": event.get("detail"),
                "created_at": format_timestamp(
                    event.get("created_at")
                ),
            }
        )

    return serialized


# ---------------------------------------------------------
# Model serializers
# ---------------------------------------------------------


def lineage_to_dict(lineage):
    return {
        "id": lineage.id,
        "file_path": lineage.file_path,
        "file_name": lineage.file_name,
        "status": lineage.status,
        "file_size_bytes": lineage.file_size_bytes,
    }


def media_analysis_to_dict(record):
    if record is None:
        return None

    return {
        "analysis_run_id": record.analysis_run_id,
        "resolution": record.resolution,
        "video_codec": record.video_codec,
        "duration": record.duration,
        "bitrate": record.bitrate,
        "audio_tracks": record.audio_tracks,
        "is_hdr": record.is_hdr,
        "container": record.container,
        "analysed_at": format_timestamp(record.analysed_at),
    }


def lineage_status_to_dict(entry):
    effective_media_status = entry.media.status

    if entry.reason == "media_missing":
        effective_media_status = "missing"
    elif entry.reason == "filesystem_unavailable":
        effective_media_status = "unavailable"

    base = {
        "media": lineage_to_dict(entry.media),
        "media_status": effective_media_status,
        "reason": entry.reason,
        "analysis_required": entry.analysis_required,
        "incomplete_run_states": list(
            entry.incomplete_run_states
        ),
        "valid_run_id": entry.valid_run_id,
        "opportunity": entry.opportunity,
        "opportunity_score": entry.opportunity_score,
        "confidence": entry.confidence,
        "estimated_saving_percent": (
            entry.estimated_saving_percent
        ),
        "risk": entry.risk,
        "technical_facts": media_analysis_to_dict(
            entry.technical_facts
        ),
        "historical_run_count": entry.historical_run_count,
    }

    label, badge = status_label(base)

    base["status_label"] = label
    base["status_badge"] = badge

    return base


def library_summary_to_dict(summary):
    return {
        "total_active_lineages": summary.total_active_lineages,
        "total_missing_lineages": summary.total_missing_lineages,
        "lineages_with_valid_analysis": (
            summary.lineages_with_valid_analysis
        ),
        "lineages_requiring_analysis": (
            summary.lineages_requiring_analysis
        ),
        "opportunity_count": summary.opportunity_count,
        "total_library_bytes": summary.total_library_bytes,
        "total_estimated_saved_bytes": (
            summary.total_estimated_saved_bytes
        ),
        "last_scanned_at": format_timestamp(
            summary.last_scanned_at
        ),
        # Display-formatted mirrors for templates
        "total_library_size": format_bytes(
            summary.total_library_bytes
        ),
        "total_estimated_saved_size": format_bytes(
            summary.total_estimated_saved_bytes
        ),
    }


def scan_meta_to_dict(meta):
    return {
        "last_scanned_at": format_timestamp(
            meta.last_scanned_at
        ),
        "active_lineage_count": meta.active_lineage_count,
        "missing_lineage_count": meta.missing_lineage_count,
    }


def standing_decision_to_dict(decision):
    return {
        "id": decision.id,
        "media_id": decision.media_id,
        "proposition": decision.proposition,
        "state": decision.state,
        "actor": decision.actor,
        "reason": decision.reason,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
    }

def candidate_to_dict(candidate):
    return {
        "media_id": candidate.media_id,
        "file_path": candidate.file_path,
        "file_name": candidate.file_name,
        "opportunity": candidate.opportunity,
        "opportunity_level": candidate.opportunity_level,
        "priority_label": candidate.priority_label,
        "opportunity_score": candidate.opportunity_score,
        "confidence": candidate.confidence,
        "estimated_saving_percent": (
            candidate.estimated_saving_percent
        ),
        "file_size_bytes": candidate.file_size_bytes,
        "estimated_saved_bytes": candidate.estimated_saved_bytes,
        "risk": candidate.risk,
        "benefit": candidate.benefit,
        "cost": candidate.cost,
        "standing_suppressed_propositions": list(
            getattr(
                candidate,
                "standing_suppressed_propositions",
                (),
            )
            or ()
        ),
        # Display-formatted mirrors
        "file_size": format_bytes(candidate.file_size_bytes),
        "estimated_saved_size": format_bytes(
            candidate.estimated_saved_bytes
        ),
        "saving_percent": format_percent(
            candidate.estimated_saving_percent
        ),
        "confidence_percent": format_confidence(
            candidate.confidence
        ),
        "change_summary": change_summary_to_dict(
            getattr(candidate, "signals", ()),
            suppressed_propositions=tuple(
                sorted(
                    {
                        *(
                            getattr(
                                candidate,
                                "suppressed_propositions",
                                (),
                            )
                            or ()
                        ),
                        *(
                            getattr(
                                candidate,
                                "standing_suppressed_propositions",
                                (),
                            )
                            or ()
                        ),
                    }
                )
            ),
            estimated_saved_bytes=(
                candidate.estimated_saved_bytes
            ),
            estimated_saving_percent=(
                candidate.estimated_saving_percent
            ),
        ),
    }

# ---------------------------------------------------------
# Phase 1 change summary (presentation derivation, no new intelligence)
#
# Derives the proposed transformation from the persisted decision
# signals carried verbatim on the candidate read model. This is
# presentation formatting of data the system already persists; no
# savings are computed here and no intelligence is recomputed.
# ---------------------------------------------------------

CHANGE_DOMAIN_LABELS = {
    "codec_rule": "Video codec",
    "bitrate_rule": "Video bitrate",
    "resolution_rule": "Resolution",
    "audio_rule": "Audio",
    "container_rule": "Container",
    "hdr_rule": "HDR",
    "source_rule": "Source",
}

STORAGE_BENEFITS = frozenset({"small", "moderate", "substantial"})


def _surviving_signals(signals, suppressed_propositions):
    suppressed = set(suppressed_propositions or ())

    survivors = []

    for signal in signals:

        if getattr(signal, "direction", "") not in (
            "optimize",
            "remux",
        ):
            continue

        proposition = getattr(signal, "proposition", "") or ""

        if proposition and proposition in suppressed:
            continue

        survivors.append(signal)

    return survivors


def _signal_line(signal):
    current = getattr(signal, "current_state", None)
    target = getattr(signal, "target_state", None)

    if current is None and target is None:
        return None

    return {
        "domain": CHANGE_DOMAIN_LABELS.get(
            getattr(signal, "rule", ""),
            (getattr(signal, "rule", "") or "Change")
            .replace("_", " ")
            .title(),
        ),
        "current": current,
        "target": target,
        "benefit": getattr(signal, "benefit", "none"),
        "risk": getattr(signal, "risk", "unknown"),
        "reason": getattr(signal, "reason", ""),
    }


def _signal_one_liner(signal):
    rule = getattr(signal, "rule", "")
    current = getattr(signal, "current_state", None)
    target = getattr(signal, "target_state", None)

    if not target:
        return None

    if rule == "codec_rule":
        return f"Convert the video from {current} to {target}."
    if rule == "bitrate_rule":
        return f"Reduce the video bitrate from {current} to {target}."
    if rule == "resolution_rule":
        return f"Reduce the resolution from {current} to {target}."
    if rule == "audio_rule":
        return f"Change the audio from {current} to {target}."
    if rule == "container_rule":
        return f"Remux the file from the {current} container to {target}."
    if rule == "hdr_rule":
        return f"Change HDR handling from {current} to {target}."
    return f"Change {current} to {target}."


def change_summary_to_dict(
    signals,
    *,
    suppressed_propositions=(),
    estimated_saved_bytes=None,
    estimated_saving_percent=None,
):
    """
    A derived change summary over the persisted surviving proposition
    signals. Honest about what is known and what is not:

    - a target value is only shown when the signal actually carries it
    - storage savings are shown only when a storage-bearing
      proposition survives; compatibility-only changes (container
      remux) are labelled as such and never present a savings figure
    - savings are always labelled as estimates from the current
      analysis heuristic, never as measured results
    """

    survivors = _surviving_signals(
        signals,
        suppressed_propositions,
    )

    if not survivors:

        return {
            "available": False,
            "lines": [],
            "one_liner": None,
            "has_storage_claim": False,
            "compatibility_only": False,
            "savings": None,
        }

    lines = [
        line
        for line in (
            _signal_line(signal) for signal in survivors
        )
        if line is not None
    ]

    one_liner = None

    for signal in sorted(
        survivors,
        key=lambda item: getattr(item, "opportunity_score", 0.0),
        reverse=True,
    ):
        one_liner = _signal_one_liner(signal)
        if one_liner is not None:
            break

    has_storage = any(
        (
            getattr(signal, "benefit", "none") or "none"
        ) in STORAGE_BENEFITS
        for signal in survivors
    )

    has_compatibility = any(
        getattr(signal, "benefit", "") == "compatibility"
        or (
            getattr(signal, "evidence", None) or {}
        ).get("storage_benefit") == "none"
        for signal in survivors
    )

    compatibility_only = has_compatibility and not has_storage

    savings = None

    if has_storage and not compatibility_only:

        savings = {
            "estimated_saved_bytes": estimated_saved_bytes,
            "saved_size": format_bytes(estimated_saved_bytes),
            "saving_percent": format_percent(
                estimated_saving_percent
            ),
            "note": (
                "Estimate from the current analysis heuristic, "
                "not a measured result."
            ),
        }

    return {
        "available": True,
        "lines": lines,
        "one_liner": one_liner,
        "has_storage_claim": has_storage,
        "compatibility_only": compatibility_only,
        "savings": savings,
    }


def storage_summary_to_dict(summary):
    return {
        "total_library_bytes": summary.total_library_bytes,
        "opportunity_count": summary.opportunity_count,
        "total_estimated_saved_bytes": (
            summary.total_estimated_saved_bytes
        ),
        "total_estimated_saving_percent": (
            summary.total_estimated_saving_percent
        ),
        "by_opportunity": [
            {
                "opportunity": category.opportunity,
                "count": category.count,
                "total_saved_bytes": category.total_saved_bytes,
                "total_size_bytes": category.total_size_bytes,
                "saved_size": format_bytes(
                    category.total_saved_bytes
                ),
                "saving_percent": format_percent(
                    (
                        category.total_saved_bytes
                        / category.total_size_bytes
                        * 100
                    )
                    if category.total_size_bytes > 0
                    else 0.0
                ),
            }
            for category in summary.by_opportunity
        ],
        # Display-formatted mirrors
        "total_library_size": format_bytes(
            summary.total_library_bytes
        ),
        "total_estimated_saved_size": format_bytes(
            summary.total_estimated_saved_bytes
        ),
        "total_saving_percent": format_percent(
            summary.total_estimated_saving_percent
        ),
    }


# ---------------------------------------------------------
# Sprint 7 library-intelligence serializers
# ---------------------------------------------------------


def library_statistics_to_dict(statistics):
    return {
        "total_lineages": statistics.total_lineages,
        "active_lineages": statistics.active_lineages,
        "missing_lineages": statistics.missing_lineages,
        "analysed_lineages": statistics.analysed_lineages,
        "unanalysed_lineages": statistics.unanalysed_lineages,
        "stale_analyses": statistics.stale_analyses,
        "changed_media": statistics.changed_media,
        "changed_since_analysis": (
            statistics.changed_since_analysis
        ),
        "analysis_coverage_percent": (
            statistics.analysis_coverage_percent
        ),
        "opportunity_count": statistics.opportunity_count,
        "total_library_bytes": statistics.total_library_bytes,
        "total_estimated_saved_bytes": (
            statistics.total_estimated_saved_bytes
        ),
        # Display-formatted mirrors
        "coverage_percent": format_percent(
            statistics.analysis_coverage_percent
        ),
        "total_library_size": format_bytes(
            statistics.total_library_bytes
        ),
        "total_estimated_saved_size": format_bytes(
            statistics.total_estimated_saved_bytes
        ),
    }


def storage_consumption_to_dict(consumption):
    return {
        "total_library_bytes": consumption.total_library_bytes,
        "active_lineage_count": consumption.active_lineage_count,
        "missing_lineage_count": consumption.missing_lineage_count,
        "analysed_bytes": consumption.analysed_bytes,
        "unanalysed_bytes": consumption.unanalysed_bytes,
        "missing_bytes": consumption.missing_bytes,
        "opportunity_bytes": consumption.opportunity_bytes,
        "opportunity_saved_bytes": consumption.opportunity_saved_bytes,
        "opportunity_saved_percent": (
            consumption.opportunity_saved_percent
        ),
        "library_savings_percent": (
            consumption.library_savings_percent
        ),
        # Display-formatted mirrors
        "total_library_size": format_bytes(
            consumption.total_library_bytes
        ),
        "analysed_size": format_bytes(consumption.analysed_bytes),
        "unanalysed_size": format_bytes(
            consumption.unanalysed_bytes
        ),
        "missing_size": format_bytes(consumption.missing_bytes),
        "opportunity_size": format_bytes(
            consumption.opportunity_bytes
        ),
        "opportunity_saved_size": format_bytes(
            consumption.opportunity_saved_bytes
        ),
        "opportunity_saved_percent_text": format_percent(
            consumption.opportunity_saved_percent
        ),
        "library_savings_percent_text": format_percent(
            consumption.library_savings_percent
        ),
    }


def savings_distribution_to_dict(distribution):
    return {
        "total_opportunities": distribution.total_opportunities,
        "total_size_bytes": distribution.total_size_bytes,
        "total_saved_bytes": distribution.total_saved_bytes,
        "total_saved_size": format_bytes(
            distribution.total_saved_bytes
        ),
        "buckets": [
            {
                "label": bucket.label,
                "lower_percent": bucket.lower_percent,
                "upper_percent": bucket.upper_percent,
                "count": bucket.count,
                "total_size_bytes": bucket.total_size_bytes,
                "total_saved_bytes": bucket.total_saved_bytes,
                "saved_size": format_bytes(
                    bucket.total_saved_bytes
                ),
            }
            for bucket in distribution.buckets
        ],
    }


def confidence_distribution_to_dict(distribution):
    return {
        "total_opportunities": distribution.total_opportunities,
        "total_size_bytes": distribution.total_size_bytes,
        "total_saved_bytes": distribution.total_saved_bytes,
        "total_saved_size": format_bytes(
            distribution.total_saved_bytes
        ),
        "buckets": [
            {
                "label": bucket.label,
                "lower": bucket.lower,
                "upper": bucket.upper,
                "count": bucket.count,
                "total_size_bytes": bucket.total_size_bytes,
                "total_saved_bytes": bucket.total_saved_bytes,
                "saved_size": format_bytes(
                    bucket.total_saved_bytes
                ),
            }
            for bucket in distribution.buckets
        ],
    }


def library_health_to_dict(health):
    return {
        "health_score": health.health_score,
        "status": health.status,
        "analysis_coverage": health.analysis_coverage,
        "coverage_status": health.coverage_status,
        "stale_ratio": health.stale_ratio,
        "stale_status": health.stale_status,
        "opportunity_ratio": health.opportunity_ratio,
        "opportunity_status": health.opportunity_status,
        "indicators": list(health.indicators),
        # Display-formatted mirrors
        "health_score_percent": f"{health.health_score * 100:.0f}%",
        "coverage_percent": format_percent(
            health.analysis_coverage * 100
        ),
        "stale_percent": format_percent(health.stale_ratio * 100),
        "opportunity_percent": format_percent(
            health.opportunity_ratio * 100
        ),
    }


def library_lineage_status_to_dict(entry):
    return {
        "media_id": entry.media_id,
        "media_status": entry.media_status,
        "validity_reason": entry.validity_reason,
        "analysis_required": entry.analysis_required,
        "is_analysed": entry.is_analysed,
        "is_stale": entry.is_stale,
        "is_changed_media": entry.is_changed_media,
        "is_changed_since_analysis": (
            entry.is_changed_since_analysis
        ),
        "valid_run_id": entry.valid_run_id,
        "historical_run_count": entry.historical_run_count,
        "file_size_bytes": entry.file_size_bytes,
        "file_name": entry.file_name,
    }


# ---------------------------------------------------------
# Sprint 7 recommendation-prioritisation serializers
# ---------------------------------------------------------


def prioritised_recommendation_to_dict(item):
    candidate = item.candidate
    components = item.components

    return {
        "rank": item.rank,
        "media_id": candidate.media_id,
        "file_path": candidate.file_path,
        "file_name": candidate.file_name,
        "opportunity": candidate.opportunity,
        "opportunity_level": candidate.opportunity_level,
        "priority_label": candidate.priority_label,
        "opportunity_score": candidate.opportunity_score,
        "confidence": candidate.confidence,
        "estimated_saving_percent": (
            candidate.estimated_saving_percent
        ),
        "file_size_bytes": candidate.file_size_bytes,
        "estimated_saved_bytes": candidate.estimated_saved_bytes,
        "risk": candidate.risk,
        "benefit": candidate.benefit,
        "cost": candidate.cost,
        "standing_suppressed_propositions": list(
            getattr(
                candidate,
                "standing_suppressed_propositions",
                (),
            )
            or ()
        ),
        "priority_score": item.priority_score,
        "components": {
            "score_component": components.score_component,
            "savings_bytes_component": (
                components.savings_bytes_component
            ),
            "confidence_component": (
                components.confidence_component
            ),
            "risk_penalty": components.risk_penalty,
            "calibrated_confidence": (
                components.calibrated_confidence
            ),
            "risk_value": components.risk_value,
            "cost_benefit_ratio": components.cost_benefit_ratio,
        },
        "rationale": list(item.rationale),
        # Display-formatted mirrors
        "priority_score_text": f"{item.priority_score:.4f}",
        "file_size": format_bytes(candidate.file_size_bytes),
        "estimated_saved_size": format_bytes(
            candidate.estimated_saved_bytes
        ),
        "saving_percent": format_percent(
            candidate.estimated_saving_percent
        ),
        "confidence_percent": format_confidence(
            candidate.confidence
        ),
        "calibrated_confidence_percent": format_confidence(
            components.calibrated_confidence
        ),
        "change_summary": change_summary_to_dict(
            getattr(candidate, "signals", ()),
            suppressed_propositions=tuple(
                sorted(
                    {
                        *(
                            getattr(
                                candidate,
                                "suppressed_propositions",
                                (),
                            )
                            or ()
                        ),
                        *(
                            getattr(
                                candidate,
                                "standing_suppressed_propositions",
                                (),
                            )
                            or ()
                        ),
                    }
                )
            ),
            estimated_saved_bytes=(
                candidate.estimated_saved_bytes
            ),
            estimated_saving_percent=(
                candidate.estimated_saving_percent
            ),
        ),
    }


def recommendation_set_to_dict(recommendation_set):
    return {
        "name": recommendation_set.name,
        "description": recommendation_set.description,
        "count": recommendation_set.count,
        "total_size_bytes": recommendation_set.total_size_bytes,
        "total_saved_bytes": recommendation_set.total_saved_bytes,
        "total_saved_size": format_bytes(
            recommendation_set.total_saved_bytes
        ),
        "recommendations": [
            prioritised_recommendation_to_dict(item)
            for item in recommendation_set.recommendations
        ],
    }


def savings_projection_to_dict(projection):
    return {
        "total_opportunities": projection.total_opportunities,
        "total_size_bytes": projection.total_size_bytes,
        "total_saved_bytes": projection.total_saved_bytes,
        "total_saving_percent": projection.total_saving_percent,
        "by_opportunity": [
            {
                "opportunity": category.opportunity,
                "count": category.count,
                "total_size_bytes": category.total_size_bytes,
                "total_saved_bytes": category.total_saved_bytes,
                "saved_size": format_bytes(
                    category.total_saved_bytes
                ),
            }
            for category in projection.by_opportunity
        ],
        "top_n_projection": [
            {
                "rank": rank,
                "saved_bytes": saved,
                "cumulative_saved_bytes": cumulative,
                "cumulative_saved_size": format_bytes(cumulative),
            }
            for rank, saved, cumulative in (
                projection.top_n_projection
            )
        ],
        # Display-formatted mirrors
        "total_saved_size": format_bytes(
            projection.total_saved_bytes
        ),
        "total_saving_percent_text": format_percent(
            projection.total_saving_percent
        ),
    }


def run_to_dict(run):
    label, badge = run_status_label(run.status)

    return {
        "id": run.id,
        "media_id": run.media_id,
        "file_observation_id": run.file_observation_id,
        "configuration_snapshot_id": (
            run.configuration_snapshot_id
        ),
        "status": run.status,
        "status_label": label,
        "status_badge": badge,
        "intelligence_identity": getattr(
            run, "intelligence_identity", None
        ),
        "started_at": format_timestamp(run.started_at),
        "completed_at": format_timestamp(run.completed_at),
        "error_message": run.error_message,
        "created_at": format_timestamp(run.created_at),
    }


def run_summary_to_dict(summary):
    data = run_to_dict(summary.run)

    data["media_name"] = summary.media_name
    data["media_path"] = summary.media_path
    data["media_status"] = summary.media_status

    return data


def observation_to_dict(observation):
    return {
        "id": observation.id,
        "observed_at": format_timestamp(
            observation.observed_at
        ),
        "file_path": observation.file_path,
        "file_name": observation.file_name,
        "file_extension": observation.file_extension,
        "size_bytes": observation.size_bytes,
        "size": format_bytes(observation.size_bytes),
        "file_mtime_ns": observation.file_mtime_ns,
        "filesystem_device": observation.filesystem_device,
        "filesystem_inode": observation.filesystem_inode,
        "sha256_hash": observation.sha256_hash,
        "identity_match_method": (
            observation.identity_match_method
        ),
    }


def observation_history_to_dict(history):
    return {
        "media": lineage_to_dict(history.media),
        "observations": [
            {
                "observation": observation_to_dict(
                    entry.observation
                ),
                "analysis_runs": [
                    run_to_dict(run)
                    for run in entry.analysis_runs
                ],
            }
            for entry in history.observations
        ],
    }


def expert_result_to_dict(result):
    domains = {}

    if result.expert_data:
        for domain, analysis in (
            result.expert_data.domains.items()
        ):
            domains[domain] = {
                "selected_value": analysis.selected_value,
                "confidence": analysis.confidence,
                "agreement": (
                    analysis.agreement.value
                    if analysis.agreement is not None
                    else None
                ),
                "has_conflict": analysis.has_conflict,
                "uncertainty": analysis.uncertainty,
            }

    return {
        "expert_name": result.expert_name,
        "confidence": result.confidence,
        "confidence_percent": format_confidence(
            result.confidence
        ),
        "observations": result.observations,
        "notes": result.notes,
        "domains": domains,
    }


def decision_signal_to_dict(signal):
    return {
        "rule": signal.rule,
        "direction": signal.direction,
        "proposition": signal.proposition,
        "current_state": signal.current_state,
        "target_state": signal.target_state,
        "benefit": signal.benefit,
        "cost": signal.cost,
        "risk": signal.risk,
        "reason": signal.reason,
        "opportunity_score": signal.opportunity_score,
        "confidence": signal.confidence,
        "confidence_percent": format_confidence(
            signal.confidence
        ),
        "notes": signal.notes,
        "evidence": signal.evidence,
        "provenance": signal.provenance,
    }


def evidence_to_dict(item):
    return {
        "domain": item.domain,
        "value": item.value,
        "confidence": item.confidence,
        "confidence_percent": format_confidence(
            item.confidence
        ),
        "source": item.source,
        "evidence_id": item.evidence_id,
        "matched_text": item.matched_text,
    }


def assessment_to_dict(assessment):
    if assessment is None:
        return None

    return {
        "opportunity": assessment.opportunity,
        "opportunity_level": assessment.opportunity_level,
        "priority_label": assessment.priority_label,
        "opportunity_score": assessment.opportunity_score,
        "confidence": assessment.confidence,
        "confidence_percent": format_confidence(
            assessment.confidence
        ),
        "estimated_saving_percent": (
            assessment.estimated_saving_percent
        ),
        "saving_percent": format_percent(
            assessment.estimated_saving_percent
        ),
        "expected_saved_bytes": assessment.expected_saved_bytes,
        "benefit": assessment.benefit,
        "cost": assessment.cost,
        "risk": assessment.risk,
        "evidence": assessment.evidence,
        "reasoning": assessment.reasoning,
        "preservation_reasons": assessment.preservation_reasons,
        "suppressed_signals": assessment.suppressed_signals,
        "contributing_rules": assessment.contributing_rules,
        "constraints": list(
            getattr(assessment, "constraints", ()) or ()
        ),
    }


def provenance_to_dict(provenance):
    return {
        "analysis_run": run_to_dict(provenance.analysis_run),
        "knowledge_usage": [
            {
                "knowledge_set_id": usage.knowledge_set_id,
            }
            for usage in provenance.knowledge_usage
        ],
        "evidence": [
            evidence_to_dict(item)
            for item in provenance.evidence
        ],
        "expert_results": [
            expert_result_to_dict(result)
            for result in provenance.expert_results
        ],
        "decision_signals": [
            decision_signal_to_dict(signal)
            for signal in provenance.decision_signals
        ],
        "opportunity_assessment": assessment_to_dict(
            provenance.opportunity_assessment
        ),
    }


def explanation_to_dict(explanation):
    return {
        "summary": explanation.summary,
        "expert_contributions": list(
            explanation.expert_contributions
        ),
        "evidence_summary": list(explanation.evidence_summary),
        "decision_summary": list(explanation.decision_summary),
        "knowledge_summary": list(explanation.knowledge_summary),
        "confidence_summary": explanation.confidence_summary,
    }


def comparison_to_dict(comparison):
    return {
        "run_a": run_to_dict(comparison.run_a),
        "run_b": run_to_dict(comparison.run_b),
        "media_id": comparison.media_id,
        "same_observation": comparison.same_observation,
        "observation_a": (
            observation_to_dict(comparison.observation_a)
            if comparison.observation_a is not None
            else None
        ),
        "observation_b": (
            observation_to_dict(comparison.observation_b)
            if comparison.observation_b is not None
            else None
        ),
        "differences": [
            {
                "category": diff.category,
                "key": diff.key,
                "before": diff.before,
                "after": diff.after,
                "summary": diff.summary,
            }
            for diff in comparison.differences
        ],
    }


# ---------------------------------------------------------
# Organisation proposals (Sprint 13)
# ---------------------------------------------------------


# Durable organisation proposal lifecycle states mapped for
# presentation. The lifecycle is owned by the organisation
# records; this only maps the persisted state value to a display
# label and badge kind.
ORGANISATION_STATE_LABELS = {
    "proposed": ("Proposed", "stale"),
    "accepted": ("Accepted", "current"),
    "rejected": ("Rejected", "missing"),
    "superseded": ("Superseded", "unknown"),
}

ORGANISATION_INTENT_LABELS = {
    "move_destination": ("Move destination", "opportunity"),
    "rename": ("Rename", "warn"),
    "group_with": ("Grouping", "current"),
    "flag_duplicate": ("Duplicate candidate", "missing"),
    "order_within_group": ("Ordering", "unknown"),
}


def organisation_state_label(state):
    """Label and badge kind for one organisation proposal state."""

    return ORGANISATION_STATE_LABELS.get(
        state, (state or "Unknown", "unknown")
    )


def organisation_intent_label(intent):
    """Label and badge kind for one proposal intent type."""

    return ORGANISATION_INTENT_LABELS.get(
        intent, (intent or "Unknown", "unknown")
    )


def organisation_decision_run_to_dict(decision_run):
    """
    Serialize one decision-run anchor verbatim: the exact rule
    versions, policy values and digest that produced its
    proposals. Nothing is re-derived.
    """

    return {
        "id": decision_run.id,
        "status": decision_run.status,
        "library_roots": list(
            decision_run.library_roots or []
        ),
        "rule_versions": dict(
            decision_run.rule_versions or {}
        ),
        "policy_values": dict(
            decision_run.policy_values or {}
        ),
        "git_revision": decision_run.git_revision,
        "identity_digest": decision_run.identity_digest,
        "identity_digest_short": (
            decision_run.identity_digest[:16]
            if decision_run.identity_digest
            else None
        ),
        "lineages_considered": (
            decision_run.lineages_considered
        ),
        "proposals_created": decision_run.proposals_created,
        "hash_coverage_total": (
            decision_run.hash_coverage_total
        ),
        "hash_coverage_hashed": (
            decision_run.hash_coverage_hashed
        ),
        "created_at": format_timestamp(
            decision_run.created_at
        ),
    }


def organisation_proposal_to_dict(proposal):
    """
    Serialize one durable organisation proposal AS PRODUCED BY
    ITS DECISION RUN. All fields are shown verbatim; nothing is
    re-derived from current rules.
    """

    state_label, state_badge = organisation_state_label(
        proposal.state
    )

    intent_label, intent_badge = organisation_intent_label(
        proposal.intent
    )

    return {
        "id": proposal.id,
        "decision_run_id": proposal.decision_run_id,
        "media_id": proposal.media_id,
        "related_media_id": proposal.related_media_id,
        "intent": proposal.intent,
        "intent_label": intent_label,
        "intent_badge": intent_badge,
        "proposed_destination": proposal.proposed_destination,
        "proposed_name": proposal.proposed_name,
        "confidence": proposal.confidence,
        "confidence_percent": format_confidence(
            proposal.confidence
        ),
        "risk": proposal.risk,
        "rationale": list(proposal.rationale or []),
        "evidence": dict(proposal.evidence or {}),
        "intelligence_identity": (
            proposal.intelligence_identity
        ),
        "state": proposal.state,
        "state_label": state_label,
        "state_badge": state_badge,
        "created_at": format_timestamp(proposal.created_at),
        "updated_at": format_timestamp(proposal.updated_at),
    }


def organisation_events_to_dict(events):
    """Serialize an append-only organisation event ledger."""

    serialized = []

    for event in events:

        label, kind = organisation_state_label(
            event.get("new_state")
        )

        serialized.append(
            {
                "event_type": event.get("event_type"),
                "previous_state": event.get("previous_state"),
                "new_state": event.get("new_state"),
                "new_state_label": label,
                "new_state_badge": kind,
                "actor": event.get("actor"),
                "detail": event.get("detail"),
                "created_at": format_timestamp(
                    event.get("created_at")
                ),
            }
        )

    return serialized


# ---------------------------------------------------------
# Phase 7 organisation execution presentation
# ---------------------------------------------------------


# Presentation mapping over the organisation execution state machine.
# The lifecycle itself is owned by the execution authority; this only
# maps each recorded state to a display label and badge kind.
ORGANISATION_EXECUTION_STATE_LABELS = {
    "proposed": ("Proposed", "stale"),
    "approved": ("Approved", "stale"),
    "precondition_verified": ("Preconditions verified", "warn"),
    "executing": ("Moving", "warn"),
    "verifying": ("Verifying", "warn"),
    "observation_persistence": ("Recording observation", "warn"),
    "provenance_persistence": ("Recording provenance", "warn"),
    "succeeded": ("Succeeded", "current"),
    "failed": ("Failed", "missing"),
    "interrupted": ("Interrupted", "warn"),
    "recovery_required": ("Recovery required", "missing"),
}


def organisation_execution_state_label(state):
    """Label and badge kind for one organisation execution state."""

    return ORGANISATION_EXECUTION_STATE_LABELS.get(
        state, (state or "Unknown", "unknown")
    )


def organisation_execution_to_dict(execution):
    """
    Serialize one durable organisation execution record verbatim.
    Presentation only; the lifecycle is owned by the execution
    authority.
    """

    state_label, state_badge = (
        organisation_execution_state_label(execution.state)
    )

    intent_label, intent_badge = organisation_intent_label(
        execution.intent
    )

    return {
        "id": execution.id,
        "proposal_id": execution.proposal_id,
        "decision_run_id": execution.decision_run_id,
        "media_id": execution.media_id,
        "intent": execution.intent,
        "intent_label": intent_label,
        "intent_badge": intent_badge,
        "source_path": execution.source_path,
        "source_observation_id": (
            execution.source_observation_id
        ),
        "source_size_bytes": execution.source_size_bytes,
        "source_mtime_ns": execution.source_mtime_ns,
        "destination_path": execution.destination_path,
        "state": execution.state,
        "state_label": state_label,
        "state_badge": state_badge,
        "error": execution.error,
        "result_observation_id": (
            execution.result_observation_id
        ),
        "continuity_id": execution.continuity_id,
        "actor": execution.actor,
        "created_at": format_timestamp(execution.created_at),
        "updated_at": format_timestamp(execution.updated_at),
    }


def organisation_execution_continuity_to_dict(entry):
    """
    Serialize one execution-authorised identity-continuity record:
    the exact observation linkage the authorised execution
    established.
    """

    return {
        "id": entry.get("id"),
        "execution_id": entry.get("execution_id"),
        "media_id": entry.get("media_id"),
        "source_observation_id": entry.get(
            "source_observation_id"
        ),
        "result_observation_id": entry.get(
            "result_observation_id"
        ),
        "authority": entry.get("authority"),
        "created_at": format_timestamp(
            entry.get("created_at")
        ),
    }


# ---------------------------------------------------------
# Phase 4 notifications + Phase 5 scan status serializers
# ---------------------------------------------------------


NOTIFICATION_LABELS = {
    "information": "Information",
    "success": "Success",
    "working": "Working",
    "attention": "Attention",
    "error": "Error",
    "neutral": "File change",
}


def notification_to_dict(notification):
    """
    Serialize one durable user notification.
    """

    links = {}

    if notification.media_id is not None:
        links["media"] = f"/media/{notification.media_id}"

    if notification.execution_job_id is not None:
        links["execution"] = (
            f"/executions/{notification.execution_job_id}"
        )

    if notification.recommendation_id is not None:
        links["recommendation"] = (
            f"/recommendations/{notification.recommendation_id}"
        )

    if notification.scan_id is not None:
        links["scan"] = "/scan"

    return {
        "id": notification.id,
        "category": notification.category,
        "category_label": NOTIFICATION_LABELS.get(
            notification.category,
            notification.category,
        ),
        "title": notification.title,
        "message": notification.message,
        "media_id": notification.media_id,
        "execution_job_id": notification.execution_job_id,
        "recommendation_id": notification.recommendation_id,
        "scan_id": notification.scan_id,
        "created_at": format_timestamp(
            notification.created_at
        ),
        "links": links,
    }


def _parse_utc(value):
    """
    Parse a stored SQLite UTC timestamp (CURRENT_TIMESTAMP) into a
    naive UTC datetime, so ETA arithmetic is timezone-consistent.
    """

    if not value:
        return None

    text = str(value).replace("T", " ")

    if "." in text:
        text = text.split(".")[0]

    try:
        return datetime.strptime(
            text,
            "%Y-%m-%d %H:%M:%S",
        )
    except ValueError:
        return None


def scan_status_to_dict(scan, now=None):
    """
    Honest scan-progress presentation.

    - discovery: the discovered denominator is unknown -> no
      percentage, no ETA (never fabricated)
    - analysing: percent and approximate ETA derive only from the
      durable per-file counts and elapsed time
    - completed / failed: the terminal state with final counts
    """

    if scan is None:
        return {"exists": False}

    if now is None:
        now = (
            datetime.now(timezone.utc)
            .replace(tzinfo=None)
        )

    status = scan.status

    if status == "running":
        phase = (
            "discovering"
            if not scan.files_discovered
            else "analysing"
        )
    else:
        phase = status

    discovered = scan.files_discovered or 0
    analysed = scan.files_analysed or 0
    reused = scan.files_reused or 0
    failed = scan.files_failed or 0
    skipped = scan.files_skipped or 0
    processed = analysed + reused + failed + skipped

    percent = None
    eta_seconds = None
    elapsed_seconds = None

    started = _parse_utc(scan.started_at)

    if started is not None:
        elapsed_seconds = int(
            max((now - started).total_seconds(), 0)
        )

    if phase == "analysing" and discovered > 0:

        percent = (
            round(processed / discovered * 100)
            if processed > 0
            else 0
        )

        remaining = discovered - processed

        analysis_started = _parse_utc(
            scan.analysis_started_at or scan.started_at
        )

        if (
            analysis_started is not None
            and processed > 0
            and remaining > 0
        ):

            elapsed = max(
                (now - analysis_started).total_seconds(),
                0.001,
            )

            rate = processed / elapsed

            eta_seconds = remaining / rate

    return {
        "exists": True,
        "id": scan.id,
        "target_scope": scan.target_scope,
        "status": status,
        "phase": phase,
        "started_at": format_timestamp(scan.started_at),
        "completed_at": format_timestamp(scan.completed_at),
        "analysis_started_at": format_timestamp(
            scan.analysis_started_at
        ),
        "files_discovered": discovered,
        "files_analysed": analysed,
        "files_reused": reused,
        "files_failed": failed,
        "files_skipped": skipped,
        "files_processed": processed,
        "percent": percent,
        "eta_seconds": (
            int(round(eta_seconds))
            if eta_seconds is not None
            else None
        ),
        "eta_approximate": True,
        "elapsed_seconds": elapsed_seconds,
        "error_message": scan.error_message,
    }


# ---------------------------------------------------------
# HTML escaping helper (used by templates)
# ---------------------------------------------------------


def esc(value):
    """HTML-escape a value for safe rendering."""

    if value is None:
        return ""

    return html.escape(str(value))


def now_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------
# Sprint 15 organisation scope actions, scope executions,
# file plans and preflight (presentation pass-throughs)
# ---------------------------------------------------------


def scope_action_to_dict(action):
    """
    Serialize one durable scope action record verbatim.
    Pure presentation; the lifecycle is owned by the
    organisation records.
    """

    label, kind = organisation_state_label(
        getattr(action, "state", None)
    )

    return {
        "id": getattr(action, "id", None),
        "decision_run_id": getattr(
            action, "decision_run_id", None
        ),
        "scope_path": getattr(action, "scope_path", ""),
        "action_type": getattr(action, "action_type", ""),
        "source_path": getattr(action, "source_path", ""),
        "destination_path": getattr(
            action, "destination_path", ""
        ),
        "descendant_manifest": [
            dict(item)
            for item in (
                getattr(action, "descendant_manifest", None)
                or []
            )
            if isinstance(item, dict)
        ],
        "strategy": getattr(action, "strategy", ""),
        "operation_count": getattr(
            action, "operation_count", 0
        ),
        "reasoning": list(
            getattr(action, "reasoning", None) or []
        ),
        "review_conditions": list(
            getattr(action, "review_conditions", None) or []
        ),
        "descendant_proposal_ids": list(
            getattr(action, "descendant_proposal_ids", None)
            or []
        ),
        "intelligence_identity": getattr(
            action, "intelligence_identity", None
        ),
        "state": getattr(action, "state", None),
        "state_label": label,
        "state_badge": kind,
        "created_at": format_timestamp(
            getattr(action, "created_at", None)
        ),
        "updated_at": format_timestamp(
            getattr(action, "updated_at", None)
        ),
    }


def scope_execution_to_dict(execution):
    """
    Serialize one durable scope execution record verbatim.
    Pure presentation; the lifecycle is owned by the
    organisation execution authority.
    """

    state_label, state_badge = (
        organisation_execution_state_label(
            getattr(execution, "state", None)
        )
    )

    return {
        "id": getattr(execution, "id", None),
        "scope_action_id": getattr(
            execution, "scope_action_id", None
        ),
        "decision_run_id": getattr(
            execution, "decision_run_id", None
        ),
        "action_type": getattr(
            execution, "action_type", ""
        ),
        "source_path": getattr(
            execution, "source_path", ""
        ),
        "destination_path": getattr(
            execution, "destination_path", ""
        ),
        "descendant_manifest": [
            dict(item)
            for item in (
                getattr(
                    execution,
                    "descendant_manifest",
                    None,
                )
                or []
            )
            if isinstance(item, dict)
        ],
        "state": getattr(execution, "state", None),
        "state_label": state_label,
        "state_badge": state_badge,
        "error": getattr(execution, "error", None),
        "descendants_completed": list(
            getattr(
                execution, "descendants_completed", None
            )
            or []
        ),
        "actor": getattr(execution, "actor", None),
        "created_at": format_timestamp(
            getattr(execution, "created_at", None)
        ),
        "updated_at": format_timestamp(
            getattr(execution, "updated_at", None)
        ),
    }


def file_plan_to_dict(plan):
    """
    Pass-through view of one planning FilePlan dict (as
    produced by FilePlan.to_dict()). The planning
    authority owns the content; this only normalises the
    container so HTML and JSON mirrors share it.
    """

    payload = dict(plan or {})

    for key in (
        "rules_applied",
        "mappings_applied",
        "reasoning",
    ):
        payload[key] = list(payload.get(key) or [])

    payload["mutation"] = dict(payload.get("mutation") or {})

    metadata = dict(payload.get("metadata_cited") or {})

    metadata["observation_ids"] = list(
        metadata.get("observation_ids") or []
    )

    payload["metadata_cited"] = metadata

    payload["association"] = dict(
        payload.get("association") or {}
    )

    return payload
