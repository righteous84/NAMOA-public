"""Preview settings (Phase 17).

Operational Preview settings live in a tracked default file,
``config/preview.json``, following the ``config/evidence_weights.json``
precedent. The loader validates every value; invalid configuration
fails loudly at load time rather than silently altering Preview
behaviour. No migration is involved: settings are operational, not
library state.
"""

import json
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "preview.json"


#: Preview sample length in seconds.
DEFAULT_DURATION_SECONDS = 10.0

#: Bounded generation timeout in seconds. Preview encodes at most a
#: short segment, so this is deliberately far below the production
#: execution timeout.
DEFAULT_GENERATION_TIMEOUT_SECONDS = 180

#: Maximum preview artifact age in seconds before expiry sweeps
#: consider it stale (server restart always sweeps orphans first).
DEFAULT_MAX_ARTIFACT_AGE_SECONDS = 24 * 3600

#: Maximum preview artifacts retained per lineage.
DEFAULT_MAX_ARTIFACTS_PER_LINEAGE = 3

#: Maximum preview output size in bytes. Generation refuses to keep
#: outputs beyond this bound.
DEFAULT_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PreviewSettings:
    """Validated operational Preview settings."""

    duration_seconds: float = DEFAULT_DURATION_SECONDS
    generation_timeout_seconds: int = (
        DEFAULT_GENERATION_TIMEOUT_SECONDS
    )
    max_artifact_age_seconds: int = (
        DEFAULT_MAX_ARTIFACT_AGE_SECONDS
    )
    max_artifacts_per_lineage: int = (
        DEFAULT_MAX_ARTIFACTS_PER_LINEAGE
    )
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    preview_dir: str | None = None
    ffmpeg_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "duration_seconds": self.duration_seconds,
            "generation_timeout_seconds": (
                self.generation_timeout_seconds
            ),
            "max_artifact_age_seconds": (
                self.max_artifact_age_seconds
            ),
            "max_artifacts_per_lineage": (
                self.max_artifacts_per_lineage
            ),
            "max_artifact_bytes": self.max_artifact_bytes,
            "preview_dir": self.preview_dir,
            "ffmpeg_path": self.ffmpeg_path,
        }


def _require_number(name, value, *, minimum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"preview setting '{name}' must be a number"
        )

    if number != number:
        raise ValueError(
            f"preview setting '{name}' must be finite"
        )

    if minimum is not None and number < minimum:
        raise ValueError(
            f"preview setting '{name}' must be >= {minimum}"
        )

    return number


def _require_int(name, value, *, minimum=None):
    number = _require_number(name, value, minimum=minimum)

    if int(number) != number:
        raise ValueError(
            f"preview setting '{name}' must be an integer"
        )

    return int(number)


def load_settings(config_path=None) -> PreviewSettings:
    """
    Load and validate Preview settings. Missing file means
    defaults; present-but-invalid file raises ValueError. Unknown
    keys are rejected so typos fail loudly.
    """

    path = (
        Path(config_path)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    )

    payload = {}

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(
                f"preview settings file '{path}' cannot be "
                f"read as JSON: {error}"
            )

        if not isinstance(payload, dict):
            raise ValueError(
                f"preview settings file '{path}' must contain "
                "a JSON object"
            )

    known = {
        "duration_seconds",
        "generation_timeout_seconds",
        "max_artifact_age_seconds",
        "max_artifacts_per_lineage",
        "max_artifact_bytes",
        "preview_dir",
        "ffmpeg_path",
    }

    unknown = sorted(set(payload) - known)

    if unknown:
        raise ValueError(
            "unknown preview setting(s): " + ", ".join(unknown)
        )

    preview_dir = payload.get("preview_dir")

    if preview_dir is not None:
        preview_dir = str(preview_dir).strip() or None

    ffmpeg_path = payload.get("ffmpeg_path")

    if ffmpeg_path is not None:
        ffmpeg_path = str(ffmpeg_path).strip() or None

    return PreviewSettings(
        duration_seconds=_require_number(
            "duration_seconds",
            payload.get(
                "duration_seconds", DEFAULT_DURATION_SECONDS
            ),
            minimum=1.0,
        ),
        generation_timeout_seconds=_require_int(
            "generation_timeout_seconds",
            payload.get(
                "generation_timeout_seconds",
                DEFAULT_GENERATION_TIMEOUT_SECONDS,
            ),
            minimum=10,
        ),
        max_artifact_age_seconds=_require_int(
            "max_artifact_age_seconds",
            payload.get(
                "max_artifact_age_seconds",
                DEFAULT_MAX_ARTIFACT_AGE_SECONDS,
            ),
            minimum=60,
        ),
        max_artifacts_per_lineage=_require_int(
            "max_artifacts_per_lineage",
            payload.get(
                "max_artifacts_per_lineage",
                DEFAULT_MAX_ARTIFACTS_PER_LINEAGE,
            ),
            minimum=1,
        ),
        max_artifact_bytes=_require_int(
            "max_artifact_bytes",
            payload.get(
                "max_artifact_bytes", DEFAULT_MAX_ARTIFACT_BYTES
            ),
            minimum=1024 * 1024,
        ),
        preview_dir=preview_dir,
        ffmpeg_path=ffmpeg_path,
    )
