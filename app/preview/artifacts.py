"""Preview artifact lifecycle (Phase 17).

Application-owned temporary Preview area with ownership markers:

- directory: ``data/previews/`` by default (overridable via
  settings or ``NAMOA_PREVIEW_DIR``); never a scanned library root
  by operator contract, and the scanner additionally skips it
- files: ``.namoa-preview-<token>.mp4`` plus a ``.json`` manifest
  sidecar recording token, lineage, observation, and creation time
- ownership: the ``.namoa-preview-`` prefix plus manifest; cleanup
  only ever considers these names inside the preview directory
- traversal/symlink safety: every served or deleted path is
  resolved and verified to stay inside the preview directory;
  symlinks are refused

Artifacts are transient: deleted when the Preview context closes,
on Accept/Reject, on expiry, and by the startup sweep. They never
enter the scan, never become observations, and are never treated
as library source media.
"""

import json
import os
import time
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PREVIEW_DIR = PACKAGE_ROOT / "data" / "previews"

PREVIEW_ENV_VAR = "NAMOA_PREVIEW_DIR"

ARTIFACT_PREFIX = ".namoa-preview-"

ARTIFACT_SUFFIX = ".mp4"

MANIFEST_SUFFIX = ".json"

#: Staging suffixes for in-progress Preview writes: the ffmpeg
#: output (``.part``) written beside the final artifact name, and
#: the atomic-write temporary manifest (``.tmp``). All three
#: non-staging suffixes plus these two are owned Preview names;
#: the prefix requirement keeps unrelated ``.part``/``.tmp`` files
#: elsewhere untouched.
STAGING_SUFFIXES = (".part", ".tmp")

OWNED_SUFFIXES = (
    ARTIFACT_SUFFIX,
    MANIFEST_SUFFIX,
    *STAGING_SUFFIXES,
)


def resolve_preview_dir(explicit=None) -> Path:
    """Application-managed preview directory (created on demand)."""

    configured = explicit or os.environ.get(PREVIEW_ENV_VAR, "")

    configured = str(configured or "").strip()

    directory = (
        Path(configured) if configured else DEFAULT_PREVIEW_DIR
    )

    directory.mkdir(parents=True, exist_ok=True)

    return directory


def artifact_paths(directory, token):
    """(media_path, manifest_path) for one preview token."""

    safe = "".join(
        character
        for character in str(token)
        if character.isalnum() or character in ("-", "_")
    )

    if not safe:
        raise ValueError("preview token is empty")

    base = ARTIFACT_PREFIX + safe

    return (
        Path(directory) / (base + ARTIFACT_SUFFIX),
        Path(directory) / (base + MANIFEST_SUFFIX),
    )


def write_manifest(manifest_path, payload):
    """Atomically write the ownership manifest sidecar."""

    manifest_path = Path(manifest_path)

    tmp_path = manifest_path.with_suffix(".tmp")

    tmp_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    os.replace(tmp_path, manifest_path)


def read_manifest(manifest_path):
    """Read an ownership manifest, or None when absent/invalid."""

    try:
        return json.loads(
            Path(manifest_path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None


def _is_owned_name(name):
    return name.startswith(ARTIFACT_PREFIX) and name.endswith(
        OWNED_SUFFIXES
    )


def _contained(path, directory):
    """True when path resolves inside directory (no escape)."""

    try:
        resolved = Path(path).resolve()
        anchored = Path(directory).resolve()
    except OSError:
        return False

    if resolved.is_symlink() or not resolved.is_file():
        # Missing files are handled by callers; symlinks never.
        if resolved.is_symlink():
            return False

    return resolved == anchored or anchored in resolved.parents


def owned_artifact_paths(directory):
    """All owned artifact paths currently in the directory."""

    directory = Path(directory)

    if not directory.is_dir():
        return []

    return sorted(
        (
            entry
            for entry in directory.iterdir()
            if _is_owned_name(entry.name)
        ),
        key=lambda entry: entry.name,
    )


def remove_owned(path, directory):
    """Delete one owned artifact after containment verification."""

    if not _contained(path, directory):
        raise ValueError(
            "refusing to delete outside the preview directory"
        )

    if Path(path).is_dir():
        raise ValueError(
            "refusing to delete a directory during preview "
            "cleanup"
        )

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def sweep_orphans(directory, *, active_tokens=(), max_age_seconds=None):
    """
    Delete owned artifacts that are no longer active (server
    restart orphans, expired contexts). Returns
    {"removed": [...names...], "kept": [...names...]}. Only owned
    names inside the directory are considered; unrelated files are
    never touched.
    """

    now = time.time()

    removed = []

    kept = []

    active = {str(token) for token in (active_tokens or ())}

    for path in owned_artifact_paths(directory):
        # Directories (even owned-looking ones) are never removed
        # and never abort the sweep; only regular files are
        # considered for deletion.
        try:
            if path.is_dir():
                kept.append(path.name)
                continue
        except OSError:
            kept.append(path.name)
            continue

        stem = path.name[len(ARTIFACT_PREFIX):]

        for suffix in OWNED_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break

        if stem in active:
            kept.append(path.name)
            continue

        if max_age_seconds is not None:
            try:
                age = now - path.stat().st_mtime
            except OSError:
                age = None

            if age is not None and age < max_age_seconds:
                kept.append(path.name)
                continue

        try:
            remove_owned(path, directory)
        except OSError:
            # One malformed or unremovable entry must not abort
            # cleanup of the remaining entries.
            kept.append(path.name)
            continue

        removed.append(path.name)

    return {"removed": removed, "kept": kept}
