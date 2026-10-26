"""Retention assessment (Phase 17 retention, read-time only).

A pure, side-effect-free evaluation of what one ALREADY-PROPOSED
transformation does to the content of one probed source under one
effective retention policy:

    source inventory + RequestedTransformation + retention policy
        -> RetentionAssessment

This module is NOT intelligence: it creates no AnalysisRuns, mutates
no observations, creates no lineage, enqueues nothing, spawns no
FFmpeg, writes no artifacts, and constructs no FFmpeg argv. It only
reads the shared stream-policy evidence (the same codec sets the
execution builders enforce) and the evidence-gated capability table
below.

Capability evaluation is default-deny: any content class / operation
pair not explicitly listed as preserved is blocked or unassessable,
never assumed preservable.
"""

from dataclasses import dataclass, field

from app.execution.ffmpeg import (
    BITMAP_SUBTITLE_CODECS,
    MKV_COPY_TEXT_CODECS,
    MKV_SRT_FALLBACK_CODECS,
    MKV_VERIFIED_BITMAP_CODECS,
    TEXT_SUBTITLE_CODECS,
)


#: Assessment verdicts, worst-case first for rollup purposes.
VERDICT_OK = "ok"
VERDICT_LOSS_ACKNOWLEDGEABLE = "loss_acknowledgeable"
VERDICT_BLOCKED = "blocked"
VERDICT_UNASSESSABLE = "unassessable_present"

_VERDICT_SEVERITY = {
    VERDICT_OK: 0,
    VERDICT_LOSS_ACKNOWLEDGEABLE: 1,
    VERDICT_UNASSESSABLE: 2,
    VERDICT_BLOCKED: 3,
}

#: Operations the assessment understands. Unknown operations refuse
#: closed-world: without a capability row nothing may be claimed.
OPERATION_REMUX_MP4 = "remux_mp4"
OPERATION_CODEC_CONVERSION = "codec_conversion"
OPERATION_CODEC_CONVERSION_MKV = "codec_conversion_mkv"

_MP4_OPERATIONS = frozenset({
    OPERATION_REMUX_MP4,
    OPERATION_CODEC_CONVERSION,
})

KNOWN_OPERATIONS = frozenset(
    _MP4_OPERATIONS | {OPERATION_CODEC_CONVERSION_MKV}
)

#: Bitmap subtitle codecs with a LIVE-VERIFIED Matroska stream-copy
#: contract are owned by the execution builders
#: (app.execution.ffmpeg.MKV_VERIFIED_BITMAP_CODECS); the retention
#: assessment reads that authority rather than duplicating it. Any
#: other bitmap codec stays blocked until its own live verification
#: exists.


@dataclass(frozen=True, slots=True)
class ContentItem:
    """One assessed content unit: verdict + explanation inputs."""

    content_class: str
    track_index: int | None = None
    codec: str | None = None
    verdict: str = VERDICT_OK
    preservable_by: tuple = ()
    explanation: str = ""


@dataclass(frozen=True, slots=True)
class RetentionAssessment:
    """Transient, recomputable retention consequence report."""

    operation: str = ""
    verdict: str = VERDICT_OK
    items: tuple = ()
    lost: tuple = ()
    disclosures: tuple = ()
    pins: dict = field(default_factory=dict)

    def to_view(self):
        """JSON-safe read model for handlers and templates."""

        return {
            "operation": self.operation,
            "verdict": self.verdict,
            "items": [
                {
                    "content_class": item.content_class,
                    "track_index": item.track_index,
                    "codec": item.codec,
                    "verdict": item.verdict,
                    "preservable_by": list(item.preservable_by),
                    "explanation": item.explanation,
                }
                for item in self.items
            ],
            "lost": [
                {
                    "content_class": item.content_class,
                    "track_index": item.track_index,
                    "codec": item.codec,
                    "explanation": item.explanation,
                }
                for item in self.lost
            ],
            "disclosures": list(self.disclosures),
            "pins": dict(self.pins),
        }


