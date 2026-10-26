"""
Preference rules (Phase 15, Phase A).

Ordered deterministic rules compiled from explicit user examples.
Evaluation is top-to-bottom first match over AND conditions; the
terminal fallback (no rule matches) preserves existing
intent/policy/decision behaviour unchanged. Coverage evaluation,
suggestions, and lifecycle are Phase B/C scope, not here.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from app.preferences.dimensions import (
    ALLOWED_DIMENSIONS,
    CONTEXTUAL_DIMENSIONS,
    EXCLUDED_DIMENSIONS,
    STRONG_DIMENSIONS,
)


def rule_id_for(conditions, answer: str) -> str:
    """
    Stable deterministic rule identity derived from the canonical
    conditions plus answer. Identical scopes always produce identical
    ids across runs, orderings, and processes.
    """

    canonical = json.dumps(
        {
            "conditions": [
                [dimension, value]
                for dimension, value in conditions
            ],
            "answer": answer,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return f"pref-{digest[:12]}"


@dataclass(frozen=True, slots=True)
class PreferenceRule:
    """
    One compiled preference rule.

    conditions      : ordered AND conditions as
                      ((dimension, canonical value), ...).
    answer          : canonical wizard answer this scope carries.
    source_example_ids : sorted ids of the examples evidencing it.
    derivation_version : compiler version that produced it.
    order           : list position assigned at compile time
                      (narrower scopes first, deterministic after).
    is_exception    : pinned narrower override of a broader rule.
    parent_rule_id  : id of the overridden broader rule, if any.
    """

    conditions: Tuple[Tuple[str, Any], ...]

    answer: str

    source_example_ids: Tuple[str, ...] = ()

    derivation_version: str = "1.0.0"

    order: int = 0

    is_exception: bool = False

    parent_rule_id: Optional[str] = None

    rule_id: str = ""

    def __post_init__(self):
        from app.preferences.dimensions import (
            ANSWERS,
            normalise_dimension,
        )

        if self.answer not in ANSWERS:
            raise ValueError(
                f"unknown preference answer '{self.answer}'"
            )

        seen = set()

        for dimension, value in self.conditions:
            if dimension not in ALLOWED_DIMENSIONS:
                if dimension in EXCLUDED_DIMENSIONS:
                    raise ValueError(
                        f"dimension '{dimension}' is excluded "
                        "from preference matching"
                    )
                raise ValueError(
                    f"unknown preference dimension '{dimension}'"
                )

            if dimension in seen:
                raise ValueError(
                    f"duplicate condition dimension '{dimension}'"
                )

            seen.add(dimension)

            canonical = normalise_dimension(dimension, value)

            if canonical != value:
                raise ValueError(
                    f"condition ({dimension}, {value!r}) is not "
                    "canonical; compile through PreferenceCompiler"
                )

        if not any(
            dimension in STRONG_DIMENSIONS
            for dimension, _ in self.conditions
        ):
            raise ValueError(
                "preference rules require at least one strong "
                "dimension; contextual dimensions refine only"
            )

        derived = rule_id_for(self.conditions, self.answer)

        if self.rule_id and self.rule_id != derived:
            raise ValueError(
                f"rule_id '{self.rule_id}' does not match derived "
                f"identity '{derived}'"
            )

        if not self.rule_id:
            object.__setattr__(self, "rule_id", derived)

    def matches(self, facts: Dict[str, Any]) -> bool:
        """
        Shared first-match predicate (also used by the Phase B
        coverage evaluator): every condition holds against the
        normalised facts. Extra fact keys (titles, actors, genres)
        are ignored by construction, so semantic metadata can never
        influence matching.
        """

        from app.preferences.dimensions import normalise_dimension

        normalised = {}

        for dimension, value in facts.items():
            if dimension not in ALLOWED_DIMENSIONS:
                continue

            normalised[dimension] = normalise_dimension(
                dimension,
                value,
            )

        for dimension, expected in self.conditions:
            if normalised.get(dimension) != expected:
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.rule_id,
            "conditions": [
                {"dimension": dimension, "value": value}
                for dimension, value in self.conditions
            ],
            "answer": self.answer,
            "source_example_ids": list(self.source_example_ids),
            "derivation_version": self.derivation_version,
            "order": self.order,
            "is_exception": self.is_exception,
            "parent_rule_id": self.parent_rule_id,
        }


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """
    Compiler output: ordered deterministic rules plus recorded
    scope conflicts. Conflicts never block unrelated scopes; they
    are reported so a later phase (or the user) can narrow them.
    """

    rules: Tuple[PreferenceRule, ...] = ()

    conflicts: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rules": [rule.to_dict() for rule in self.rules],
            "conflicts": [dict(entry) for entry in self.conflicts],
        }
