"""
Compatibility effect adapter (Phase 15, Phase C, version 1.0.0).

Additive compatibility attribution for existing decision signals.
This module never scores, never fuses, and never changes storage
semantics: it attaches an effect plus evidence to a signal copy and
renders deterministic wording/caveats for recommendation text.

Unknown is the default and must never be read as compatible.
"""

from dataclasses import replace
from typing import Any, Dict, Mapping, Optional


# Semantic version of the effect vocabulary, adapter behaviour, and
# caveat wording. Any change MUST bump this version in the same
# change.
COMPATIBILITY_VERSION = "1.0.0"

COMPATIBILITY_EFFECTS = frozenset({
    "improves",
    "neutral",
    "worsens",
    "unknown",
})

COMPATIBILITY_TARGETS = frozenset({
    "Maximum",
    "Broad",
    "Efficient",
})


def attach_compatibility(
    signal,
    effect: str,
    evidence=None,
):
    """
    Return a copy of the signal carrying compatibility attribution.

    effect must be one of COMPATIBILITY_EFFECTS; anything else
    raises. evidence must be a mapping (recorded as a plain dict)
    or omitted. The input signal is never mutated.
    """

    if effect not in COMPATIBILITY_EFFECTS:
        raise ValueError(
            f"unknown compatibility effect '{effect}' "
            f"(expected one of {sorted(COMPATIBILITY_EFFECTS)})"
        )

    if evidence is None:
        recorded: Dict[str, Any] = {}
    elif isinstance(evidence, Mapping):
        recorded = dict(evidence)
    else:
        raise ValueError(
            "compatibility evidence must be a mapping"
        )

    return replace(
        signal,
        compatibility_effect=effect,
        compatibility_evidence=recorded,
    )


def infer_container_effect(
    container,
    remux_friendly,
) -> tuple:
    """
    Compatibility effect for a container-remux proposition from
    existing container knowledge.

    container is the measured container label; remux_friendly is the
    knowledge value supplied by the caller (later phases wire the
    knowledge service; Phase C passes explicit values so nothing is
    invented here). True means remuxing is known to help; False or
    None means no such claim can be established, which yields
    unknown rather than a silent positive.
    """

    name = str(container or "").strip().upper() or "unknown container"

    if remux_friendly is True:
        return (
            "improves",
            {
                "basis": "container_remux_knowledge",
                "knowledge_set": "container",
                "knowledge_version": "1.0.0",
                "container": name,
                "remux_friendly": True,
            },
        )

    return (
        "unknown",
        {
            "basis": "container_remux_knowledge",
            "knowledge_set": "container",
            "knowledge_version": "1.0.0",
            "container": name,
            "remux_friendly": bool(remux_friendly),
        },
    )


def caveat_for(
    effect: str,
    compatibility_target: str,
    proposition: Optional[str] = None,
) -> Optional[str]:
    """
    Deterministic user-facing wording for a compatibility effect
    under a compatibility target. Returns None when no caveat is
    warranted (improves, neutral). Wording only: this never vetoes,
    scores, or classifies; vetoes remain rule and fusion territory.
    """

    if effect not in COMPATIBILITY_EFFECTS:
        raise ValueError(
            f"unknown compatibility effect '{effect}'"
        )

    if compatibility_target not in COMPATIBILITY_TARGETS:
        raise ValueError(
            f"unknown compatibility target "
            f"'{compatibility_target}'"
        )

    what = (
        f"Transformation '{proposition}'"
        if proposition
        else "This transformation"
    )

    if effect == "unknown" and compatibility_target == "Maximum":
        return (
            f"{what} has unknown compatibility impact; Maximum "
            "compatibility requires preservation or review."
        )

    if effect == "unknown":
        return (
            f"{what} has unknown compatibility impact; "
            "proceeding assumes broad client support."
        )

    if effect == "worsens":
        return (
            f"{what} may reduce compatibility with some "
            "playback environments."
        )

    return None