def _subtitle_items(operation, subtitles):
    """Per-track subtitle verdicts for one operation."""

    items = []

    for stream in subtitles:
        codec = (stream.get("codec_name") or "").lower()
        index = stream.get("index")

        if operation in _MP4_OPERATIONS:
            if codec in TEXT_SUBTITLE_CODECS:
                items.append(ContentItem(
                    content_class="subtitle",
                    track_index=index,
                    codec=codec or None,
                    verdict=VERDICT_OK,
                    preservable_by=(operation,),
                    explanation=(
                        f"text subtitle track #{index} "
                        f"({codec}) is carried as mov_text"
                    ),
                ))
            elif codec in BITMAP_SUBTITLE_CODECS:
                items.append(ContentItem(
                    content_class="subtitle",
                    track_index=index,
                    codec=codec or None,
                    verdict=VERDICT_BLOCKED,
                    preservable_by=(
                        (OPERATION_CODEC_CONVERSION_MKV,)
                        if codec in MKV_VERIFIED_BITMAP_CODECS
                        else ()
                    ),
                    explanation=(
                        f"bitmap subtitle track #{index} "
                        f"({codec}) cannot be preserved by "
                        f"{operation}"
                    ),
                ))
            else:
                items.append(ContentItem(
                    content_class="subtitle",
                    track_index=index,
                    codec=codec or None,
                    verdict=VERDICT_BLOCKED,
                    preservable_by=(),
                    explanation=(
                        f"subtitle track #{index} "
                        f"({codec or 'unknown codec'}) cannot "
                        f"be preserved by {operation}"
                    ),
                ))
        elif operation == OPERATION_CODEC_CONVERSION_MKV:
            if (
                codec in MKV_COPY_TEXT_CODECS
                or codec in MKV_SRT_FALLBACK_CODECS
                or codec in MKV_VERIFIED_BITMAP_CODECS
            ):
                items.append(ContentItem(
                    content_class="subtitle",
                    track_index=index,
                    codec=codec or None,
                    verdict=VERDICT_OK,
                    preservable_by=(operation,),
                    explanation=(
                        f"subtitle track #{index} ({codec}) "
                        "is carried in Matroska output"
                    ),
                ))
            else:
                items.append(ContentItem(
                    content_class="subtitle",
                    track_index=index,
                    codec=codec or None,
                    verdict=VERDICT_BLOCKED,
                    preservable_by=(),
                    explanation=(
                        f"subtitle track #{index} "
                        f"({codec or 'unknown codec'}) has no "
                        "verified Matroska preservation "
                        "contract"
                    ),
                ))

    return items


def assess(
    source_summary,
    transformation,
    *,
    subtitle_retention="allow_loss",
    content_retention="normal",
    pins=None,
):
    """Assess one proposed transformation against one source.

    `transformation` is a RequestedTransformation or its dict form;
    only operation + parameters are read. Returns a transient
    RetentionAssessment. Raises ValueError for unknown operations
    or missing stream inventory (closed-world: refuse rather than
    guess), matching the fail-closed builder discipline.
    """

    if isinstance(transformation, dict):
        operation = transformation.get("operation", "")
    else:
        operation = getattr(transformation, "operation", "")

    if operation not in KNOWN_OPERATIONS:
        raise ValueError(
            f"retention assessment: unknown operation "
            f"'{operation}'; nothing may be claimed"
        )

    if not isinstance(source_summary, dict):
        raise ValueError(
            "retention assessment requires a probed source "
            "summary; probe the source first"
        )

    streams = source_summary.get("streams")

    if not isinstance(streams, list) or not streams:
        raise ValueError(
            "retention assessment requires a source stream "
            "inventory; probe the source first"
        )

    items = []
    disclosures = []

    videos = [
        stream for stream in streams
        if (stream.get("codec_type") or "") == "video"
    ]

    audios = [
        stream for stream in streams
        if (stream.get("codec_type") or "") == "audio"
    ]

    subtitles = [
        stream for stream in streams
        if (stream.get("codec_type") or "") == "subtitle"
    ]

    others = [
        stream for stream in streams
        if (stream.get("codec_type") or "") not in (
            "video", "audio", "subtitle",
        )
    ]

    if len(videos) > 1:
        detail = ", ".join(
            f"#{stream.get('index')} "
            f"({stream.get('codec_name') or 'unknown'})"
            for stream in videos
        )
        items.append(ContentItem(
            content_class="video",
            verdict=VERDICT_BLOCKED,
            explanation=(
                f"{len(videos)} video streams present "
                f"({detail}); only a single primary video "
                "stream is supported"
            ),
        ))

    for stream in audios:
        items.append(ContentItem(
            content_class="audio",
            track_index=stream.get("index"),
            codec=(stream.get("codec_name") or None),
            verdict=VERDICT_OK,
            preservable_by=(operation,),
            explanation=(
                f"audio track #{stream.get('index')} "
                f"({stream.get('codec_name') or 'unknown'}) "
                "is mapped and copied"
            ),
        ))

    items.extend(_subtitle_items(operation, subtitles))

    for stream in others:
        stream_type = (stream.get("codec_type") or "")
        items.append(ContentItem(
            content_class=stream_type or "unknown",
            track_index=stream.get("index"),
            codec=(stream.get("codec_name") or None),
            verdict=VERDICT_BLOCKED,
            preservable_by=(),
            explanation=(
                f"{stream_type or 'unknown'} stream "
                f"#{stream.get('index')} "
                f"('{stream.get('codec_name') or 'unknown'}') "
                f"cannot be represented by {operation}"
            ),
        ))

    chapter_count = source_summary.get("chapter_count", 0) or 0

    try:
        chapter_count = int(chapter_count)
    except (TypeError, ValueError):
        chapter_count = 0

    chapters_probed = "chapter_count" in source_summary

    if chapter_count > 0:
        if operation == OPERATION_CODEC_CONVERSION_MKV:
            items.append(ContentItem(
                content_class="chapter",
                verdict=VERDICT_OK,
                preservable_by=(operation,),
                explanation=(
                    f"{chapter_count} chapters are carried in "
                    "Matroska output"
                ),
            ))
        else:
            items.append(ContentItem(
                content_class="chapter",
                verdict=VERDICT_UNASSESSABLE,
                preservable_by=(OPERATION_CODEC_CONVERSION_MKV,),
                explanation=(
                    f"{chapter_count} chapters cannot be "
                    f"assessed for {operation}; chapter "
                    "mapping is not established for this "
                    "output"
                ),
            ))
    elif not chapters_probed:
        disclosures.append(
            "chapter information was not probed for this "
            "source; chapter loss cannot be assessed"
        )

    format_tags = source_summary.get("format_tags") or {}

    if isinstance(format_tags, dict) and format_tags:
        items.append(ContentItem(
            content_class="metadata",
            verdict=VERDICT_LOSS_ACKNOWLEDGEABLE,
            preservable_by=(),
            explanation=(
                "container-level metadata is not "
                "contractually preserved by this "
                "conversion"
            ),
        ))

    disclosures.append(
        "container-level metadata handling is best-effort; "
        "preservation beyond mapped streams is never promised"
    )

    verdict = VERDICT_OK

    for item in items:
        if _VERDICT_SEVERITY.get(
            item.verdict, 0
        ) > _VERDICT_SEVERITY[verdict]:
            verdict = item.verdict

    lost = tuple(
        item for item in items
        if item.verdict == VERDICT_LOSS_ACKNOWLEDGEABLE
    )

    return RetentionAssessment(
        operation=operation,
        verdict=verdict,
        items=tuple(items),
        lost=lost,
        disclosures=tuple(disclosures),
        pins=dict(pins or {}),
    )


