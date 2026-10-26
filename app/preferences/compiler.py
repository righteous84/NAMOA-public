"""
Preference rule compiler (Phase 15, Phase A).

Deterministic compilation of explicit user examples into ordered
preference rules. No probability, no similarity scoring, no machine
learning, no semantic inference.

Compilation contract (compiler version 1.0.0 behaviour):

- every example compiles to its maximally specific rule first
  (all observed allowlisted dimensions as AND conditions)
- a broader rule (exactly one condition removed) is emitted only
  with at least GENERALISATION_THRESHOLD_N distinct consistent
  examples sharing all remaining conditions and zero contradicting
  examples in the proposed broader scope
- removal candidates are tried least-discriminating-first, where
  discrimination is the count of distinct values a dimension takes
  across the example population; ties break by DIMENSION_ORDER
- identical scopes with different answers are recorded as
  conflicts; each answer keeps its specific rule and no broader
  rule is emitted from a contradicted scope
- final list order is narrower-first, then deterministic; rule
  identity derives from scope plus answer, so recompilation is
  byte-identical
"""

from app.preferences.dimensions import (
    DIMENSION_ORDER,
    GENERALISATION_THRESHOLD_N,
    STRONG_DIMENSIONS,
)
from app.preferences.examples import PreferenceExample
from app.preferences.rules import (
    CompilationResult,
    PreferenceRule,
)


