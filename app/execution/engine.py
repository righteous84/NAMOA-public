"""
Execution engine primitives (Sprint 9).

Pure orchestration helpers for one execution sequence. All decisions
and state persistence live in ExecutionService; this module owns the
irreducible mechanics:

- staging a temporary output next to the source (same filesystem so
  the final swap is an atomic rename)
- output verification: exists, non-empty, valid media via the
  existing ffprobe infrastructure, plan expectations met, sha256
  recorded
- controlled replacement: original renamed to a recorded backup
  path, temporary output atomically renamed onto the source path,
  automatic restore of the original if the second rename fails
- rollback: restore original bytes from the recorded backup

FFmpeg itself runs through app.execution.ffmpeg (argument-list
execution only). The runner and prober are injectable for isolated
fixture testing.
"""

import hashlib
import os
import tempfile

from app.analysis_engine.ffprobe_analyzer import (
    probe_file_summary,
)

from app.execution.ffmpeg import run_ffmpeg


DEFAULT_RUNNER = run_ffmpeg

DEFAULT_PROBER = staticmethod(probe_file_summary)


class ReplacementFailed(OSError):
    """
    Raised when the swap sequence did not complete. restored=True
    means the original was put back; restored=False means the
    filesystem is mid-sequence and recovery must consult the
    recorded backup path.
    """

    def __init__(self, message, *, restored):

        super().__init__(message)

        self.restored = restored


def make_temp_output(source_path):
    """
    Create an empty temporary output file in the source directory
    (same filesystem as the source) and return its path.
    """

    directory = os.path.dirname(os.path.abspath(source_path))

    handle, temp_path = tempfile.mkstemp(
        prefix=".namoa-exec-",
        suffix=".mp4",
        dir=directory,
    )

    os.close(handle)

    return temp_path


def cleanup_path(path):

    if path and os.path.exists(path):

        try:

            os.unlink(path)

        except OSError:

            pass


def sha256_of(path):

    digest = hashlib.sha256()

    with open(path, "rb") as handle:

        for chunk in iter(
            lambda: handle.read(1024 * 1024), b""
        ):

            digest.update(chunk)

    return digest.hexdigest()