def _item_in_strict_scope(item, *, subtitle_retention,
                          content_retention):
    """Whether one lost item needs acknowledgement under policy."""

    if (
        item.content_class == "subtitle"
        and subtitle_retention == "preserve"
    ):
        return True

    if content_retention == "preserve_supported":
        return True

    return False


def acknowledgement_required(
    assessment,
    *,
    subtitle_retention="allow_loss",
    content_retention="normal",
):
    """Lost items the current strict policy requires acked."""

    return [
        item for item in assessment.lost
        if _item_in_strict_scope(
            item,
            subtitle_retention=subtitle_retention,
            content_retention=content_retention,
        )
    ]


def build_acknowledgement(assessment, *, pins=None):
    """Record explicit user acceptance of the assessed loss.

    Created only by explicit user action (the caller owns that
    guarantee). Identifies the actual presented loss set and binds
    it to assessment pins; any drift voids it at approval.
    """

    return {
        "verdict": assessment.verdict,
        "lost": [
            {
                "content_class": item.content_class,
                "track_index": item.track_index,
                "codec": item.codec,
            }
            for item in assessment.lost
        ],
        "assessed_at": _utcnow(),
        "pins": dict(pins if pins is not None
                     else assessment.pins),
    }


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


def acknowledgement_matches(
    acknowledgement, assessment, *, pins=None
):
    """Whether an ack covers the CURRENT assessment loss set."""

    if not isinstance(acknowledgement, dict):
        return False

    expected_pins = dict(
        pins if pins is not None else assessment.pins
    )

    if dict(acknowledgement.get("pins") or {}) != expected_pins:
        return False

    current = sorted(
        (
            item.content_class,
            item.track_index,
            item.codec,
        )
        for item in assessment.lost
    )

    recorded = sorted(
        (
            entry.get("content_class"),
            entry.get("track_index"),
            entry.get("codec"),
        )
        for entry in (acknowledgement.get("lost") or [])
    )

    return recorded == current