class PreferenceCompiler:
    """
    Deterministic example-to-rule compiler.
    """

    # Semantic version of the compilation behaviour (grouping,
    # broadening rule, removal order, ordering, identity scheme).
    # Any change MUST bump this version in the same change.
    semantic_version = "1.0.0"

    def __init__(self):
        pass

    def compile(self, examples) -> CompilationResult:
        entries = list(examples or [])

        if not entries:
            return CompilationResult(rules=(), conflicts=())

        scopes = {}

        for example in entries:
            scope = example.normalised_scope()
            key = (scope, example.answer)
            bucket = scopes.setdefault(key, set())
            bucket.add(example.example_id)

        population_values = {}

        for example in entries:
            for dimension, value in example.normalised_scope():
                population_values.setdefault(dimension, set()).add(
                    _stable_value_key(value)
                )

        rules = []
        conflicts = []
        emitted_scopes = {}

        for (scope, answer) in sorted(
            scopes,
            key=lambda item: (
                _scope_sort_key(item[0]),
                item[1],
            ),
        ):
            rules.append(
                PreferenceRule(
                    conditions=scope,
                    answer=answer,
                    source_example_ids=tuple(sorted(scopes[(scope, answer)])),
                    derivation_version=self.semantic_version,
                )
            )

        self._record_conflicts(entries, conflicts)

        specific_keys = {
            (_scope_sort_key(scope), answer)
            for (scope, answer) in scopes
        }

        for (scope, answer) in sorted(
            scopes,
            key=lambda item: (
                _scope_sort_key(item[0]),
                item[1],
            ),
        ):
            self._broaden(
                entries,
                scope,
                answer,
                population_values,
                emitted_scopes,
                specific_keys,
                rules,
            )

        ordered = sorted(
            rules,
            key=lambda rule: (
                -len(rule.conditions),
                _scope_sort_key(rule.conditions),
                rule.answer,
                rule.rule_id,
            ),
        )

        final = []

        for index, rule in enumerate(ordered):
            final.append(
                PreferenceRule(
                    conditions=rule.conditions,
                    answer=rule.answer,
                    source_example_ids=rule.source_example_ids,
                    derivation_version=rule.derivation_version,
                    order=index,
                    is_exception=rule.is_exception,
                    parent_rule_id=rule.parent_rule_id,
                    rule_id=rule.rule_id,
                )
            )

        return CompilationResult(
            rules=tuple(final),
            conflicts=tuple(conflicts),
        )

    def _record_conflicts(self, entries, conflicts):
        by_scope = {}

        for example in entries:
            scope = example.normalised_scope()
            slot = by_scope.setdefault(scope, {})
            slot.setdefault(example.answer, set()).add(
                example.example_id
            )

        for scope in sorted(by_scope, key=_scope_sort_key):
            answers = by_scope[scope]

            if len(answers) < 2:
                continue

            conflicts.append(
                {
                    "scope": [
                        {"dimension": dimension, "value": value}
                        for dimension, value in scope
                    ],
                    "answers": {
                        answer: sorted(ids)
                        for answer, ids in sorted(answers.items())
                    },
                }
            )

    def _broaden(
        self,
        entries,
        scope,
        answer,
        population_values,
        emitted_scopes,
        specific_keys,
        rules,
    ):
        for dimension in self._removal_order(scope, population_values):
            candidate = tuple(
                (dim, val)
                for dim, val in scope
                if dim != dimension
            )

            if not candidate:
                continue

            if not any(
                dim in STRONG_DIMENSIONS for dim, _ in candidate
            ):
                continue

            supporting = set()
            contradicted = False

            for example in entries:
                if not _scope_matches(
                    candidate, example.normalised_scope()
                ):
                    continue

                if example.answer == answer:
                    supporting.add(example.example_id)
                else:
                    contradicted = True
                    break

            if contradicted:
                continue

            if (_scope_sort_key(candidate), answer) in specific_keys:
                continue

            if self._merge_duplicate(
                candidate, answer, supporting, rules
            ):
                continue

            if self._covered(candidate, answer, emitted_scopes):
                continue

            if len(supporting) < GENERALISATION_THRESHOLD_N:
                continue

            rules.append(
                PreferenceRule(
                    conditions=candidate,
                    answer=answer,
                    source_example_ids=tuple(sorted(supporting)),
                    derivation_version=self.semantic_version,
                )
            )

            emitted_scopes.setdefault(answer, []).append(candidate)

    def _merge_duplicate(
        self, candidate, answer, supporting, rules
    ) -> bool:
        """
        Merge supporting evidence into an already-emitted rule with
        an identical scope and answer (reached from a different
        specific rule). Identity is unchanged; sources union
        deterministically. Returns True when merged.
        """

        wanted = set(candidate)

        for index, existing in enumerate(rules):
            if (
                existing.answer == answer
                and set(existing.conditions) == wanted
            ):
                merged = tuple(
                    sorted(
                        set(existing.source_example_ids)
                        | supporting
                    )
                )

                rules[index] = PreferenceRule(
                    conditions=existing.conditions,
                    answer=existing.answer,
                    source_example_ids=merged,
                    derivation_version=existing.derivation_version,
                    order=existing.order,
                    is_exception=existing.is_exception,
                    parent_rule_id=existing.parent_rule_id,
                    rule_id=existing.rule_id,
                )

                return True

        return False

    def _removal_order(self, scope, population_values):
        def rank(item):
            dimension, _ = item
            distinct = len(population_values.get(dimension, ()))
            try:
                tiebreak = DIMENSION_ORDER.index(dimension)
            except ValueError:
                tiebreak = len(DIMENSION_ORDER)
            return (distinct, tiebreak, dimension)

        return [
            dimension
            for dimension, _ in sorted(scope, key=rank)
        ]

    def _covered(self, candidate, answer, emitted_scopes):
        wanted = set(candidate)

        for existing in emitted_scopes.get(answer, []):
            if set(existing) <= wanted:
                return True

        return False


def _stable_value_key(value) -> str:
    if isinstance(value, bool):
        return f"bool:{value!r}"

    if isinstance(value, (int, float)):
        return f"num:{value!r}"

    return f"str:{value}"


def _scope_sort_key(scope) -> tuple:
    return tuple(
        (dimension, _stable_value_key(value))
        for dimension, value in scope
    )


def _scope_matches(candidate, example_scope) -> bool:
    known = dict(example_scope)

    for dimension, expected in candidate:
        if known.get(dimension) != expected:
            return False

    return True
