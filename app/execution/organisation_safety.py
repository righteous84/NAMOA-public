"""
Deterministic organisation filesystem safety boundary (Sprint 14).

This module is the ONLY place that decides whether an organisation
filesystem mutation is SAFE. Its decisions are pure and deterministic
(code-driven, never AI). Organisation intelligence, recommendation,
policy and proposal code must never call filesystem mutation
primitives directly; they must pass through this boundary.

Responsibilities:

- canonical path handling (no reliance on string-prefix checks)
- library boundary enforcement (resolved containment)
- symlink safety (a path is rejected if any component is a symlink)
- source validation (exists, regular file, not a symlink)
- destination validation (inside boundary, no unsafe parent symlinks,
  no existing object -> collision prevention)
- path traversal / ambiguity rejection

A path that appears inside the library lexically but resolves outside
the authorised boundary is rejected. A path that is not symlink-free
is rejected rather than silently dereferenced.
"""

import os

from pathlib import Path


class OrganisationSafetyError(ValueError):
    """Raised when a filesystem operation is not deterministically safe."""


def canonical(path) -> str:
    """
    Lexically-normalised absolute form of a path.
    """
    return os.path.abspath(os.path.expanduser(path))


def has_symlink_component(path) -> bool:
    """
    True if any path component from the nearest existing ancestor to
    the leaf is a symlink.

    Walks only as far as the deepest existing ancestor so that a
    destination whose leaf does not exist yet can still be validated
    for unsafe parent-directory symlinks.
    """

    current = canonical(path)

    stack = []

    probe = current

    # Walk up to the deepest existing ancestor.
    while not os.path.lexists(probe):

        parent, base = os.path.split(probe)

        if parent == probe:
            break

        stack.append(base)

        probe = parent

    segments = [probe]

    for segment in reversed(stack):

        probe = os.path.join(probe, segment)

        segments.append(probe)

    for segment in segments:

        if os.path.islink(segment):

            return True

    return False


def resolve_roots(roots) -> list[str]:
    """
    Deterministic, deduplicated, ordered set of canonical library
    boundary roots. Entries may be plain paths or {path, alias}
    profile roots; aliases never reach the filesystem.
    """

    resolved = []

    seen = set()

    for root in roots or ():

        if isinstance(root, dict):
            root = root.get("path")

        if not isinstance(root, str) or not root.strip():
            continue

        value = os.path.realpath(root)

        if value in seen:

            continue

        seen.add(value)

        resolved.append(value)

    return resolved


def is_within_boundary(path, roots) -> bool:
    """
    True when the resolved canonical path lies inside at least one
    resolved boundary root. Uses realpath so a path that lexically
    appears inside but resolves outside (or vice versa) is judged by
    its real location, never by string prefix.
    """

    if not roots:

        return False

    resolved = os.path.realpath(path)

    for root in roots:

        if Path(resolved).is_relative_to(Path(root)):

            return True

    return False


def require_boundary_roots(roots) -> list[str]:
    """
    Return the resolved boundary roots or raise; a move cannot be
    authorised without an explicit library boundary.
    """

    resolved = resolve_roots(roots)

    if not resolved:

        raise OrganisationSafetyError(
            "no authorised library boundary is configured; "
            "organisation execution requires at least one library root"
        )

    return resolved


def validate_source(path, roots) -> os.stat_result:
    """
    Validate the source object immediately before mutation.

    Returns the lstat result. Raises OrganisationSafetyError on any
    safety violation.
    """

    roots_resolved = require_boundary_roots(roots)

    if not os.path.lexists(path):

        raise OrganisationSafetyError(
            f"source does not exist: {path}"
        )

    if os.path.islink(path):

        raise OrganisationSafetyError(
            f"source is a symlink; refusing: {path}"
        )

    if has_symlink_component(path):

        raise OrganisationSafetyError(
            f"source path contains a symlink component; "
            f"refusing: {path}"
        )

    if not os.path.isfile(path):

        raise OrganisationSafetyError(
            f"source is not a regular file: {path}"
        )

    if not is_within_boundary(path, roots_resolved):

        raise OrganisationSafetyError(
            f"source resolves outside the authorised library "
            f"boundary: {path}"
        )

    return os.stat(path)