def check_approval(
    assessment,
    transformation,
    *,
    subtitle_retention="allow_loss",
    content_retention="normal",
    pins=None,
):
    """Shared strict-retention approval check.

    Returns None when the transformation may proceed. Raises
    ValueError with a user-facing reason when it must not:
    blocked layouts never proceed; unassessable layouts refuse
    under strict policy; acknowledgeable loss requires a matching
    explicit acknowledgement for every strict-scope item. Under
    defaults nothing is required (builders remain the backstop).
    """

    strict = (
        subtitle_retention == "preserve"
        or content_retention == "preserve_supported"
    )

    if assessment.verdict == VERDICT_OK:
        return None

    if assessment.verdict == VERDICT_BLOCKED:
        problems = "; ".join(
            item.explanation
            for item in assessment.items
            if item.verdict == VERDICT_BLOCKED
        )
        raise ValueError(
            "retention policy refuses this approval: "
            f"{problems}. Select a verified preservation "
            "alternative instead; acknowledgement cannot "
            "bypass blocked content."
        )

    if assessment.verdict == VERDICT_UNASSESSABLE:
        if not strict:
            return None

        problems = "; ".join(
            item.explanation
            for item in assessment.items
            if item.verdict == VERDICT_UNASSESSABLE
        )
        raise ValueError(
            "strict retention policy refuses this approval: "
            f"{problems}."
        )

    if assessment.verdict == VERDICT_LOSS_ACKNOWLEDGEABLE:
        required = acknowledgement_required(
            assessment,
            subtitle_retention=subtitle_retention,
            content_retention=content_retention,
        )

        if not required:
            return None

        detail = (
            transformation.to_dict()
            if hasattr(transformation, "to_dict")
            else dict(transformation or {})
        )

        acknowledgement = (
            dict(detail.get("context_detail") or {}).get(
                "retention_acknowledged"
            )
        )

        if acknowledgement_matches(
            acknowledgement,
            assessment,
            pins=(pins if pins is not None
                  else assessment.pins),
        ):
            return None

        problems = "; ".join(
            f"{item.content_class}"
            + (
                f" track #{item.track_index}"
                if item.track_index is not None
                else ""
            )
            + (f" ({item.codec})" if item.codec else "")
            for item in required
        )

        raise ValueError(
            "strict retention policy requires explicit "
            f"acknowledgement of {problems} before this "
            "approval, or a verified preservation "
            "alternative."
        )

    return None


def alternatives_for(
    assessment,
    source_summary,
    base_transformation,
    build_advanced,
    *,
    recommendation_id=None,
    captured_from_run_id=None,
    captured_from_observation_id=None,
):
    """Generate verified preservation alternatives.

    Pure except for the injected `build_advanced` callable (normally
    TransformationService.build_from_advanced): candidates are fully
    validated RequestedTransformations carrying no authority until
    the user selects one through the existing override path. Never
    constructs argv. Returns [] when nothing verified preserves the
    endangered classes.
    """

    if isinstance(base_transformation, dict):
        base_operation = base_transformation.get("operation", "")
        base_parameters = dict(
            base_transformation.get("parameters") or {}
        )
        base_preserve_resolution = base_transformation.get(
            "preserve_resolution", True
        )
        base_preserve_hdr = base_transformation.get(
            "preserve_hdr", True
        )
        base_audio_handling = base_transformation.get(
            "audio_handling", "copy"
        )
    else:
        base_operation = getattr(
            base_transformation, "operation", ""
        )
        base_parameters = dict(
            getattr(base_transformation, "parameters", None)
            or {}
        )
        base_preserve_resolution = getattr(
            base_transformation, "preserve_resolution", True
        )
        base_preserve_hdr = getattr(
            base_transformation, "preserve_hdr", True
        )
        base_audio_handling = getattr(
            base_transformation, "audio_handling", "copy"
        )

    endangered = [
        item for item in assessment.items
        if item.verdict in (
            VERDICT_BLOCKED, VERDICT_UNASSESSABLE,
        )
        and item.preservable_by
    ]

    if not endangered:
        return []

    # The only verified remediation in this phase: MP4 HEVC intent
    # re-expressed as Matroska HEVC when every endangered class is
    # MKV-preservable. Remux intent has no MKV counterpart
    # operation, so remux-based assessments yield no alternative.
    if base_operation != OPERATION_CODEC_CONVERSION:
        return []

    if not all(
        OPERATION_CODEC_CONVERSION_MKV in item.preservable_by
        for item in endangered
    ):
        return []

    candidate = build_advanced(
        operation=OPERATION_CODEC_CONVERSION_MKV,
        parameters=dict(base_parameters),
        recommendation_id=recommendation_id,
        preserve_resolution=base_preserve_resolution,
        preserve_hdr=base_preserve_hdr,
        audio_handling=base_audio_handling,
        captured_from_run_id=captured_from_run_id,
        captured_from_observation_id=(
            captured_from_observation_id
        ),
    )

    return [candidate]
