"""
FFmpeg boundary (Sprint 9, extended Phase 6).

The single place in NAMOA where FFmpeg commands are constructed and
executed:

- argv is always a list; shell interpolation is never used
- the operation set is closed and owned by the operation registry
  (app/execution/operations.py); arguments derive only from the
  validated plan / operation parameters
- paths are passed verbatim to FFmpeg as positional operands (no
  shell, no string concatenation of user input)
- a hard timeout prevents runaway processes

The runner is injectable so tests can exercise the full state machine
without real media or real FFmpeg.

Preview generation (Phase 17) reuses this boundary: bounded preview
segments are built from the same registered operation builders with
input seeking and a duration limit applied, and executed through a
cancellable runner with its own bounded timeout. No preview-specific
codec, bitrate, or resolution logic exists here.
"""

import os
import shutil
import subprocess

from app.execution.operations import (
    EXECUTABLE_OPERATIONS,
    HEVC_CRF_VALUES,
    OPERATION_CODEC_CONVERSION,
    OPERATION_CODEC_CONVERSION_MKV,
    OPERATION_REMUX_MP4,
    get_operation,
)
from app.execution.policy import EXECUTION_TIMEOUT_SECONDS


#: Environment variable overriding the FFmpeg executable used for
#: Preview generation. The production execution path keeps using the
#: registry default and is unaffected.
PREVIEW_FFMPEG_ENV_VAR = "NAMOA_FFMPEG"

#: Environment variable overriding the ffprobe executable used for
#: Preview media probing.
PREVIEW_FFPROBE_ENV_VAR = "NAMOA_FFPROBE"


def resolve_media_binary(
    name, *, explicit=None, env_var=None,
):
    """
    Resolve a media executable (ffmpeg/ffprobe) cross-platform.

    Precedence: explicit configured path, environment variable,
    then PATH lookup. The result is a plain executable path or
    name; invocation always uses an argv list with shell=False,
    so no quoting or shell syntax is involved on any platform.
    Raises ValueError when nothing usable is found.
    """

    candidates = []

    if explicit:
        candidates.append(str(explicit))

    if env_var:
        configured = os.environ.get(env_var, "").strip()

        if configured:
            candidates.append(configured)

    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(
            candidate, os.X_OK
        ):
            return candidate

        raise ValueError(
            f"configured media executable '{candidate}' "
            "is not an executable file"
        )

    found = shutil.which(name)

    if found:
        return found

    raise ValueError(
        f"media executable '{name}' was not found on PATH "
        f"and no override was configured"
        + (f" (see ${env_var})" if env_var else "")
    )


def resolve_ffmpeg_binary(explicit=None):
    """Resolve the FFmpeg executable for Preview generation."""

    return resolve_media_binary(
        "ffmpeg",
        explicit=explicit,
        env_var=PREVIEW_FFMPEG_ENV_VAR,
    )


#: Subtitle codecs that can be carried explicitly into MP4
#: output as mov_text. Only codecs in this set are claimed as
#: supported; anything else subtitle-bearing refuses truthfully
#: rather than relying on FFmpeg automatic encoder selection
#: (which fails for subtitle-to-MP4 mappings on supported
#: builds) or silently dropping subtitle information.
TEXT_SUBTITLE_CODECS = frozenset({
    "subrip",
    "srt",
    "ass",
    "ssa",
    "mov_text",
    "webvtt",
})

#: Bitmap/image subtitle codecs that MP4/mov_text cannot preserve.
#: Named separately so refusal messages explain the actual cause
#: instead of reporting an opaque encoder failure.
BITMAP_SUBTITLE_CODECS = frozenset({
    "hdmv_pgs_subtitle",
    "dvd_subtitle",
    "dvd_sub",
    "xsub",
    "dvb_subtitle",
})

#: Text subtitle codecs with a live-verified Matroska stream-copy
#: contract (subrip, webvtt, ass carried; ssa shares the ASS
#: family and the same test matrix).
MKV_COPY_TEXT_CODECS = frozenset({
    "subrip",
    "srt",
    "ass",
    "ssa",
    "webvtt",
})

#: The Matroska muxer rejects stream-copied mov_text ("Subtitle
#: codec 94213 is not supported"); mov_text tracks must be
#: re-encoded to srt instead (text-to-text, live-verified).
MKV_SRT_FALLBACK_CODECS = frozenset({
    "mov_text",
})

