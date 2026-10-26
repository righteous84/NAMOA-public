"""Optimisation Preview application service (Phase 17).

Orchestrates non-destructive Optimisation Preview over the existing
recommendation, transformation, and execution authorities:

- recommendation contexts resolve through the existing queue,
  validity, and review authorities (never a second model);
- transformations resolve through TransformationService and the
  closed operation registry (never a second builder);
- segments reuse the registered argv builders through
  ``app.execution.ffmpeg.build_preview_argv``;
- artifacts live in the application-owned preview directory with
  ownership manifests and server-side lifecycle;
- Accept/Reject/Close route through the existing decision and
  approval boundaries with pinned-context revalidation.

Preview generates no library media state: no media_items, no
file_observations, no analysis_runs, no recommendations rows, and
no media_executions rows are created by generation itself. Only an
explicit Accept creates an execution job through the existing
approval boundary.
"""

import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.ffmpeg import (
    PreviewCancelled,
    PreviewTimeout,
    build_preview_argv,
    resolve_ffmpeg_binary,
    run_preview,
)
from app.execution.operations import (
    EXECUTABLE_OPERATIONS,
    OPERATION_CODEC_CONVERSION_MKV,
    get_operation,
)
from app.models.transformation import (
    SOURCE_RECOMMENDATION,
    SOURCE_USER_OVERRIDE,
)
from app.retention.assessment import (
    VERDICT_LOSS_ACKNOWLEDGEABLE,
    alternatives_for,
    assess as assess_retention,
    build_acknowledgement,
    check_approval as check_retention_approval,
)
from app.preview import artifacts
from app.preview.settings import (
    PreviewSettings,
    load_settings,
)


_PREVIEWS = {}

_PREVIEWS_LOCK = threading.Lock()


class PreviewError(ValueError):
    """A truthful Preview refusal or failure (user-facing message)."""


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def clear_preview_records():
    """Test support: drop every transient preview context."""

    with _PREVIEWS_LOCK:
        _PREVIEWS.clear()


def _store_context(context):
    with _PREVIEWS_LOCK:
        _PREVIEWS[context.token] = context


def _get_context(token):
    with _PREVIEWS_LOCK:
        return _PREVIEWS.get(str(token or ""))


def _drop_context(token):
    with _PREVIEWS_LOCK:
        _PREVIEWS.pop(str(token or ""), None)


def _active_tokens():
    with _PREVIEWS_LOCK:
        return [
            token
            for token, context in _PREVIEWS.items()
            if context.status in ("open", "generated", "failed")
        ]


@dataclass
class PreviewContext:
    """
    Transient preview session state (never persisted to the
    database).

    The pinned source version (observation id + file stat +
    analysis run id) is captured at resolution time. Generation
    and Accept both revalidate these pins against live state, so
    a changed file can never silently receive a stale preview or
    a stale approval.
    """

    token: str

    origin: str

    media_id: int

    file_path: str = ""

    file_name: str = ""

    suggestion_id: str | None = None

    recommendation_id: int | None = None

    run_id: int | None = None

    observation_id: int | None = None

    pinned_size_bytes: int | None = None

    pinned_mtime_ns: int | None = None

    transformation: dict = field(default_factory=dict)

    override: dict | None = None

    timestamp_seconds: float | None = None

    duration_seconds: float | None = None

    source_duration_seconds: float | None = None

    suggested_position_seconds: float | None = None

    source_audio_codecs: list = field(default_factory=list)

    sample_audio_codecs: list = field(default_factory=list)

    artifact_path: str | None = None

    manifest_path: str | None = None

    actual_duration_seconds: float | None = None

    status: str = "open"

    error: str | None = None

    created_at: str = ""

    retention: dict | None = None

    alternatives: list = field(default_factory=list)

    def to_view(self):
        """JSON-safe read model for handlers and templates."""

        transformation = dict(self.transformation or {})

        return {
            "token": self.token,
            "origin": self.origin,
            "media_id": self.media_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "suggestion_id": self.suggestion_id,
            "recommendation_id": self.recommendation_id,
            "run_id": self.run_id,
            "observation_id": self.observation_id,
            "operation": transformation.get("operation", ""),
            "parameters": dict(
                transformation.get("parameters") or {}
            ),
            "source": transformation.get(
                "source", SOURCE_RECOMMENDATION
            ),
            "override": (
                dict(self.override) if self.override else None
            ),
            "timestamp_seconds": self.timestamp_seconds,
            "duration_seconds": self.duration_seconds,
            "source_duration_seconds": (
                self.source_duration_seconds
            ),
            "suggested_position_seconds": (
                self.suggested_position_seconds
            ),
            "source_audio_codecs": list(
                self.source_audio_codecs or []
            ),
            "sample_audio_codecs": list(
                self.sample_audio_codecs or []
            ),
            "actual_duration_seconds": (
                self.actual_duration_seconds
            ),
            "has_artifact": bool(
                self.artifact_path
                and os.path.exists(self.artifact_path)
            ),
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "retention": (
                dict(self.retention)
                if isinstance(self.retention, dict)
                else None
            ),
            "alternatives": [
                dict(alternative)
                for alternative in (self.alternatives or [])
            ],
        }


