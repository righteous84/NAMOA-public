"""
Cross-platform path rules (Sprint 15).

Platform-safe path handling for organisation templates,
rendered destinations, collision detection, and root
containment. Uses `os.path` semantics with no hardcoded
POSIX assumptions.

Rules enforced here (and only here, so every consumer
shares one definition):

- canonicalization: absolute, normalised, symlink-resolved
  real path for containment decisions; lexical
  normalisation for display
- case semantics: normcase-aware comparison on
  case-insensitive platforms (Windows), exact forms on
  POSIX; the target platform rule travels with validated
  configuration
- separators: `os.sep`/`os.path` joining and splitting
  only; foreign separators inside a single path
  component are rejected at validation
- illegal characters: Windows set rejected on Windows
  targets, `/` and NUL rejected on POSIX, enforced per
  rendered component
- Windows reserved names rejected (CON, PRN, AUX, NUL,
  COM1-9, LPT1-9, trailing dots/spaces)
- traversal prevention: normalised paths must remain
  contained in a configured root (realpath
  `is_relative_to` check); `..` escapes rejected
- root containment: every rendered destination must
  resolve inside a configured, preflight-checked root
- normalization: redundant separators and `.` segments
  collapsed; empty components rejected with fallback
  to review state
- collision handling: normcase-aware existence check at
  plan time; deterministic suffixing only as explicit
  opt-in policy, never a silent side effect

Pure functions only. No filesystem mutation. Existence
checks (`os.path.lexists`) are read-only and safe for
planning; execution-time validation remains
authoritative.
"""

import os
import re

from pathlib import Path


#: Illegal characters on Windows targets (plus C0-C31).
WINDOWS_ILLEGAL_CHARS = frozenset('<>:"/\\|?*')

#: Windows reserved basenames (without extension).
WINDOWS_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

#: Collision policies (closed set).
COLLISION_REVIEW = "review"

COLLISION_SUFFIX = "suffix"

COLLISION_POLICIES = frozenset(
    {COLLISION_REVIEW, COLLISION_SUFFIX}
)


def target_is_windows(platform: str | None = None) -> bool:
    """
    Whether path rules should apply Windows semantics.
    Defaults to the runtime platform (`os.name == "nt"`).
    An explicit `platform` of "windows"/"posix" overrides
    it for validated configuration portability checks.
    """

    if platform is None:
        return os.name == "nt"

    return str(platform).strip().lower() == "windows"


def canonical_display(path: str) -> str:
    """
    Lexically normalised absolute form for display and
    stable comparison. No symlink resolution, no
    filesystem access beyond abspath.
    """

    return os.path.normpath(os.path.abspath(str(path)))


def canonical_real(path: str) -> str:
    """
    Symlink-resolved absolute form for containment and
    identity decisions. Touches the filesystem only to
    resolve links (read-only).
    """

    return os.path.realpath(os.path.abspath(str(path)))


def normcase_compare(path: str, *, windows: bool | None = None) -> str:
    """
    Comparison key for collision and containment checks:
    casefolded on case-insensitive platforms (Windows),
    exact otherwise.
    """

    value = canonical_display(path)

    if windows is None:
        windows = target_is_windows()

    if windows:
        return value.casefold()

    return value


def split_components(path: str) -> list:
    """
    Split a path into components using `os.path` semantics
    only. A backslash on POSIX is an ordinary filename
    character and is preserved; validation decides what
    is legal for the target platform.
    """

    parts = []

    for part in str(path).split(os.sep):
        if part not in ("", "."):
            parts.append(part)

    return parts