#: Bitmap subtitle codecs with a live-verified Matroska
#: stream-copy contract (synthetic PGS epoch carried through an
#: HEVC Matroska conversion; output inventory confirms
#: hdmv_pgs_subtitle). Any other bitmap codec stays refused until
#: its own live verification exists.
MKV_VERIFIED_BITMAP_CODECS = frozenset({
    "hdmv_pgs_subtitle",
})


def mkv_subtitle_codec_args(subtitle_streams):
    """Per-output-subtitle-stream ``-c:s:N`` args for Matroska.

    Returns a flat argv fragment such as ``["-c:s:0", "copy",
    "-c:s:1", "srt"]`` where ``N`` counts mapped subtitle streams
    in source-inventory order. This is deterministic because the
    builder maps subtitles with a single ``-map 0:s?``, which
    preserves source stream order in the output.

    Per-track contract (each live-verified):

    - ``MKV_COPY_TEXT_CODECS`` and verified bitmap codecs copy;
    - ``mov_text`` re-encodes to ``srt`` (text-to-text; the
      Matroska muxer rejects copied mov_text);
    - anything else raises ``ValueError`` naming the stream:
      unknown/unverified codecs must refuse truthfully, never
      inherit a neighbouring track's encoder.

    A single global ``-c:s`` is deliberately never emitted: it
    would apply one track's encoder (for example ``srt``) to
    every subtitle stream (for example PGS). Empty input yields
    no args.
    """

    args = []

    for output_index, stream in enumerate(
        subtitle_streams or []
    ):
        codec = (stream.get("codec_name") or "").lower()
        index = stream.get("index")

        if codec in MKV_COPY_TEXT_CODECS:
            encoder = "copy"
        elif codec in MKV_SRT_FALLBACK_CODECS:
            encoder = "srt"
        elif codec in MKV_VERIFIED_BITMAP_CODECS:
            encoder = "copy"
        else:
            raise ValueError(
                "no verified Matroska subtitle contract for "
                f"subtitle codec '{codec or 'unknown'}' in "
                f"stream #{index}"
            )

        args += [f"-c:s:{output_index}", encoder]

    return args


def _source_stream_inventory(source_summary):
    """
    The probed per-stream inventory an operation builder needs to
    map streams deterministically. Raises ValueError when the
    inventory is absent: without it the builder cannot know
    whether subtitles, attachments, or data streams exist, and
    guessing would either silently drop streams or depend on
    FFmpeg automatic encoder selection.
    """

    if not isinstance(source_summary, dict):
        raise ValueError(
            "source stream inventory is required to build a "
            "deterministic FFmpeg command; probe the source first"
        )

    streams = source_summary.get("streams")

    if not isinstance(streams, list) or not streams:
        raise ValueError(
            "source stream inventory is required to build a "
            "deterministic FFmpeg command; probe the source first"
        )

    return streams


def _stream_policy_args(operation, source_summary):
    """
    Explicit stream mapping plus subtitle codec args for one
    operation, shared by execution and Preview.

    Policy (identical for every caller):

    - the single primary video stream is mapped (``0:v:0``);
      audio streams are all mapped (``0:a``);
    - text subtitles are all mapped (``0:s``) with an explicit
      ``mov_text`` encoder, never automatic selection;
    - bitmap subtitles, unknown subtitle codecs, attachments,
      data streams, unknown stream types, and additional video
      streams refuse truthfully with a NAMOA-level error naming
      the stream, instead of silently dropping information or
      failing opaquely inside FFmpeg.

    All mapping specifiers are optional (``?``) so layouts that
    worked before (for example audio-less video) keep working;
    unsupported layouts fail here, before any process runs.
    Returns ``(map_args, codec_args)``.
    """

    streams = _source_stream_inventory(source_summary)

    video = [
        stream
        for stream in streams
        if (stream.get("codec_type") or "") == "video"
    ]

    if len(video) > 1:
        detail = ", ".join(
            f"#{stream.get('index')} "
            f"({stream.get('codec_name') or 'unknown'})"
            for stream in video
        )
        raise ValueError(
            f"unsupported source layout for {operation}: "
            f"{len(video)} video streams present ({detail}); "
            "only a single primary video stream is supported"
        )

    subtitles = [
        stream
        for stream in streams
        if (stream.get("codec_type") or "") == "subtitle"
    ]

    for stream in subtitles:
        codec = (stream.get("codec_name") or "").lower()
        index = stream.get("index")

        if codec in BITMAP_SUBTITLE_CODECS:
            raise ValueError(
                f"unsupported source layout for {operation}: "
                f"bitmap subtitle codec '{codec}' in stream "
                f"#{index} cannot be preserved in MP4 output"
            )

        if codec not in TEXT_SUBTITLE_CODECS:
            raise ValueError(
                f"unsupported source layout for {operation}: "
                f"subtitle codec '{codec or 'unknown'}' in "
                f"stream #{index} cannot be preserved in MP4 "
                "output"
            )

    for stream in streams:
        stream_type = (stream.get("codec_type") or "")

        if stream_type in ("attachment", "data"):
            raise ValueError(
                f"unsupported source layout for {operation}: "
                f"{stream_type} stream "
                f"#{stream.get('index')} "
                f"('{stream.get('codec_name') or 'unknown'}') "
                "cannot be represented in MP4 output"
            )

        if stream_type not in ("video", "audio", "subtitle"):
            raise ValueError(
                f"unsupported source layout for {operation}: "
                f"unknown stream type "
                f"'{stream_type or 'unknown'}' in stream "
                f"#{stream.get('index')}"
            )

    map_args = ["-map", "0:v:0?", "-map", "0:a?"]
    codec_args = []

    if subtitles:
        map_args += ["-map", "0:s?"]
        codec_args += ["-c:s", "mov_text"]

    return map_args, codec_args