def validate_destination(path, roots, *, must_be_absent=True) -> None:
    """
    Validate the destination immediately before mutation.

    - destination must resolve inside the authorised boundary
    - no path component of the destination may be a symlink
    - the destination must not already contain an object (collision
      and overwrite prevention)

    Raises OrganisationSafetyError on any violation.
    """

    roots_resolved = require_boundary_roots(roots)

    if not is_within_boundary(path, roots_resolved):

        raise OrganisationSafetyError(
            f"destination resolves outside the authorised library "
            f"boundary: {path}"
        )

    if has_symlink_component(path):

        raise OrganisationSafetyError(
            f"destination path contains a symlink component; "
            f"refusing: {path}"
        )

    if must_be_absent and os.path.lexists(path):

        raise OrganisationSafetyError(
            f"destination already exists; refusing to overwrite or "
            f"replace it: {path}"
        )


def ensure_destination_parent(path) -> None:
    """
    Deterministically create the destination parent directory (and any
    missing ancestors) so the move can place the object. Callers must
    have already validated the destination is inside the boundary and
    is symlink-free; this never follows a symlink it did not create.
    """

    parent = os.path.dirname(canonical(path))

    if not parent:

        return

    os.makedirs(parent, exist_ok=True)


# ---------------------------------------------------------
# Sprint 15: directory-scope validation
# ---------------------------------------------------------

def validate_directory_source(path, roots) -> os.stat_result:
    """
    Validate a directory source immediately before a
    structural mutation. Mirrors `validate_source` with
    directory semantics: exists, real directory, not a
    symlink, no symlink components, inside the boundary.
    File-only validation is unchanged.
    """

    roots_resolved = require_boundary_roots(roots)

    if not os.path.lexists(path):

        raise OrganisationSafetyError(
            f"directory source does not exist: {path}"
        )

    if os.path.islink(path):

        raise OrganisationSafetyError(
            f"directory source is a symlink; refusing: {path}"
        )

    if has_symlink_component(path):

        raise OrganisationSafetyError(
            f"directory source path contains a symlink "
            f"component; refusing: {path}"
        )

    if not os.path.isdir(path):

        raise OrganisationSafetyError(
            f"directory source is not a directory: {path}"
        )

    if not is_within_boundary(path, roots_resolved):

        raise OrganisationSafetyError(
            f"directory source resolves outside the "
            f"authorised library boundary: {path}"
        )

    return os.stat(path)


def validate_directory_destination(
    path,
    roots,
    *,
    must_be_absent=True,
) -> None:
    """
    Validate a directory destination immediately before a
    structural mutation. Same guarantees as
    `validate_destination`: inside the boundary, no
    symlink components, and (by default) absent so no
    existing object is ever merged into or overwritten.
    """

    roots_resolved = require_boundary_roots(roots)

    if not is_within_boundary(path, roots_resolved):

        raise OrganisationSafetyError(
            f"directory destination resolves outside the "
            f"authorised library boundary: {path}"
        )

    if has_symlink_component(path):

        raise OrganisationSafetyError(
            f"directory destination path contains a "
            f"symlink component; refusing: {path}"
        )

    if must_be_absent and os.path.lexists(path):

        raise OrganisationSafetyError(
            f"directory destination already exists; "
            f"refusing to merge into or replace it: {path}"
        )


def subtree_file_manifest(root) -> dict:
    """
    Read-only manifest of regular files under a directory:
    relative path -> (size_bytes, mtime_ns). Symlinks are
    recorded by presence only (never followed) so the
    caller can refuse impure trees. Raises
    OrganisationSafetyError when the tree cannot be
    listed deterministically.
    """

    manifest = {}

    try:
        walker = os.walk(root, followlinks=False)
        entries = sorted(
            (directory, sorted(directories), sorted(files))
            for directory, directories, files in walker
        )
    except OSError as error:
        raise OrganisationSafetyError(
            f"cannot list directory tree for manifest: "
            f"{root}: {error}"
        ) from error

    for directory, _directories, files in entries:
        for name in files:
            full = os.path.join(directory, name)

            try:
                if os.path.islink(full):
                    manifest[os.path.relpath(full, root)] = (
                        "symlink",
                    )
                    continue

                if not os.path.isfile(full):
                    manifest[os.path.relpath(full, root)] = (
                        "special",
                    )
                    continue

                stat = os.stat(full)

                manifest[os.path.relpath(full, root)] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )
            except OSError as error:
                raise OrganisationSafetyError(
                    f"cannot stat tree member for manifest: "
                    f"{full}: {error}"
                ) from error

    return manifest