def verify_output(
    *,
    plan,
    output_path,
    prober=None,
):
    """
    Verify a staged output against the plan's verification
    requirements. Returns (ok, reasons, summary, sha256).

    FFmpeg exit code zero is never treated as sufficient on its own.

    Verification is operation-aware: the plan's `verification` section
    carries the expectations the planner derived from the operation
    definition and the probed source (codec, resolution, HDR, audio,
    container, duration, stream count, and the storage expectation
    that a storage-saving output must be smaller than the source).
    """

    prober = prober or probe_file_summary

    reasons = []

    requirements = plan.get("verification", {})

    if not os.path.exists(output_path):

        return (
            False,
            ["output file does not exist"],
            None,
            None,
        )

    if os.path.getsize(output_path) <= 0:

        reasons.append("output file is empty")

        return False, reasons, None, None

    summary = prober(output_path)

    if not summary:

        reasons.append(
            "output is not readable as media"
        )

        return False, reasons, None, None

    expected_container = requirements.get(
        "expected_container"
    )

    if expected_container:

        container = (summary.get("container") or "")

        if expected_container not in container:

            reasons.append(
                f"output container '{container}' does not "
                f"match expectation "
                f"'{expected_container}'"
            )

    min_streams = requirements.get("min_streams")

    if min_streams is not None:

        # Stream count derives from the SAME probe result as every
        # other characteristic (single injected prober), so fixture
        # tests can exercise verification without real media.

        inferred = (
            (1 if summary.get("video_codec") else 0)
            + int(summary.get("audio_tracks") or 0)
        )

        if inferred < min_streams:

            reasons.append(
                f"output exposes {inferred} usable streams; "
                f"expected at least {min_streams}"
            )

    source_duration = requirements.get(
        "source_duration_s"
    )

    tolerance = requirements.get(
        "duration_tolerance_s",
        2.0,
    )

    if source_duration:

        duration = float(summary.get("duration") or 0.0)

        if abs(duration - float(source_duration)) > float(
            tolerance
        ):

            reasons.append(
                f"output duration {duration:.3f}s differs from "
                f"source duration {float(source_duration):.3f}s "
                f"beyond tolerance {tolerance}s"
            )

    expected_video_codec = requirements.get(
        "expected_video_codec"
    )

    if expected_video_codec:

        codec = (summary.get("video_codec") or "").lower()

        if codec != str(expected_video_codec).lower():

            reasons.append(
                f"output video codec '{codec}' does not match "
                f"expectation '{expected_video_codec}'"
            )

    expected_width = requirements.get(
        "expected_width"
    )

    expected_height = requirements.get(
        "expected_height"
    )

    if expected_width is not None and expected_height is not None:

        width = summary.get("width")

        height = summary.get("height")

        if (
            width is None
            or height is None
            or int(width) != int(expected_width)
            or int(height) != int(expected_height)
        ):

            reasons.append(
                f"output resolution {width}x{height} does not "
                f"match expectation "
                f"{expected_width}x{expected_height}"
            )

    expected_hdr = requirements.get(
        "expected_hdr_format"
    )

    if requirements.get("preserve_hdr") and expected_hdr:

        # hdr_format is None for SDR content; only enforce when the
        # source actually carried an HDR format.
        output_hdr = summary.get("hdr_format")

        if output_hdr != expected_hdr:

            reasons.append(
                f"output HDR format '{output_hdr}' does not "
                f"match source '{expected_hdr}'"
            )

    expected_audio_codec = requirements.get(
        "expected_audio_codec"
    )

    if requirements.get("preserve_audio") and (
        expected_audio_codec
    ):

        audio_codec = (summary.get("audio_codec") or "").lower()

        if audio_codec != str(expected_audio_codec).lower():

            reasons.append(
                f"output audio codec '{audio_codec}' does not "
                f"match source '{expected_audio_codec}'"
            )

    expected_audio_channels = requirements.get(
        "expected_audio_channels"
    )

    if requirements.get("preserve_audio") and (
        expected_audio_channels is not None
    ):

        channels = summary.get("audio_channels")

        if channels is None or int(channels) != int(
            expected_audio_channels
        ):

            reasons.append(
                f"output audio channels '{channels}' do not "
                f"match source '{expected_audio_channels}'"
            )

    if requirements.get("smaller_than_source"):

        source_size = requirements.get("source_size_bytes")

        # The probed size is authoritative for the staged output's
        # media facts (the same probe drives every other check);
        # fall back to the raw file size when the probe omits it.
        output_size = summary.get("size_bytes")

        if output_size is None:

            output_size = os.path.getsize(output_path)

        if source_size is not None and int(output_size) >= int(
            source_size
        ):

            reasons.append(
                f"output size {output_size} is not smaller "
                f"than source {int(source_size)}; a storage-"
                "saving operation must produce a smaller file"
            )

    expected_subtitle_codecs = requirements.get(
        "expected_subtitle_codecs"
    )

    if expected_subtitle_codecs is not None:

        # Preservation is proven against the output inventory,
        # never merely from exit code 0: every source subtitle
        # codec must still be present (mov_text sources are
        # expected back as srt under the verified Matroska
        # text-to-text contract).
        output_subs = sorted(
            (stream.get("codec_name") or "").lower()
            for stream in (summary.get("streams") or [])
            if (stream.get("codec_type") or "") == "subtitle"
        )

        remaining = list(output_subs)

        for expected in expected_subtitle_codecs:
            wanted = (expected or "").lower()
            acceptable = {wanted}

            if wanted == "mov_text":
                acceptable |= {"subrip", "srt"}

            if wanted in ("srt", "subrip"):
                acceptable |= {"srt", "subrip"}

            for index, actual in enumerate(remaining):
                if actual in acceptable:
                    remaining.pop(index)
                    break
            else:
                reasons.append(
                    f"output subtitles {output_subs} do not "
                    f"preserve source subtitle codec "
                    f"'{expected}'"
                )
                break

    expected_chapter_count = requirements.get(
        "expected_chapter_count"
    )

    if expected_chapter_count is not None:

        actual_chapters = summary.get("chapter_count", 0) or 0

        try:
            actual_chapters = int(actual_chapters)
        except (TypeError, ValueError):
            actual_chapters = -1

        if actual_chapters != int(expected_chapter_count):

            reasons.append(
                f"output chapter count {actual_chapters} does "
                f"not match source "
                f"{int(expected_chapter_count)}"
            )

    checksum = sha256_of(output_path)

    return (
        not reasons,
        reasons,
        summary,
        checksum,
    )


def perform_replacement(
    *,
    source_path,
    staged_output_path,
    backup_path,
):
    """
    Controlled replacement:

        1. rename original -> backup_path   (atomic)
        2. rename staged output -> source    (atomic)

    If step 2 fails, step 1 is undone (original restored). If the
    undo also fails, ReplacementFailed(restored=False) is raised and
    the caller must record backup_path for recovery.

    Returns backup_path on success.
    """

    os.rename(source_path, backup_path)

    try:

        os.replace(staged_output_path, source_path)

    except OSError as error:

        restored = True

        try:

            os.rename(backup_path, source_path)

        except OSError:

            restored = False

        raise ReplacementFailed(
            f"replacement failed: {error}",
            restored=restored,
        ) from error

    return backup_path


def restore_original(*, source_path, backup_path):

    """
    Rollback/recovery: put the preserved original bytes back in
    place of the executed output (atomic rename).
    """

    os.replace(backup_path, source_path)