def _mkv_stream_policy_args(operation, source_summary):
    """Explicit stream mapping plus subtitle codec args for the
    Matroska HEVC conversion, shared by execution and Preview.

    Same fail-closed discipline as the MP4 policy: single primary
    video, all audio, attachments/data/unknown/multi-video refuse
    truthfully. Differences from MP4 (each live-verified):

    - subtitles are mapped with ``-map 0:s?`` and encoded
      per output subtitle stream (``-c:s:N`` in source subtitle
      order): ``MKV_COPY_TEXT_CODECS`` and verified bitmap
      subtitles stream-copy; ``mov_text`` tracks re-encode to
      srt (text-to-text; the Matroska muxer rejects copied
      mov_text). A single global ``-c:s`` is never used, so a
      mixed text + bitmap layout cannot inherit one track's
      encoder onto another track's stream;
    - chapters and global metadata are mapped explicitly
      (``-map_metadata 0 -map_chapters 0``; safe no-ops when
      absent);
    - any other subtitle codec refuses (no verified contract).

    Returns ``(map_args, codec_args)``.
    """

    streams = _source_stream_inventory(source_summary)

    video = [
        stream
        for stream in streams
        if (stream.get("codec_type") or "") == "video"
    ]

    if len(video) > 1:
        detail = ", ".join(
            f"#{stream.get('index')} "
            f"({stream.get('codec_name') or 'unknown'})"
            for stream in video
        )
        raise ValueError(
            f"unsupported source layout for {operation}: "
            f"{len(video)} video streams present ({detail}); "
            "only a single primary video stream is supported"
        )

    subtitles = [
        stream
        for stream in streams
        if (stream.get("codec_type") or "") == "subtitle"
    ]

    for stream in subtitles:
        codec = (stream.get("codec_name") or "").lower()
        index = stream.get("index")

        if codec in MKV_COPY_TEXT_CODECS:
            continue

        if codec in MKV_SRT_FALLBACK_CODECS:
            continue

        if codec in MKV_VERIFIED_BITMAP_CODECS:
            continue

        raise ValueError(
            f"unsupported source layout for {operation}: "
            f"subtitle codec '{codec or 'unknown'}' in "
            f"stream #{index} has no verified Matroska "
            "preservation contract"
        )

    for stream in streams:
        stream_type = (stream.get("codec_type") or "")

        if stream_type in ("attachment", "data"):
            raise ValueError(
                f"unsupported source layout for {operation}: "
                f"{stream_type} stream "
                f"#{stream.get('index')} "
                f"('{stream.get('codec_name') or 'unknown'}') "
                "cannot be represented in Matroska output"
            )

        if stream_type not in ("video", "audio", "subtitle"):
            raise ValueError(
                f"unsupported source layout for {operation}: "
                f"unknown stream type "
                f"'{stream_type or 'unknown'}' in stream "
                f"#{stream.get('index')}"
            )

    map_args = [
        "-map", "0:v:0?",
        "-map", "0:a?",
        "-map_metadata", "0",
        "-map_chapters", "0",
    ]
    codec_args = []

    if subtitles:
        map_args[2:2] = ["-map", "0:s?"]
        codec_args += mkv_subtitle_codec_args(subtitles)

    return map_args, codec_args


