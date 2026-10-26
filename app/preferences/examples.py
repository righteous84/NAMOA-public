"""
Preference examples (Phase 15, Phase A).

An explicit user answer about one file or file class. Examples are
immutable records: the facts collection itself is an immutable sorted
tuple, so neither attribute reassignment (frozen dataclass) nor item
assignment (tuple) can mutate an example after construction.
Correcting an answer supersedes the example, it never mutates it.
"""

from dataclasses import dataclass
from typing import Any, Tuple

from app.preferences.dimensions import ANSWERS


@dataclass(frozen=True, slots=True)
class PreferenceExample:
    """
    One explicit user preference answer.

    example_id : stable caller-supplied identity (wizard session plus
        position, or an explicit key). Uniqueness across a compile
        input is the caller's responsibility; duplicates are treated
        as separate evidence only when their ids differ.
    facts      : observed technical/contextual facts, accepted as a
        mapping or iterable of pairs and stored as an immutable
        sorted tuple of (dimension, canonical value) pairs.
        Canonicalisation happens at construction, so every stored
        value is an immutable scalar (str, int, float, bool) and no
        mutable object can ever become part of the record. Keys
        outside the allowlist are rejected at compile time, never
        silently dropped.
    answer     : one of the canonical wizard answers.
    """

    example_id: str

    facts: Tuple[Tuple[str, Any], ...] = ()

    answer: str = "Balanced"

    def __post_init__(self):
        if not isinstance(self.example_id, str) or not self.example_id:
            raise ValueError(
                "example_id must be a non-empty string"
            )

        if self.answer not in ANSWERS:
            raise ValueError(
                f"unknown preference answer '{self.answer}' "
                f"(expected one of {sorted(ANSWERS)})"
            )

        from app.preferences.dimensions import (
            EXCLUDED_DIMENSIONS,
            normalise_dimension,
        )

        items = (
            list(self.facts.items())
            if isinstance(self.facts, dict)
            else list(self.facts)
        )

        canonical = []

        for pair in items:
            dimension, value = pair

            if dimension in EXCLUDED_DIMENSIONS:
                continue

            canonical.append((
                dimension,
                normalise_dimension(dimension, value),
            ))

        object.__setattr__(
            self,
            "facts",
            tuple(sorted(
                canonical,
                key=lambda item: (item[0], repr(item[1])),
            )),
        )

    def normalised_scope(self) -> Tuple[Tuple[str, Any], ...]:
        """
        The example's canonical match scope. Facts are canonicalised
        at construction, so this returns the stored scope sorted by
        dimension for determinism. Behaviour for valid Phase A
        dimensions is identical to normalising here: normalisation
        is idempotent over canonical values.
        """

        return tuple(sorted(self.facts))