class PreviewService:
    """
    Application boundary for Optimisation Preview.

    Constructed with injected services and repositories; owns no
    intelligence of its own. All recommendation, transformation,
    currentness, approval, and execution semantics come from the
    existing authorities.
    """

    def __init__(
        self,
        *,
        media_repository,
        validity_service,
        recommendation_service,
        execution_service,
        preference_service,
        transformation_service,
        operation_service,
        notification_service=None,
        settings=None,
        settings_path=None,
        preview_dir=None,
        prober=None,
        runner=None,
        user_policy_service=None,
    ):
        self._media_repository = media_repository
        self._validity_service = validity_service
        self._recommendation_service = recommendation_service
        self._execution_service = execution_service
        self._preference_service = preference_service
        self._transformation_service = transformation_service
        self._operation_service = operation_service
        self._notification_service = notification_service
        self._settings = (
            settings
            if settings is not None
            else load_settings(settings_path)
        )
        self._preview_dir = preview_dir
        self._prober = prober
        self._runner = runner or run_preview
        self._user_policy_service = user_policy_service

    def _retention_preferences(self):
        """Effective retention preferences (durable or default)."""

        service = self._user_policy_service

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

    def _retention_pins(self, context):
        """Assessment pins binding an assessment to one source."""

        return {
            "observation_id": context.observation_id,
            "size_bytes": context.pinned_size_bytes,
            "mtime_ns": context.pinned_mtime_ns,
        }

    def assess_retention(self, context, source_summary):
        """Read-time retention assessment for one preview context.

        Pure read: probes nothing, persists nothing. Raises
        PreviewError when the inventory or operation cannot be
        assessed (fail closed, matching the builder discipline).
        """

        preferences = self._retention_preferences()

        try:
            return assess_retention(
                source_summary,
                dict(context.transformation or {}),
                subtitle_retention=(
                    preferences["subtitle_retention"]
                ),
                content_retention=(
                    preferences["content_retention"]
                ),
                pins=self._retention_pins(context),
            )
        except ValueError as error:
            raise PreviewError(str(error))

    # ------------------------------------------------------------------
    # Settings / directories
    # ------------------------------------------------------------------

    @property
    def settings(self) -> PreviewSettings:
        return self._settings

    def preview_directory(self):
        return artifacts.resolve_preview_dir(
            self._settings.preview_dir or self._preview_dir
        )

    def _ffmpeg_binary(self):
        return resolve_ffmpeg_binary(
            self._settings.ffmpeg_path
        )

    def _probe(self, path):
        prober = self._prober

        if prober is None:
            from app.analysis_engine.ffprobe_analyzer import (
                probe_file_summary,
            )

            prober = probe_file_summary

        return prober(path)

    # ------------------------------------------------------------------
    # Context resolution (shared by Analysis, Wizard, Override)
    # ------------------------------------------------------------------

    def _current_candidate(self, media_id):
        """The current-valid queue candidate for one lineage."""

        for item in (
            self._recommendation_service.get_current_queue()
        ):
            if int(item.media_id) == int(media_id):
                return item

        raise PreviewError(
            "There is no current valid optimisation "
            "recommendation for this file. The analysis may be "
            "stale, missing, or simply not opportunity-producing. "
            "No preview was generated and nothing was invented "
            "in its place."
        )

    def _pin_source(self, media_id):
        """
        Pin the exact source version: current observation plus
        live file stat. Raises PreviewError when the source is
        missing or unreadable.
        """

        try:
            validity = self._validity_service.get_validity(
                int(media_id)
            )
        except ValueError as error:
            raise PreviewError(str(error))

        observation = validity.current_observation

        if observation is None:
            raise PreviewError(
                "This file has no current observation, so a "
                "preview cannot be pinned to a definite source "
                "version."
            )

        try:
            stat = os.stat(observation.file_path)
        except OSError:
            raise PreviewError(
                "The source file is not accessible, so a "
                "preview cannot be generated."
            )

        run = validity.valid_analysis_run

        return {
            "observation": observation,
            "run_id": run.id if run is not None else None,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "inode": stat.st_ino,
            "file_path": observation.file_path,
        }

    def _build_authoritative_transformation(
        self, candidate, *, parameters=None, recommendation_id=None
    ):
        """
        The authoritative transformation via the shared builder.
        The remux fallback is deliberately NOT applied here: a
        candidate with no executable proposition fails truthfully
        instead of previewing an invented optimisation.
        """

        from app.application.transformation_service import (
            NoExecutablePropositionError,
        )

        try:
            return (
                self._transformation_service.build_from_candidate(
                    candidate,
                    recommendation_id=recommendation_id,
                    parameters=parameters,
                )
            )
        except NoExecutablePropositionError:
            raise PreviewError(
                "This recommendation carries no executable "
                "optimisation proposition, so there is nothing "
                "truthful to preview. Nothing was generated."
            )

    def _new_context(
        self,
        *,
        origin,
        media_id,
        file_path,
        file_name,
        suggestion_id=None,
        recommendation_id=None,
        run_id=None,
        observation_id=None,
        pinned,
        transformation,
        override=None,
    ):
        context = PreviewContext(
            token=secrets.token_urlsafe(24),
            origin=origin,
            media_id=int(media_id),
            file_path=file_path,
            file_name=file_name,
            suggestion_id=suggestion_id,
            recommendation_id=recommendation_id,
            run_id=run_id,
            observation_id=observation_id,
            pinned_size_bytes=pinned["size_bytes"],
            pinned_mtime_ns=pinned["mtime_ns"],
            transformation=transformation.to_dict(),
            override=(
                dict(override) if override is not None else None
            ),
            status="open",
            created_at=_utcnow(),
        )

        _store_context(context)

        # Best-effort read-only playback facts so the position
        # control can render before the first generation. Probe
        # failure must never fail context creation.
        try:
            summary = self._probe(file_path)
        except Exception:
            summary = None

        try:
            self._refresh_source_facts(context, summary)
        except Exception:
            pass

        return context

    def create_analysis_preview(self, media_id, *, actor="human"):
        """
        Resolve an Analysis recommendation context: the current
        valid queue candidate plus the pinned source version plus
        the authoritative transformation.
        """

        _ = actor

        candidate = self._current_candidate(media_id)

        pinned = self._pin_source(candidate.media_id)

        transformation = self._build_authoritative_transformation(
            candidate,
            recommendation_id=getattr(
                candidate, "recommendation_id", None
            ),
        )

        return self._new_context(
            origin="analysis",
            media_id=candidate.media_id,
            file_path=candidate.file_path,
            file_name=candidate.file_name,
            recommendation_id=getattr(
                candidate, "recommendation_id", None
            ),
            run_id=getattr(candidate, "analysis_run_id", None),
            observation_id=getattr(
                candidate, "observation_id", None
            )
            or pinned["observation"].id,
            pinned=pinned,
            transformation=transformation,
        )

    def create_wizard_preview(
        self, suggestion_id, *, actor="human"
    ):
        """
        Resolve a Wizard suggestion to the shared candidate and
        transformation machinery. The suggestion itself is a
        preference record, never an execution object: resolution
        goes suggestion -> current recommendation context ->
        current valid candidate -> authoritative transformation.
        Refuses truthfully when no current valid Analysis
        recommendation context exists for the lineage.
        """

        _ = actor

        record = self._preference_service.get_suggestion(
            suggestion_id
        )

        if record is None:
            raise PreviewError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.status not in ("proposed", "accepted"):
            raise PreviewError(
                f"suggestion '{suggestion_id}' is "
                f"{record.status}; only proposed or accepted "
                "suggestions can seed a preview"
            )

        media_id = record.media_id

        context_view = (
            self._preference_service.recommendation_context(
                media_id
            )
        )

        if not context_view.get("available"):
            raise PreviewError(
                "This file has no current valid optimisation "
                "recommendation to preview. The Wizard suggestion "
                "remains a preference record; nothing was "
                "invented in place of a recommendation."
            )

        candidate = self._current_candidate(media_id)

        pinned = self._pin_source(candidate.media_id)

        transformation = self._build_authoritative_transformation(
            candidate,
            recommendation_id=getattr(
                candidate, "recommendation_id", None
            ),
        )

        return self._new_context(
            origin="wizard",
            media_id=candidate.media_id,
            file_path=candidate.file_path,
            file_name=candidate.file_name,
            suggestion_id=suggestion_id,
            recommendation_id=getattr(
                candidate, "recommendation_id", None
            ),
            run_id=getattr(candidate, "analysis_run_id", None),
            observation_id=getattr(
                candidate, "observation_id", None
            )
            or pinned["observation"].id,
            pinned=pinned,
            transformation=transformation,
        )

    def get_context(self, token):
        context = _get_context(token)

        if context is None:
            raise PreviewError(
                "This preview is no longer available. It may "
                "have been closed, accepted, rejected, or "
                "cleaned up."
            )

        return context

    def resolve_sample_path(self, token):
        """
        Absolute path of the active preview artifact for serving.
        The token is the only input; the path comes from the
        server-side registry and is containment-verified, so no
        request can cause an arbitrary filesystem read.
        """

        context = self.get_context(token)

        if context.status != "generated":
            raise PreviewError(
                "There is no generated preview sample to serve."
            )

        if not context.artifact_path:
            raise PreviewError(
                "There is no generated preview sample to serve."
            )

        directory = self.preview_directory()

        candidate = Path(context.artifact_path)

        try:
            resolved = candidate.resolve()
            anchored = Path(directory).resolve()
        except OSError:
            raise PreviewError(
                "The preview sample is not available."
            )

        if resolved.is_symlink() or (
            resolved != anchored
            and anchored not in resolved.parents
        ):
            raise PreviewError(
                "The preview sample is not available."
            )

        if not resolved.is_file():
            raise PreviewError(
                "The preview sample is not available."
            )

        return str(resolved)

    def resolve_original_path(self, token):
        """
        Absolute path of the pinned source file for serving. The
        path comes from the server-side registry (never the
        request) and the live file must still match the pinned
        size/mtime; otherwise serving is refused truthfully.
        """

        context = self.get_context(token)

        if context.status not in ("open", "generated", "failed"):
            raise PreviewError(
                "This preview is no longer available."
            )

        path = context.file_path

        if not path:
            raise PreviewError(
                "This preview has no pinned source file."
            )

        try:
            stat = os.stat(path)
        except OSError:
            raise PreviewError(
                "The source file is no longer accessible."
            )

        if (
            stat.st_size != context.pinned_size_bytes
            or stat.st_mtime_ns != context.pinned_mtime_ns
        ):
            raise PreviewError(
                "The source file changed since this preview "
                "context was created; it is not served."
            )

        return path

    # ------------------------------------------------------------------
    # User override
    # ------------------------------------------------------------------

    def apply_override(
        self, token, *, operation=None, parameters=None
    ):
        """
        Apply an explicit user override to a preview context. The
        override specifies supported transformation parameters
        through the existing operation registry; it is validated
        there and immediately becomes the authoritative context
        for Preview, Accept, execution, and provenance. The
        original recommendation is preserved in the context
        detail, never overwritten.
        """

        context = self.get_context(token)

        if context.status not in ("open", "generated", "failed"):
            raise PreviewError(
                "This preview can no longer be changed."
            )

        self._revalidate_pins(context)

        candidate = self._current_candidate(context.media_id)

        resolved_operation = context.transformation.get(
            "operation", ""
        )

        if operation is None or not str(operation).strip():
            operation = resolved_operation

        operation = str(operation)

        definition = get_operation(operation)

        if definition is None:
            raise PreviewError(
                f"operation '{operation}' is not registered"
            )

        if operation not in EXECUTABLE_OPERATIONS:
            raise PreviewError(
                f"operation '{operation}' is defined but not "
                "executable in this phase; the override was "
                "rejected and nothing changed"
            )

        from app.execution.operations import (
            validate_parameters,
        )

        try:
            validated = validate_parameters(
                operation, dict(parameters or {})
            )
        except ValueError as error:
            raise PreviewError(
                f"unsupported override parameter: {error} "
                "Nothing changed."
            )

        if (
            operation == OPERATION_CODEC_CONVERSION_MKV
            and resolved_operation
            != OPERATION_CODEC_CONVERSION_MKV
        ):
            self._require_offered_preservation_alternative(
                context, operation
            )

        if operation == resolved_operation:
            transformation = (
                self._transformation_service.build_from_candidate(
                    candidate,
                    recommendation_id=(
                        context.recommendation_id
                    ),
                    parameters=validated,
                )
            )
        else:
            transformation = (
                self._transformation_service.build_from_advanced(
                    operation=operation,
                    parameters=validated,
                    recommendation_id=(
                        context.recommendation_id
                    ),
                    captured_from_run_id=context.run_id,
                    captured_from_observation_id=(
                        context.observation_id
                    ),
                )
            )

        import dataclasses

        transformation = dataclasses.replace(
            transformation,
            source=SOURCE_USER_OVERRIDE,
            context_detail={
                "origin": context.origin,
                "suggestion_id": context.suggestion_id,
                "recommendation_id": (
                    context.recommendation_id
                ),
                "preview_token": context.token,
                "overridden_operation": operation,
                "overridden_parameters": dict(validated),
                "pinned_observation_id": (
                    context.observation_id
                ),
                "pinned_run_id": context.run_id,
            },
        )

        context.transformation = transformation.to_dict()

        context.override = {
            "operation": operation,
            "parameters": dict(validated),
        }

        context.status = "open"

        context.error = None

        context.retention = None

        context.alternatives = []

        _store_context(context)

        return context

    # ------------------------------------------------------------------
    # Pin revalidation (shared by generate and accept)
    # ------------------------------------------------------------------

    def _revalidate_pins(self, context):
        """
        Re-resolve the live source and require it to match the
        pinned version: same current observation id and same file
        stat. Any drift refuses truthfully; nothing is silently
        reinterpreted against the new version.
        """

        pinned = self._pin_source(context.media_id)

        if (
            pinned["observation"].id != context.observation_id
            or pinned["size_bytes"] != context.pinned_size_bytes
            or pinned["mtime_ns"] != context.pinned_mtime_ns
        ):
            raise PreviewError(
                "The source file changed since this preview "
                "context was created. Regenerate the preview "
                "against the current version instead; nothing "
                "was applied to the changed file."
            )

        candidate = self._current_candidate(context.media_id)

        candidate_run = getattr(
            candidate, "analysis_run_id", None
        )

        if (
            context.run_id is not None
            and candidate_run is not None
            and int(candidate_run) != int(context.run_id)
        ):
            raise PreviewError(
                "The underlying analysis changed since this "
                "preview context was created. Regenerate the "
                "preview instead; nothing was applied."
            )

        return pinned

    # ------------------------------------------------------------------
    # Timestamp selection
    # ------------------------------------------------------------------

    @staticmethod
    def select_timestamp(duration_seconds, requested_seconds):
        """
        Automatically select a valid preview window. Prefers the
        middle of the media; clamps into the valid range; short
        media yields a truthfully shorter window. Raises
        PreviewError when no valid window exists (unknown or
        non-positive duration).
        """

        try:
            total = float(duration_seconds)
            wanted = float(requested_seconds)
        except (TypeError, ValueError):
            raise PreviewError(
                "The source duration is unknown, so a valid "
                "preview window cannot be selected."
            )

        if not (total == total and wanted == wanted):
            raise PreviewError(
                "The source duration is unknown, so a valid "
                "preview window cannot be selected."
            )

        if total <= 0:
            raise PreviewError(
                "The source has no playable duration."
            )

        window = min(wanted, total)

        if window <= 0:
            raise PreviewError(
                "The requested preview duration is not positive."
            )

        start = (total - window) / 2.0

        if start < 0:
            start = 0.0

        return start, window

    @staticmethod
    def select_window(duration_seconds, requested_seconds,
                      start_seconds=None):
        """
        Select a preview window at a user-chosen start position.
        ``start_seconds=None`` keeps the established automatic
        behaviour (middle of the media). An explicit start is
        validated as a finite non-negative number and clamped
        into the playable range; it never changes the
        transformation, observation, run, or lineage — only the
        temporary sample position.
        """

        if start_seconds is None:
            return PreviewService.select_timestamp(
                duration_seconds, requested_seconds
            )

        try:
            total = float(duration_seconds)
            wanted = float(requested_seconds)
            start = float(start_seconds)
        except (TypeError, ValueError):
            raise PreviewError(
                "The preview position must be a number."
            )

        if not (total == total and wanted == wanted
                and start == start):
            raise PreviewError(
                "The preview position must be a finite number."
            )

        if total <= 0:
            raise PreviewError(
                "The source has no playable duration."
            )

        if wanted <= 0:
            raise PreviewError(
                "The requested preview duration is not positive."
            )

        if start < 0:
            raise PreviewError(
                "The preview position must be >= 0."
            )

        window = min(wanted, total)

        latest = total - window

        if latest < 0:
            latest = 0.0

        if start > latest:
            start = latest

        return start, window

    @staticmethod
    def _media_facts(summary):
        """Read-only playback facts from a probe summary.

        Returns (duration|None, [audio codecs], source facts
        dict) without touching media, state, or authority.
        """

        if not isinstance(summary, dict):
            return None, [], {}

        duration = summary.get("duration")

        try:
            duration = (
                float(duration) if duration is not None
                else None
            )
        except (TypeError, ValueError):
            duration = None

        if duration is not None and not (
            duration == duration and duration > 0
        ):
            duration = None

        audio_codecs = []

        for stream in summary.get("streams") or []:
            if not isinstance(stream, dict):
                continue

            if (
                stream.get("codec_type") == "audio"
                and stream.get("codec_name")
            ):
                codec = str(stream["codec_name"]).lower()

                if codec not in audio_codecs:
                    audio_codecs.append(codec)

        return duration, audio_codecs, {}

    def _refresh_source_facts(self, context, summary):
        """Refresh transient playback facts from a fresh probe.

        Read-only inventory facts (duration, audio codecs, and
        the default suggested position) used only to present
        playback and the position control. Never touches pins,
        transformation, observation, run, or lineage.
        """

        duration, audio_codecs, _ = self._media_facts(summary)

        context.source_duration_seconds = duration
        context.source_audio_codecs = audio_codecs

        suggested = None

        if duration:
            try:
                suggested, _ = self.select_timestamp(
                    duration,
                    self._settings.duration_seconds,
                )
            except PreviewError:
                suggested = None

        context.suggested_position_seconds = suggested

        _store_context(context)

        return context

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate_preview(self, token, *, start_seconds=None):
        """
        Generate (or regenerate) the bounded preview segment for
        one pinned context. Revalidates pins first; probes the
        source duration; selects the window — at the requested
        ``start_seconds`` when supplied, otherwise the
        established automatic middle position; builds the segment
        argv through the shared boundary; runs it bounded; and
        registers the artifact with an ownership manifest.
        The requested position changes only the temporary sample
        position, never the transformation, observation, run, or
        lineage. Failures clean up partial output and are
        reported truthfully; a failed replacement never destroys
        a valid existing preview.
        """

        context = self.get_context(token)

        if context.status not in ("open", "generated", "failed"):
            raise PreviewError(
                "This preview can no longer be generated."
            )

        self._revalidate_pins(context)

        summary = self._probe(context.file_path)

        self._refresh_source_facts(context, summary)

        assessment = self.assess_retention(context, summary)

        context.retention = assessment.to_view()

        context.alternatives = self._retention_alternatives(
            context, summary, assessment
        )

        duration = context.source_duration_seconds

        start, window = self.select_window(
            duration, self._settings.duration_seconds,
            start_seconds,
        )

        transformation = context.transformation

        operation = transformation.get("operation", "")

        if not operation:
            raise PreviewError(
                "This preview has no resolved operation."
            )

        directory = self.preview_directory()

        media_path, manifest_path = artifacts.artifact_paths(
            directory, context.token
        )

        tmp_media = media_path.with_suffix(".part")

        try:
            argv = build_preview_argv(
                operation=operation,
                source_path=context.file_path,
                output_path=str(tmp_media),
                start_seconds=start,
                duration_seconds=window,
                parameters=transformation.get("parameters"),
                source_summary=summary,
                ffmpeg_binary=self._ffmpeg_binary(),
            )
        except ValueError as error:
            # Unsupported layouts refuse here with the retention
            # assessment (computed above) still attached, so the
            # view can explain the consequence and offer verified
            # preservation alternatives instead of a bare error.
            return self._fail(context, str(error))

        try:
            returncode, _, stderr_tail = self._runner(
                argv, timeout=self._settings
                .generation_timeout_seconds,
            )
        except PreviewTimeout as error:
            self._remove_quietly(tmp_media)
            return self._fail(context, str(error))
        except PreviewCancelled as error:
            self._remove_quietly(tmp_media)
            return self._fail(context, str(error))
        except Exception as error:
            self._remove_quietly(tmp_media)
            return self._fail(
                context,
                f"preview generation failed: {error}",
            )

        if returncode != 0:
            self._remove_quietly(tmp_media)

            hint = ""

            if returncode == -9:
                hint = (
                    " The process was killed (return code "
                    "-9), which usually means the host ran "
                    "out of memory while encoding the "
                    "sample."
                )

            return self._fail(
                context,
                "preview generation failed "
                f"(ffmpeg exited {returncode}): "
                f"{(stderr_tail or '').strip()[-500:]}"
                f"{hint}",
            )

        try:
            size = tmp_media.stat().st_size
        except OSError:
            size = 0

        if size <= 0:
            self._remove_quietly(tmp_media)

            return self._fail(
                context,
                "preview generation produced no output.",
            )

        if size > self._settings.max_artifact_bytes:
            self._remove_quietly(tmp_media)

            return self._fail(
                context,
                "preview output exceeded the configured "
                "maximum artifact size.",
            )

        if context.artifact_path:
            self._remove_quietly(context.artifact_path)
            self._remove_quietly(context.manifest_path)

        os.replace(tmp_media, media_path)

        actual = None

        try:
            out_summary = self._probe(str(media_path))

            if isinstance(out_summary, dict):
                actual = out_summary.get("duration")

                _, sample_audio, _ = self._media_facts(
                    out_summary
                )

                context.sample_audio_codecs = sample_audio
        except Exception:
            actual = None

        artifacts.write_manifest(
            manifest_path,
            {
                "token": context.token,
                "origin": context.origin,
                "media_id": context.media_id,
                "observation_id": context.observation_id,
                "run_id": context.run_id,
                "operation": operation,
                "timestamp_seconds": start,
                "duration_seconds": window,
                "created_at": _utcnow(),
            },
        )

        context.timestamp_seconds = start

        context.duration_seconds = window

        context.actual_duration_seconds = (
            float(actual) if actual is not None else None
        )

        context.artifact_path = str(media_path)

        context.manifest_path = str(manifest_path)

        context.status = "generated"

        context.error = None

        _store_context(context)

        self._enforce_retention(context)

        return context

    def _require_offered_preservation_alternative(
        self, context, operation
    ):
        """Restrict Matroska preservation to offered alternatives.

        ``codec_conversion_mkv`` is executable so that a selected
        preservation alternative can run, but it must not become a
        generic override entry point: it is accepted here only when
        the current retention assessment offers it as a verified
        preservation alternative for this context. Reassesses the
        live source (never trusts stored view state), so a stale
        or absent alternative refuses truthfully. Selecting an
        already-MKV context's parameters is unaffected (same
        operation path, retention already satisfied at selection).
        """

        summary = self._probe(context.file_path)

        assessment = self.assess_retention(context, summary)

        offered = {
            alternative.get("operation")
            for alternative in self._retention_alternatives(
                context, summary, assessment
            )
        }

        if operation not in offered:
            raise PreviewError(
                "Matroska preservation is available only when "
                "the current retention assessment offers it as "
                "a verified preservation alternative. Nothing "
                "changed."
            )

    def _retention_alternatives(
        self, context, source_summary, assessment
    ):
        """Verified preservation alternatives as view payloads.

        Candidates are fully validated RequestedTransformations
        built through the existing transformation authority, but
        they carry no authority until the user selects one through
        apply_override. Failures yield no alternatives (truthful
        warning only), never a partial or invented proposal.
        """

        def build_advanced(
            *,
            operation,
            parameters,
            recommendation_id=None,
            preserve_resolution=True,
            preserve_hdr=True,
            audio_handling="copy",
            captured_from_run_id=None,
            captured_from_observation_id=None,
        ):
            return (
                self._transformation_service.build_from_advanced(
                    operation=operation,
                    parameters=parameters,
                    recommendation_id=recommendation_id,
                    preserve_resolution=preserve_resolution,
                    preserve_hdr=preserve_hdr,
                    audio_handling=audio_handling,
                    captured_from_run_id=captured_from_run_id,
                    captured_from_observation_id=(
                        captured_from_observation_id
                    ),
                )
            )

        try:
            candidates = alternatives_for(
                assessment,
                source_summary,
                dict(context.transformation or {}),
                build_advanced,
                recommendation_id=context.recommendation_id,
                captured_from_run_id=context.run_id,
                captured_from_observation_id=(
                    context.observation_id
                ),
            )
        except (ValueError, TypeError):
            return []

        payloads = []

        for candidate in candidates:
            payloads.append({
                "operation": candidate.operation,
                "parameters": dict(candidate.parameters),
                "explanation": (
                    "Preserve content by converting to "
                    "Matroska instead; carries the same HEVC "
                    "optimisation intent."
                ),
            })

        return payloads

    def acknowledge_retention(self, token, *, actor="human"):
        """Record explicit user acceptance of assessed loss.

        Created ONLY by this explicit user action, never by
        default: requires a loss_acknowledgeable assessment and
        binds the acknowledgement to the current pins. Refuses
        ok (nothing to accept), blocked (never acknowledgeable),
        and unassessable layouts. Returns the updated context.
        """

        context = self.get_context(token)

        if context.status not in ("open", "generated", "failed"):
            raise PreviewError(
                "This preview can no longer be changed."
            )

        self._revalidate_pins(context)

        summary = self._probe(context.file_path)

        assessment = self.assess_retention(context, summary)

        if assessment.verdict != VERDICT_LOSS_ACKNOWLEDGEABLE:
            raise PreviewError(
                "There is no acknowledgeable retention loss "
                "for this preview: explicit acknowledgement "
                "is only meaningful when content would be "
                "lost but may proceed."
            )

        acknowledgement = build_acknowledgement(
            assessment,
            pins=self._retention_pins(context),
        )

        transformation = dict(context.transformation or {})

        context_detail = dict(
            transformation.get("context_detail") or {}
        )

        context_detail["retention_acknowledged"] = (
            acknowledgement
        )

        transformation["context_detail"] = context_detail

        context.transformation = transformation

        _store_context(context)

        return context

    def _fail(self, context, message):
        context.status = "failed"

        context.error = message

        _store_context(context)

        raise PreviewError(message)

    @staticmethod
    def _remove_quietly(path):
        if not path:
            return

        try:
            os.unlink(path)
        except OSError:
            pass

    def _enforce_retention(self, context):
        """Keep at most N artifacts per lineage (newest kept)."""

        directory = self.preview_directory()

        owned = [
            path
            for path in artifacts.owned_artifact_paths(
                directory
            )
            if path.suffix == artifacts.ARTIFACT_SUFFIX
        ]

        mine = []

        for path in owned:
            manifest = path.with_suffix(
                artifacts.MANIFEST_SUFFIX
            )

            payload = artifacts.read_manifest(manifest)

            if (
                isinstance(payload, dict)
                and int(payload.get("media_id", -1))
                == int(context.media_id)
            ):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0

                mine.append((mtime, path, manifest))

        mine.sort(key=lambda item: item[0], reverse=True)

        limit = self._settings.max_artifacts_per_lineage

        for _, path, manifest in mine[limit:]:
            if str(path) == str(context.artifact_path):
                continue

            self._remove_quietly(path)
            self._remove_quietly(manifest)

    # ------------------------------------------------------------------
    # Accept / Reject / Close
    # ------------------------------------------------------------------

    def _enforce_retention_at_accept(self, context):
        """Strict-retention Accept pre-check (advisory layer).

        Runs after pin revalidation and before any suggestion
        decision or approval call, so a refusal never records a
        decision first. The execution-service approval boundary
        re-enforces authoritatively. Blocked layouts always refuse
        (acknowledgement can never bypass them); lossy /
        unassessable layouts refuse only under strict preferences.
        Under defaults, lossy/unassessable layouts pass here and
        builders remain the backstop.
        """

        preferences = self._retention_preferences()

        summary = self._probe(context.file_path)

        assessment = self.assess_retention(context, summary)

        try:
            check_retention_approval(
                assessment,
                dict(context.transformation or {}),
                subtitle_retention=(
                    preferences["subtitle_retention"]
                ),
                content_retention=(
                    preferences["content_retention"]
                ),
                pins=self._retention_pins(context),
            )
        except ValueError as error:
            raise PreviewError(str(error))

    def _transformation_matches(
        self, job_view, context, *, operation=None
    ):
        """The queued job must carry the previewed transformation."""

        stored = {}

        if isinstance(job_view, dict):
            stored = (
                job_view.get("requested_transformation") or {}
            )
        else:
            stored = getattr(
                job_view, "requested_transformation", {}
            ) or {}

        pinned = context.transformation

        expected_operation = (
            operation
            if operation is not None
            else pinned.get("operation")
        )

        return (
            stored.get("operation") == expected_operation
            and dict(stored.get("parameters") or {})
            == dict(pinned.get("parameters") or {})
            and stored.get("source")
            == (
                SOURCE_USER_OVERRIDE
                if context.override
                else pinned.get("source")
            )
            and (
                stored.get("captured_from_observation_id")
                == pinned.get("captured_from_observation_id")
            )
        )

    def _preview_context_detail(self, context):
        """Provenance detail frozen onto the queued job."""

        pinned_detail = dict(
            (context.transformation or {}).get(
                "context_detail"
            ) or {}
        )

        detail = {
            "origin": context.origin,
            "suggestion_id": context.suggestion_id,
            "recommendation_id": context.recommendation_id,
            "preview_token": context.token,
            "pinned_observation_id": context.observation_id,
            "pinned_run_id": context.run_id,
            "override": (
                dict(context.override)
                if context.override
                else None
            ),
        }

        if "retention_acknowledged" in pinned_detail:
            detail["retention_acknowledged"] = (
                pinned_detail["retention_acknowledged"]
            )

        return detail

    def accept_preview(
        self, token, *, actor="human",
        delete_original_requested=False,
    ):
        """
        Accept the pinned preview context through the existing
        approval boundary. Revalidates pins, records the
        underlying suggestion decision first for Wizard origins
        (so a stale suggestion fails before anything is queued),
        then queues the exact previewed transformation via
        ``ExecutionService.approve`` (or ``approve_advanced``
        when the override changed the operation) and verifies
        the queued job carries it. The artifact is deleted; the
        job (not the preview) is what enters the execution queue.
        """

        context = self.get_context(token)

        if context.status not in ("open", "generated"):
            raise PreviewError(
                "This preview can no longer be accepted."
            )

        self._revalidate_pins(context)

        self._enforce_retention_at_accept(context)

        suggestion_outcome = None

        if context.origin == "wizard" and context.suggestion_id:
            accepted, _ = (
                self._preference_service.accept_suggestion(
                    context.suggestion_id, actor=actor
                )
            )

            suggestion_outcome = accepted.suggestion_id

        pinned = context.transformation

        pinned_params = dict(pinned.get("parameters") or {})

        pinned_operation = pinned.get("operation", "")

        resolved_operation = pinned_operation

        detail = self._preview_context_detail(context)

        source = (
            SOURCE_USER_OVERRIDE
            if context.override
            else pinned.get(
                "source", SOURCE_RECOMMENDATION
            )
        )

        try:
            if context.override:
                # Any explicit override (same operation or
                # changed operation) is queued through the
                # advanced boundary with the override's exact
                # operation and parameters. Routing an override
                # through plain approve() would rebuild the
                # transformation from the original candidate
                # signals and silently drop the user's choice.
                job_id = self._execution_service.approve_advanced(
                    context.media_id,
                    operation=context.override["operation"],
                    parameters=pinned_params,
                    approved_by=actor,
                    delete_original_requested=(
                        delete_original_requested
                    ),
                    transformation_source=source,
                    transformation_context=detail,
                )

                resolved_operation = context.override[
                    "operation"
                ]
            else:
                job_id = self._execution_service.approve(
                    context.media_id,
                    approved_by=actor,
                    delete_original_requested=(
                        delete_original_requested
                    ),
                    parameters=pinned_params,
                    transformation_source=source,
                    transformation_context=detail,
                )
        except ValueError as error:
            raise PreviewError(str(error))

        job = self._execution_service.get(job_id)

        if not self._transformation_matches(
            job, context, operation=resolved_operation
        ):
            raise PreviewError(
                "The queued job does not carry the previewed "
                "transformation; refusing to report success. "
                "No preview state was changed."
            )

        self._delete_artifact(context)

        context.status = "accepted"

        context.error = None

        _store_context(context)

        return {
            "job_id": job_id,
            "suggestion_id": suggestion_outcome,
            "operation": resolved_operation,
        }

    def _resolve_analysis_recommendation(self, context):
        """
        Resolve the durable Analysis recommendation for an
        analysis-origin preview context using the existing
        recommendation authority: newest record for the lineage
        that is still in a rejectable state. Returns None when
        no such record exists. Never invents a recommendation.
        """

        try:
            record = (
                self._recommendation_service.get_latest_record(
                    int(context.media_id)
                )
            )
        except (RuntimeError, ValueError):
            return None

        if record is None:
            return None

        if record.state not in ("proposed", "accepted"):
            return None

        return record

    def reject_preview(self, token, *, actor="human", reason=None):
        """
        Reject through the existing rejection paths (Path A
        recommendation rejection where a record exists, Path B
        suggestion rejection for Wizard origins), then clean the
        transient preview. Rejection is never reported as a
        preview failure.
        """

        context = self.get_context(token)

        if context.status not in ("open", "generated", "failed"):
            raise PreviewError(
                "This preview can no longer be rejected."
            )

        if (
            context.origin == "wizard"
            and context.suggestion_id
        ):
            self._preference_service.reject_suggestion(
                context.suggestion_id,
                actor=actor,
                reason=reason,
            )
        else:
            # Revalidate the pinned run/observation before
            # resolving: a newer AnalysisRun may have produced a
            # newer proposed recommendation since this context was
            # created, and Reject must refuse rather than act on
            # a recommendation other than the previewed one.
            self._revalidate_pins(context)

            record = self._resolve_analysis_recommendation(
                context
            )

            if record is None:
                raise PreviewError(
                    "There is no durable Analysis "
                    "recommendation to reject for this file. "
                    "The transient preview was left untouched; "
                    "no decision was recorded and nothing was "
                    "queued."
                )

            try:
                self._recommendation_service.\
                    reject_recommendation(
                        recommendation_id=record.id,
                        rejected_by=actor,
                        reason=reason,
                    )
            except ValueError as error:
                raise PreviewError(
                    f"That Analysis recommendation cannot be "
                    f"rejected ({error}). Nothing was recorded."
                )

        self._delete_artifact(context)

        context.status = "rejected"

        context.error = None

        _store_context(context)

        return True

    def close_preview(self, token):
        """
        Leave the preview without changing any decision. Deletes
        the transient artifact and drops the context.
        """

        context = self.get_context(token)

        self._delete_artifact(context)

        _drop_context(token)

        return True

    def _delete_artifact(self, context):
        directory = self.preview_directory()

        for path in (
            context.artifact_path,
            context.manifest_path,
        ):
            if not path:
                continue

            try:
                artifacts.remove_owned(path, directory)
            except (ValueError, OSError):
                continue

        context.artifact_path = None

        context.manifest_path = None

    # ------------------------------------------------------------------
    # Cleanup (expiry sweep + startup backstop)
    # ------------------------------------------------------------------

    def cleanup_expired(self):
        """Delete expired orphan artifacts; returns the sweep report."""

        directory = self.preview_directory()

        return artifacts.sweep_orphans(
            directory,
            active_tokens=_active_tokens(),
            max_age_seconds=(
                self._settings.max_artifact_age_seconds
            ),
        )

    def startup_cleanup(self):
        """
        Startup backstop: every in-memory context is gone after a
        restart, so all owned artifacts are orphans. Removes them
        and best-effort informs the operator through a
        notification; cleanup never fails startup.
        """

        try:
            directory = self.preview_directory()
        except Exception:
            return {"removed": [], "kept": []}

        try:
            report = artifacts.sweep_orphans(directory)
        except Exception:
            return {"removed": [], "kept": []}

        removed = report.get("removed", [])

        if removed and self._notification_service is not None:
            try:
                self._notification_service.create(
                    category="information",
                    title="Temporary preview files cleaned up",
                    message=(
                        f"{len(removed)} abandoned preview "
                        "artifact(s) from a previous session "
                        "were deleted. Source and library media "
                        "were untouched."
                    ),
                )
            except Exception:
                pass

        return report