def _remux_mp4_argv(
    *,
    source_path,
    output_path,
    parameters=None,
    source_summary=None,
):
    """
    remux_mp4: lossless container remux (-c copy). No re-encoding,
    no filters, no metadata surgery: bytes of the streams are copied.
    Text subtitles are carried explicitly as mov_text (plain
    stream copy cannot represent them in MP4); unsupported layouts
    refuse via the shared stream policy instead of failing
    opaquely inside FFmpeg.
    """

    map_args, subtitle_codec_args = _stream_policy_args(
        OPERATION_REMUX_MP4, source_summary
    )

    return (
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", source_path,
        ]
        + map_args
        + [
            "-c", "copy",
        ]
        + subtitle_codec_args
        + [
            "-movflags", "+faststart",
            "-f", "mp4",
            output_path,
        ]
    )


def _hdr_color_args(source_summary):
    """
    Pass through colour primaries/transfer/space from the probed
    source so HDR characteristics are preserved by a re-encode where
    the source carries them. Additive; absent values add nothing.
    """

    hdr = (source_summary or {}).get("hdr_metadata") or {}

    args = []

    if hdr.get("color_primaries"):
        args += ["-color_primaries", str(hdr["color_primaries"])]

    if hdr.get("color_transfer"):
        args += ["-color_trc", str(hdr["color_transfer"])]

    if hdr.get("color_space"):
        args += ["-colorspace", str(hdr["color_space"])]

    return args


def _codec_conversion_argv(
    *,
    source_path,
    output_path,
    parameters=None,
    source_summary=None,
):
    """
    codec_conversion (Phase 6C, deliberately narrow): re-encode the
    video stream from H.264 to HEVC (libx265) with a controlled CRF
    quality and preset, preserving resolution, copying the audio
    streams, and passing through source colour metadata. All values
    come from the validated operation parameters; no free-form input.
    """

    params = dict(parameters or {})

    crf_value = HEVC_CRF_VALUES.get(
        params.get("quality", "crf_22"),
        22,
    )

    preset = params.get("preset", "medium")

    map_args, subtitle_codec_args = _stream_policy_args(
        OPERATION_CODEC_CONVERSION, source_summary
    )

    argv = (
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", source_path,
        ]
        + map_args
        + [
            "-c:v", "libx265",
            "-preset", str(preset),
            "-crf", str(crf_value),
            "-tag:v", "hvc1",
            "-c:a", "copy",
        ]
        + subtitle_codec_args
        + [
            "-movflags", "+faststart",
            "-f", "mp4",
        ]
    )

    argv.extend(_hdr_color_args(source_summary))

    argv.append(output_path)

    return argv


def _codec_conversion_mkv_argv(
    *,
    source_path,
    output_path,
    parameters=None,
    source_summary=None,
):
    """codec_conversion_mkv (Phase 17 retention): re-encode video
    H.264 to HEVC (libx265) with the shared CRF/preset family,
    preserving resolution, copying audio, passing colour metadata,
    targeting Matroska so verified subtitle/chapter content is
    retained. Subtitle handling follows the verified Matroska
    contract (copy, mov_text-to-srt fallback); anything else
    refuses via the MKV stream policy. No faststart (MP4-only),
    no hvc1 tag (MP4-specific).
    """

    params = dict(parameters or {})

    crf_value = HEVC_CRF_VALUES.get(
        params.get("quality", "crf_22"),
        22,
    )

    preset = params.get("preset", "medium")

    map_args, subtitle_codec_args = _mkv_stream_policy_args(
        OPERATION_CODEC_CONVERSION_MKV, source_summary
    )

    argv = (
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", source_path,
        ]
        + map_args
        + [
            "-c:v", "libx265",
            "-preset", str(preset),
            "-crf", str(crf_value),
            "-c:a", "copy",
        ]
        + subtitle_codec_args
        + [
            "-f", "matroska",
        ]
    )

    argv.extend(_hdr_color_args(source_summary))

    argv.append(output_path)

    return argv


_ARGV_BUILDERS = {
    OPERATION_REMUX_MP4: _remux_mp4_argv,
    OPERATION_CODEC_CONVERSION: _codec_conversion_argv,
    OPERATION_CODEC_CONVERSION_MKV: _codec_conversion_mkv_argv,
}