def validate_component(
    component: str,
    *,
    windows: bool | None = None,
) -> str | None:
    """
    Validate one rendered path component. Returns None when
    valid, otherwise a human-readable reason. Empty
    components, traversal segments, illegal characters,
    and reserved names are all rejected.
    """

    if windows is None:
        windows = target_is_windows()

    if not isinstance(component, str) or not component:
        return "empty path component"

    if component in (".", ".."):
        return f"path component '{component}' escapes"

    if "/" in component or "\x00" in component:
        return (
            f"path component '{component}' contains an "
            f"illegal separator or NUL"
        )

    if windows:
        bad = sorted(
            set(component) & WINDOWS_ILLEGAL_CHARS
        )
        if bad:
            return (
                f"path component '{component}' contains "
                f"illegal characters: {''.join(bad)}"
            )
        for char in component:
            if ord(char) < 32:
                return (
                    f"path component '{component}' "
                    f"contains a control character"
                )
        stem = component.split(".")[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            return (
                f"path component '{component}' is a "
                f"reserved Windows name"
            )
        if component != component.rstrip(" ."):
            return (
                f"path component '{component}' has a "
                f"trailing dot or space"
            )

    return None


def validate_rendered_path(
    path: str,
    roots: list,
    *,
    windows: bool | None = None,
) -> str | None:
    """
    Validate a fully rendered destination: every component
    must be valid and the resolved path must remain
    contained in one of the configured roots. Returns None
    when valid, otherwise a human-readable reason.
    """

    if windows is None:
        windows = target_is_windows()

    if not isinstance(path, str) or not path.strip():
        return "empty destination path"

    for component in split_components(path):
        reason = validate_component(
            component, windows=windows
        )
        if reason is not None:
            return reason

    if not is_within_roots(path, roots):
        return (
            f"destination '{path}' resolves outside the "
            f"configured organisation roots"
        )

    return None


def root_path_list(roots) -> list:
    """
    Plain path strings for a profile roots list whose
    entries may be legacy strings or {path, alias}
    dicts. Central tolerance point so every filesystem
    consumer keeps working on multi-root profiles.
    """

    paths = []

    for entry in roots or ():
        if isinstance(entry, dict):
            path = entry.get("path")
        else:
            path = entry

        if isinstance(path, str) and path.strip():
            paths.append(path.strip())

    return paths


def is_within_roots(path: str, roots: list) -> bool:
    """
    True when the resolved path lies inside at least one
    resolved root. Realpath-based, never string-prefix.
    """

    resolved_roots = []

    for root in root_path_list(roots):
        try:
            resolved = os.path.realpath(root)
        except (OSError, ValueError):
            continue
        if resolved not in resolved_roots:
            resolved_roots.append(resolved)

    if not resolved_roots:
        return False

    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError):
        return False

    for root in resolved_roots:
        try:
            if Path(resolved).is_relative_to(Path(root)):
                return True
        except ValueError:
            continue

    return False


def destination_occupied(
    path: str,
    *,
    windows: bool | None = None,
) -> bool:
    """
    Read-only collision probe: True when something already
    exists at the destination. Normcase-aware key is used
    by callers for case-insensitive platforms; the
    filesystem check itself is authoritative at execution.
    """

    _ = windows

    try:
        return os.path.lexists(path)
    except (OSError, ValueError):
        return True


def suffixed_candidate(
    path: str,
    taken: set,
    *,
    windows: bool | None = None,
) -> str:
    """
    Deterministic collision-resolution candidate:
    `Movie`, `Movie (1)`, `Movie (2)`, ... The first
    candidate whose normcase key is absent from `taken`
    and absent on the filesystem wins. Only used when the
    collision policy explicitly opts into suffixing;
    callers must enforce that precondition.
    """

    if windows is None:
        windows = target_is_windows()

    def key(value: str) -> str:
        return (
            value.casefold() if windows else value
        )

    taken_keys = {key(item) for item in taken}

    candidate = path

    if key(candidate) not in taken_keys and not (
        destination_occupied(candidate)
    ):
        return candidate

    stem, ext = os.path.splitext(path)

    counter = 1

    while True:
        candidate = f"{stem} ({counter}){ext}"

        if key(candidate) not in taken_keys and not (
            destination_occupied(candidate)
        ):
            return candidate

        counter += 1


def sanitize_component(
    text: str,
    *,
    windows: bool | None = None,
) -> str:
    """
    Best-effort sanitizer for template rendering previews:
    replaces illegal characters with a space and collapses
    whitespace. Validation (not sanitization) governs what
    may be saved or planned; this exists so previews can
    show the intended shape of user input.
    """

    if windows is None:
        windows = target_is_windows()

    value = re.sub(r"\s+", " ", str(text or "")).strip()

    if windows:
        value = "".join(
            " " if (char in WINDOWS_ILLEGAL_CHARS
                     or ord(char) < 32) else char
            for char in value
        )
        value = re.sub(r"\s+", " ", value).strip()

    return value.strip(" .") if windows else value
