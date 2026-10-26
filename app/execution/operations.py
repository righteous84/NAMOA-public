"""
Closed, versioned executable-operation registry (Phase 6).

The registry is the sole source of truth for executable operations:

- what operations exist and whether they are executable
- their supported parameters, types, ranges/enums and defaults
- their argv construction (still only through app.execution.ffmpeg)
- their verification expectations and expected output characteristics
- their risk classification and whether storage savings may be claimed

No free-form FFmpeg argument entry exists anywhere. Advanced controls
expose operation capabilities ONLY through this registry (via the
application OperationService boundary).

The initial executable set is deliberately narrow:

    remux_mp4          stream-copy container remux (existing)
    codec_conversion   H.264 -> HEVC re-encode (Phase 6C)

Other operations are registered as DEFINED BUT NOT EXECUTABLE so the
registry shape is complete and later operations can be added without
redesigning ExecutionService. The instruction explicitly forbids broad
codec conversion, AV1, and arbitrary encoders in this phase.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


# Operation identifiers. Registry keys, not free-form strings.
OPERATION_REMUX_MP4 = "remux_mp4"
OPERATION_CODEC_CONVERSION = "codec_conversion"
OPERATION_CODEC_CONVERSION_MKV = "codec_conversion_mkv"

# Defined but not executable in this phase (registered for the closed
# registry and for planning/verification design, gated off).
OPERATION_RESOLUTION_REDUCTION = "resolution_reduction"
OPERATION_BITRATE_REDUCTION = "bitrate_reduction"
OPERATION_AUDIO_CONVERSION = "audio_conversion"
OPERATION_AUDIO_STREAM_REMOVAL = "audio_stream_removal"
OPERATION_CONTAINER_CONVERSION = "container_conversion"
OPERATION_AV1_CONVERSION = "av1_conversion"

#: Registry semantic version. Bump when any operation definition's
#: meaning changes (parameters, defaults, argv, verification,
#: expectations, risk, or executable status).
OPERATION_REGISTRY_VERSION = "1.1.0"

#: Proposition -> primary operation mapping (the forward mapping the
#: planner consumes; the inverse of the old remux-only special case).
PROPOSITION_TO_OPERATION = {
    "container_remux": OPERATION_REMUX_MP4,
    "codec_conversion": OPERATION_CODEC_CONVERSION,
    "resolution_reduction": OPERATION_RESOLUTION_REDUCTION,
    "bitrate_reduction": OPERATION_BITRATE_REDUCTION,
    "audio_conversion": OPERATION_AUDIO_CONVERSION,
}

#: Source video codecs acceptable to the HEVC conversion operation.
HEVC_CONVERSION_SOURCE_CODECS = frozenset({"h264"})


@dataclass(frozen=True, slots=True)
class OperationParameter:
    """
    One controlled parameter of an operation.

    `param_type` is one of: enum, int, float, bool, text.
    `allowed_values` restricts an enum.
    `min_value` / `max_value` bound numeric parameters.
    `default` is the validated default.
    """

    name: str
    param_type: str
    description: str
    allowed_values: Optional[tuple] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    default: Any = None

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "type": self.param_type,
            "description": self.description,
            "allowed_values": (
                list(self.allowed_values)
                if self.allowed_values is not None
                else None
            ),
            "min_value": self.min_value,
            "max_value": self.max_value,
            "default": self.default,
        }


@dataclass(frozen=True, slots=True)
class OperationDefinition:
    """
    One closed, versioned executable operation definition.

    `executable` separates "defined for the registry" from "may be
    executed now". A non-executable operation is never planned or run.
    """

    operation: str
    semantic_version: str
    description: str
    preconditions: dict = field(default_factory=dict)
    parameters: tuple = ()
    defaults: dict = field(default_factory=dict)
    storage_savings_expected: bool = False
    risk: str = "low"
    executable: bool = False
    expected_output: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    argv_builder: Optional[str] = None

    def parameter_schema(self) -> list:
        return [param.to_schema() for param in self.parameters]

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "semantic_version": self.semantic_version,
            "description": self.description,
            "preconditions": dict(self.preconditions),
            "parameters": self.parameter_schema(),
            "defaults": dict(self.defaults),
            "storage_savings_expected": (
                self.storage_savings_expected
            ),
            "risk": self.risk,
            "executable": self.executable,
            "expected_output": dict(self.expected_output),
            "verification": dict(self.verification),
        }


# ---------------------------------------------------------
# remux_mp4 - stream-copy container remux (existing behaviour)
# ---------------------------------------------------------

REMUX_MP4_VERIFICATION = {
    "expected_container": "mp4",
    "min_streams": 1,
}

REMUX_MP4 = OperationDefinition(
    operation=OPERATION_REMUX_MP4,
    semantic_version="1.0.0",
    description=(
        "Lossless container remux to MP4 (stream copy). "
        "Compatibility improvement; no storage saving is claimed."
    ),
    preconditions={"source_regular_file": True},
    parameters=(),
    defaults={},
    storage_savings_expected=False,
    risk="low",
    executable=True,
    expected_output={"container": "mp4"},
    verification=dict(REMUX_MP4_VERIFICATION),
    argv_builder="remux_mp4",
)


# ---------------------------------------------------------
# codec_conversion - H.264 -> HEVC (Phase 6C, deliberately narrow)
# ---------------------------------------------------------

HEVC_PARAMETERS = (
    OperationParameter(
        name="target_codec",
        param_type="enum",
        description="Target video codec (HEVC only in this phase).",
        allowed_values=("hevc",),
        default="hevc",
    ),
    OperationParameter(
        name="encoder",
        param_type="enum",
        description="HEVC encoder (libx265 in this phase).",
        allowed_values=("libx265",),
        default="libx265",
    ),
    OperationParameter(
        name="quality",
        param_type="enum",
        description=(
            "CRF quality strategy. Lower is higher quality. "
            "Controlled, versioned values only."
        ),
        allowed_values=("crf_18", "crf_20", "crf_22", "crf_24"),
        default="crf_22",
    ),
    OperationParameter(
        name="preset",
        param_type="enum",
        description=(
            "x265 preset. 'slow'/'medium'/'fast' are exposed; the "
            "user encoding-speed preference maps to this set."
        ),
        allowed_values=("slow", "medium", "fast"),
        default="medium",
    ),
)

#: CRF value per controlled quality enum (the mapping is versioned
#: registry policy, never user-supplied).
HEVC_CRF_VALUES = {
    "crf_18": 18,
    "crf_20": 20,
    "crf_22": 22,
    "crf_24": 24,
}

CODEC_CONVERSION = OperationDefinition(
    operation=OPERATION_CODEC_CONVERSION,
    semantic_version="1.0.0",
    description=(
        "Re-encode the video stream to HEVC (libx265) while "
        "preserving resolution and HDR characteristics and the "
        "existing audio streams. Storage-oriented operation: the "
        "verified output must be smaller than the source."
    ),
    preconditions={
        "source_video_codec": sorted(HEVC_CONVERSION_SOURCE_CODECS),
        "target_codec": "hevc",
    },
    parameters=HEVC_PARAMETERS,
    defaults={
        "target_codec": "hevc",
        "encoder": "libx265",
        "quality": "crf_22",
        "preset": "medium",
    },
    storage_savings_expected=True,
    risk="medium",
    executable=True,
    expected_output={
        "video_codec": "hevc",
        "preserve_resolution": True,
        "preserve_hdr": True,
        "preserve_audio": True,
    },
    verification={
        "expected_video_codec": "hevc",
        "preserve_resolution": True,
        "preserve_hdr": True,
        "preserve_audio": True,
        "smaller_than_source": True,
        "min_streams": 1,
    },
    argv_builder="codec_conversion",
)


CODEC_CONVERSION_MKV = OperationDefinition(
    operation=OPERATION_CODEC_CONVERSION_MKV,
    semantic_version="1.0.0",
    description=(
        "Re-encode the video stream to HEVC (libx265) while "
        "preserving resolution and HDR characteristics and the "
        "existing audio streams, targeting Matroska output so "
        "subtitle and chapter content with a verified Matroska "
        "preservation contract is retained. Reached only through "
        "the retention preservation-alternative mechanism and "
        "User Override, never through recommendation signals."
    ),
    preconditions={
        "source_video_codec": sorted(HEVC_CONVERSION_SOURCE_CODECS),
        "target_codec": "hevc",
    },
    parameters=HEVC_PARAMETERS,
    defaults={
        "target_codec": "hevc",
        "encoder": "libx265",
        "quality": "crf_22",
        "preset": "medium",
    },
    storage_savings_expected=True,
    risk="medium",
    executable=True,
    expected_output={
        "video_codec": "hevc",
        "container": "mkv",
        "preserve_resolution": True,
        "preserve_hdr": True,
        "preserve_audio": True,
    },
    verification={
        "expected_video_codec": "hevc",
        # Substring of the real ffprobe format_name
        # ("matroska,webm"): the engine matches with `in`.
        "expected_container": "matroska",
        "preserve_resolution": True,
        "preserve_hdr": True,
        "preserve_audio": True,
        "smaller_than_source": True,
        "min_streams": 1,
    },
    argv_builder="codec_conversion_mkv",
)


# ---------------------------------------------------------
# Defined but NOT executable in this phase (gated off)
# ---------------------------------------------------------

RESOLUTION_REDUCTION = OperationDefinition(
    operation=OPERATION_RESOLUTION_REDUCTION,
    semantic_version="1.0.0",
    description=(
        "Re-encode video at a lower resolution. Defined for the "
        "closed registry; NOT executable in this phase."
    ),
    preconditions={"source_video_codec": "any"},
    parameters=(
        OperationParameter(
            name="target_resolution",
            param_type="enum",
            description="Target resolution height (controlled).",
            allowed_values=("720", "480"),
            default="720",
        ),
    ),
    defaults={"target_resolution": "720"},
    storage_savings_expected=True,
    risk="high",
    executable=False,
    expected_output={"preserve_hdr": True},
    verification={"preserve_audio": True, "smaller_than_source": True},
    argv_builder=None,
)

BITRATE_REDUCTION = OperationDefinition(
    operation=OPERATION_BITRATE_REDUCTION,
    semantic_version="1.0.0",
    description=(
        "Re-encode to a lower target bitrate/quality. Defined for "
        "the closed registry; NOT executable in this phase."
    ),
    preconditions={"source_video_codec": "any"},
    parameters=(
        OperationParameter(
            name="quality",
            param_type="enum",
            description="Quality strategy (controlled).",
            allowed_values=("crf_20", "crf_22", "crf_24"),
            default="crf_22",
        ),
    ),
    defaults={"quality": "crf_22"},
    storage_savings_expected=True,
    risk="high",
    executable=False,
    expected_output={"preserve_hdr": True},
    verification={"preserve_audio": True, "smaller_than_source": True},
    argv_builder=None,
)

AUDIO_CONVERSION = OperationDefinition(
    operation=OPERATION_AUDIO_CONVERSION,
    semantic_version="1.0.0",
    description=(
        "Re-encode audio track(s). Defined for the closed registry; "
        "NOT executable in this phase."
    ),
    preconditions={"source_audio_tracks": 1},
    parameters=(
        OperationParameter(
            name="audio_codec",
            param_type="enum",
            description="Target audio codec (controlled).",
            allowed_values=("aac", "opus"),
            default="aac",
        ),
    ),
    defaults={"audio_codec": "aac"},
    storage_savings_expected=True,
    risk="medium",
    executable=False,
    expected_output={"audio_codec": "aac"},
    verification={"preserve_video": True, "smaller_than_source": True},
    argv_builder=None,
)

AUDIO_STREAM_REMOVAL = OperationDefinition(
    operation=OPERATION_AUDIO_STREAM_REMOVAL,
    semantic_version="1.0.0",
    description=(
        "Remove an explicitly selected redundant audio stream "
        "(stream copy). Defined for the closed registry; NOT "
        "executable in this phase."
    ),
    preconditions={"source_audio_tracks": 2},
    parameters=(),
    defaults={},
    storage_savings_expected=True,
    risk="low",
    executable=False,
    expected_output={"audio_tracks": ">=1"},
    verification={"preserve_video": True},
    argv_builder=None,
)

CONTAINER_CONVERSION = OperationDefinition(
    operation=OPERATION_CONTAINER_CONVERSION,
    semantic_version="1.0.0",
    description=(
        "Container conversion to a validated target. Defined for the "
        "closed registry; NOT executable in this phase."
    ),
    preconditions={"source_regular_file": True},
    parameters=(
        OperationParameter(
            name="target_container",
            param_type="enum",
            description="Target container (controlled).",
            allowed_values=("mkv", "mp4"),
            default="mkv",
        ),
    ),
    defaults={"target_container": "mkv"},
    storage_savings_expected=False,
    risk="low",
    executable=False,
    expected_output={},
    verification={"min_streams": 1},
    argv_builder=None,
)

AV1_CONVERSION = OperationDefinition(
    operation=OPERATION_AV1_CONVERSION,
    semantic_version="1.0.0",
    description=(
        "Re-encode to AV1. Explicitly out of scope for this phase; "
        "defined so the registry is complete and the boundary is "
        "closed."
    ),
    preconditions={"source_video_codec": "any"},
    parameters=(),
    defaults={},
    storage_savings_expected=True,
    risk="high",
    executable=False,
    expected_output={"video_codec": "av1"},
    verification={"preserve_hdr": True, "smaller_than_source": True},
    argv_builder=None,
)


#: The closed registry.
OPERATIONS: dict = {
    OPERATION_REMUX_MP4: REMUX_MP4,
    OPERATION_CODEC_CONVERSION: CODEC_CONVERSION,
    OPERATION_CODEC_CONVERSION_MKV: CODEC_CONVERSION_MKV,
    OPERATION_RESOLUTION_REDUCTION: RESOLUTION_REDUCTION,
    OPERATION_BITRATE_REDUCTION: BITRATE_REDUCTION,
    OPERATION_AUDIO_CONVERSION: AUDIO_CONVERSION,
    OPERATION_AUDIO_STREAM_REMOVAL: AUDIO_STREAM_REMOVAL,
    OPERATION_CONTAINER_CONVERSION: CONTAINER_CONVERSION,
    OPERATION_AV1_CONVERSION: AV1_CONVERSION,
}

#: The set of operations that may currently be executed.
EXECUTABLE_OPERATIONS = frozenset(
    operation
    for operation, definition in OPERATIONS.items()
    if definition.executable
)


def get_operation(operation: str) -> OperationDefinition:
    """
    The operation definition, or None when the operation is unknown.
    """

    return OPERATIONS.get(operation)


def require_operation(operation: str) -> OperationDefinition:
    """
    The operation definition; raises ValueError for unknown
    operations so an unregistered operation can never be planned.
    """

    definition = OPERATIONS.get(operation)

    if definition is None:
        raise ValueError(
            f"operation '{operation}' is not registered"
        )

    return definition


def validate_parameters(
    operation: str,
    parameters: dict | None,
) -> dict:
    """
    Validate a parameter dict against the operation definition.

    - unknown parameters are rejected
    - enum parameters must be in allowed_values
    - numeric parameters must be within min/max
    - missing parameters fall back to the definition defaults
    - the result is the validated parameter dict (closed set)

    Raises ValueError for any invalid value.
    """

    definition = require_operation(operation)

    schema = {p.name: p for p in definition.parameters}

    supplied = dict(parameters or {})

    validated = dict(definition.defaults)

    for name, value in supplied.items():

        if name not in schema:
            raise ValueError(
                f"operation '{operation}' does not accept "
                f"parameter '{name}'"
            )

        param = schema[name]

        if param.param_type == "enum":
            if param.allowed_values is not None and (
                value not in param.allowed_values
            ):
                raise ValueError(
                    f"parameter '{name}' must be one of "
                    f"{sorted(param.allowed_values)}"
                )

        elif param.param_type == "int":
            value = int(value)
            if param.min_value is not None and (
                value < param.min_value
            ):
                raise ValueError(
                    f"parameter '{name}' must be >= "
                    f"{param.min_value}"
                )
            if param.max_value is not None and (
                value > param.max_value
            ):
                raise ValueError(
                    f"parameter '{name}' must be <= "
                    f"{param.max_value}"
                )

        elif param.param_type == "float":
            value = float(value)
            if param.min_value is not None and (
                value < param.min_value
            ):
                raise ValueError(
                    f"parameter '{name}' must be >= "
                    f"{param.min_value}"
                )
            if param.max_value is not None and (
                value > param.max_value
            ):
                raise ValueError(
                    f"parameter '{name}' must be <= "
                    f"{param.max_value}"
                )

        elif param.param_type == "bool":
            value = bool(value)

        validated[name] = value

    return validated


def operation_for_proposition(proposition: str) -> str:
    """
    The primary operation for a proposition, or None when the
    proposition has no executable operation.
    """

    return PROPOSITION_TO_OPERATION.get(proposition)


def registry_policy_values() -> dict:
    """
    The attributable registry snapshot (participates in execution
    provenance).
    """

    return {
        "version": OPERATION_REGISTRY_VERSION,
        "executable_operations": sorted(EXECUTABLE_OPERATIONS),
        "proposition_to_operation": dict(PROPOSITION_TO_OPERATION),
        "hevc_crf_values": dict(HEVC_CRF_VALUES),
    }