def build_argv(
    *,
    operation,
    source_path,
    output_path,
    parameters=None,
    source_summary=None,
):
    """
    Build the argument list for one permitted operation.

    The operation must be registered AND explicitly executable in the
    closed registry; a non-executable operation (executable=False) is
    refused here, at the actual FFmpeg-command boundary, regardless of
    how it was requested. `require_operation`-style registration alone
    is never sufficient. Parameter dicts are validated against the
    operation definition before argv is built. The probed source
    stream inventory (`source_summary["streams"]`, as produced by
    `probe_file_summary`) is required so stream mapping is explicit
    and deterministic; unsupported layouts refuse with a NAMOA-level
    error instead of depending on FFmpeg automatic selection.
    """

    definition = get_operation(operation)

    if definition is None:
        raise ValueError(
            f"operation '{operation}' is not registered"
        )

    if operation not in EXECUTABLE_OPERATIONS:
        raise ValueError(
            f"operation '{operation}' is not executable; "
            "only the closed executable operation set may be "
            "passed to FFmpeg"
        )

    builder = _ARGV_BUILDERS.get(operation)

    if builder is None:
        raise ValueError(
            f"operation '{operation}' has no argv builder"
        )

    return builder(
        source_path=source_path,
        output_path=output_path,
        parameters=parameters,
        source_summary=source_summary,
    )


def run_ffmpeg(argv, timeout=EXECUTION_TIMEOUT_SECONDS):
    """
    Execute one FFmpeg invocation safely.

    Returns (returncode, stdout_tail, stderr_tail). The caller owns
    every decision; this function only runs the process.
    """

    completed = subprocess.run(
        list(argv),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    return (
        completed.returncode,
        (completed.stdout or "")[-2000:],
        (completed.stderr or "")[-2000:],
    )


class PreviewTimeout(Exception):
    """A bounded Preview generation exceeded its timeout."""


class PreviewCancelled(Exception):
    """A bounded Preview generation was cancelled before completion."""


#: Address-space ceiling for Preview ffmpeg processes, bytes.
#: Live evidence (1080p Blu-ray remux, 12 sparse PGS copy
#: streams): the pipeline can wedge with output frozen while
#: memory grows linearly past 11GB until the host OOM-killer
#: SIGKILLs it. No argv-level bound fixes that layout (mux
#: queue caps, demux thread queues, timestamp flags, encoder
#: speed/threads all exonerated by experiment); the failure
#: mode is host-threatening, so the preview runner contains it
#: here instead. Legitimate previews peak far below this
#: (measured ~0.6GB at 1080p, ~2GB at 4K, medium preset), so
#: the ceiling only ever trips on pathological growth, which
#: then fails fast and truthfully instead of endangering the
#: host. Codec, preset, CRF, resolution, streams, and window
#: are untouched: this bounds the sandbox, not the operation.
PREVIEW_MAX_ADDRESS_SPACE_BYTES = 4 * 1024**3


def _preview_address_space_limit():
    """RLIMIT_AS ceiling for preview children, or None.

    None on platforms without the resource module (or any
    lookup failure): the cap is best-effort hardening, never a
    correctness requirement, so absence degrades to today's
    behaviour rather than refusing to run.
    """

    try:
        import resource
    except ImportError:
        return None

    try:
        return int(PREVIEW_MAX_ADDRESS_SPACE_BYTES)
    except (TypeError, ValueError):
        return None


def _preview_child_limits():
    """preexec_fn confining one preview child process.

    Performs only the setrlimit syscall: no locks, no
    allocation, safe in the forked child of a threaded
    server. A missing resource module means no confinement.
    """

    try:
        import resource
    except ImportError:
        return

    limit = _preview_address_space_limit()

    if limit is None:
        return

    try:
        resource.setrlimit(
            resource.RLIMIT_AS, (limit, limit)
        )
    except (OSError, ValueError):
        return


#: Upper bound on x265 thread pools for Preview encodes.
#: x265 frame-thread memory scales with resolution and pool
#: count (measured ~330MB at 720p, ~580MB at 1080p, medium
#: preset); uncapped pools on many-core hosts can exhaust small
#: hosts on 4K sources and die with SIGKILL (-9). This bounds
#: only execution resources for the temporary comparison
#: sample: codec, preset, CRF, and resolution are unchanged, so
#: the previewed transformation semantics are preserved.
PREVIEW_X265_MAX_POOLS = 4


def _preview_resource_args(argv):
    """Preview-only resource bounds appended before the output.

    Currently caps x265 thread pools when the argv performs a
    libx265 encode; stream-copy operations are untouched.
    Returns [] when no bound applies.
    """

    if "-c:v" not in argv or "libx265" not in argv:
        return []

    import os

    try:
        pools = max(
            1, min(PREVIEW_X265_MAX_POOLS, os.cpu_count() or 4)
        )
    except (TypeError, ValueError):
        pools = PREVIEW_X265_MAX_POOLS

    return ["-x265-params", f"pools={pools}"]


def build_preview_argv(
    *,
    operation,
    source_path,
    output_path,
    start_seconds,
    duration_seconds,
    parameters=None,
    source_summary=None,
    ffmpeg_binary="ffmpeg",
):
    """
    Build the argument list for one bounded Preview segment.

    The segment reuses the registered operation builder for
    `operation` (same codec/bitrate/resolution semantics as
    execution) and applies only input seeking plus a duration
    limit on top:

    - ``-ss <start>`` is placed before ``-i`` (input seeking:
      fast, keyframe-approximate; Preview timestamps are
      therefore approximate and this is reported honestly)
    - ``-t <duration>`` is placed after ``-i`` as an output
      option. It caps the output length without triggering the
      input-side subtitle buffering that can grow without bound
      when text subtitles are converted to MP4 ``mov_text``.
    - when the operation performs a libx265 encode, x265 thread
      pools are capped (preview-only resource bound; codec,
      preset, CRF, and resolution are unchanged)

    No preview-specific transformation logic exists: the operation
    must be registered and executable, and parameters are the
    already-validated operation parameters. Start/duration are
    coerced to finite non-negative numbers here so no caller
    string can reach the argument vector.
    """

    try:
        start = float(start_seconds)
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        raise ValueError(
            "preview start and duration must be numbers"
        )

    if not (start == start and duration == duration):
        raise ValueError(
            "preview start and duration must be finite numbers"
        )

    if start < 0 or duration <= 0:
        raise ValueError(
            "preview start must be >= 0 and duration must be > 0"
        )

    base = build_argv(
        operation=operation,
        source_path=source_path,
        output_path=output_path,
        parameters=parameters,
        source_summary=source_summary,
    )

    argv = list(base)

    if not argv:
        raise ValueError("empty argv from operation builder")

    argv[0] = ffmpeg_binary

    try:
        input_index = argv.index("-i")
    except ValueError:
        raise ValueError(
            "operation argv has no -i operand; cannot bound "
            "a preview segment"
        )

    argv[input_index:input_index] = [
        "-ss",
        repr(start),
    ]

    # Keep the duration bound as an output option. Placing ``-t``
    # before ``-i`` makes FFmpeg treat it as an input limit; with
    # text subtitles converted to MP4 mov_text, that layout can
    # buffer without bound and exhaust host memory.
    argv[-1:-1] = [
        "-t",
        repr(duration),
    ]

    output_path = argv[-1]

    argv[-1:] = _preview_resource_args(argv) + [output_path]

    return argv


def run_preview(
    argv,
    *,
    timeout,
    cancel_event=None,
):
    """
    Execute one bounded Preview generation with termination.

    Uses Popen (never a shell) so a hung or over-long process can
    be terminated: on timeout the process is terminated, given a
    short grace period, then killed. An optional
    ``threading.Event`` cancels generation the same way. Partial
    output removal is the caller's responsibility (the Preview
    lifecycle always cleans up after failure, timeout, or cancel).

    Returns (returncode, stdout_tail, stderr_tail).
    Raises PreviewTimeout / PreviewCancelled instead of returning
    a failure both cases can be reported truthfully.

    The child runs under an address-space ceiling (see
    ``PREVIEW_MAX_ADDRESS_SPACE_BYTES``): pathological growth
    fails fast with an allocator error instead of inviting a
    host OOM-kill. Legitimate previews peak far below it.
    """

    process = subprocess.Popen(
        list(argv),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=_preview_child_limits,
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout)

    except subprocess.TimeoutExpired:
        process.terminate()

        try:
            stdout, stderr = process.communicate(timeout=10)

        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

        raise PreviewTimeout(
            f"preview generation exceeded {timeout}s and "
            "was terminated"
        )

    if cancel_event is not None and cancel_event.is_set():
        raise PreviewCancelled(
            "preview generation was cancelled"
        )

    return (
        process.returncode,
        (stdout or "")[-2000:],
        (stderr or "")[-2000:],
    )