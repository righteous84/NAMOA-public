"""
Preference coverage evaluator (Phase 15, Phase B, version 1.0.0).

Pure deterministic answers to one question: given these current
preference rules and these current media facts, what is the coverage
state and why?

Five states, no probabilities, no similarity scoring:

- covered-explicit : the file's full normalised scope was explicitly
  answered, and a rule carrying that answer matches
- covered         : a generated rule matches
- partial         : all but one condition of exactly one rule match
  (rules need at least two conditions to qualify; a total miss on a
  single-condition rule is uncovered, not partial), with the
  differing dimension identified
- ambiguous       : two or more matching rules carry different
  answers, or partial candidates disagree on answer
- uncovered       : no rule matches and no partial candidate exists

Deliberate design points, recorded as 1.0.0 behaviour:

- Full scan, no early exit on first match. Exiting early would
  silently resolve contradictions by list order, which the Phase B
  instruction forbids. Linear rules-times-files scaling with small
  constants is the specified performance shape.
- Compiler conflict records are not an input: any contradiction
  that matters surfaces as multi-answer full matches, so a
  separate conflicts channel would be redundant.
- covered-explicit needs the explicitly answered scopes alongside
  the rules, because a rule alone cannot tell a directly answered
  group from a generalised one.
- Invalid fact values raise ValueError (fail-closed), consistent
  with the Phase A vocabulary gate. The evaluator never invents,
  weakens, or reorders rules.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.preferences.rules import PreferenceRule


COVERAGE_STATES = (
    "covered-explicit",
    "covered",
    "partial",
    "ambiguous",
    "uncovered",
)


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """
    One deterministic coverage verdict.

    state               : one of COVERAGE_STATES.
    rule_ids            : referenced rule identities in input-list
                          order (matched rules, or partial
                          candidates for partial states).
    answer              : the matched answer, or None when no rule
                          determines one.
    differing_dimension : set only for partial states.
    reason              : deterministic human explanation naming the
                          rules and, for partial, the dimension.
    """

    state: str

    rule_ids: Tuple[str, ...] = ()

    answer: Optional[str] = None

    differing_dimension: Optional[str] = None

    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "rule_ids": list(self.rule_ids),
            "answer": self.answer,
            "differing_dimension": self.differing_dimension,
            "reason": self.reason,
        }


class CoverageEvaluator:
    """
    Stateless five-state coverage evaluator.
    """

    # Semantic version of the evaluation semantics (states,
    # precedence, partial qualification, reason wording). Any change
    # MUST bump this version in the same change.
    semantic_version = "1.0.0"

    def __init__(self):
        pass

    def evaluate(
        self,
        rules,
        facts: Dict[str, Any],
        explicit_scopes=(),
    ) -> CoverageResult:
        """
        Evaluate coverage for one file.

        rules            : ordered PreferenceRule list; input order
                           defines first-match precedence.
        facts            : media facts mapping (extra keys ignored,
                           invalid values raise, per Phase A).
        explicit_scopes  : normalised scopes ((dimension, value),
                           ...) directly evidenced by explicit
                           answers, used only to distinguish
                           covered-explicit from covered.
        """

        ordered = list(rules or [])

        answered = {
            tuple(sorted(scope, key=lambda pair: pair[0]))
            for scope in (explicit_scopes or ())
        }

        full_matches = [
            rule for rule in ordered if rule.matches(facts)
        ]

        if full_matches:
            return self._resolve_full_matches(
                full_matches, facts, answered
            )

        partials = self._partial_candidates(ordered, facts)

        if not partials:
            return CoverageResult(
                state="uncovered",
                reason="no preference rule matches",
            )

        answers = {rule.answer for rule, _ in partials}

        if len(answers) > 1:
            return CoverageResult(
                state="ambiguous",
                rule_ids=tuple(
                    rule.rule_id for rule, _ in partials
                ),
                reason=(
                    "partial candidates disagree: "
                    + ", ".join(
                        f"{rule.rule_id} ({rule.answer})"
                        for rule, _ in partials
                    )
                ),
            )

        primary, _ = partials[0]

        # Exactly one miss by construction (see
        # _partial_candidates); recomputed here for the reason.
        dimension = next(
            dim
            for dim, _ in primary.conditions
            if not self._condition_holds(primary, facts, dim)
        )

        return CoverageResult(
            state="partial",
            rule_ids=tuple(rule.rule_id for rule, _ in partials),
            answer=primary.answer,
            differing_dimension=dimension,
            reason=(
                f"all but '{dimension}' of rule "
                f"{primary.rule_id} ({primary.answer}) match"
                + (
                    f"; {len(partials) - 1} further partial "
                    "candidate(s)"
                    if len(partials) > 1
                    else ""
                )
            ),
        )

    def _resolve_full_matches(
        self, full_matches, facts, answered
    ) -> CoverageResult:
        answers = {rule.answer for rule in full_matches}

        if len(answers) > 1:
            return CoverageResult(
                state="ambiguous",
                rule_ids=tuple(rule.rule_id for rule in full_matches),
                reason=(
                    "contradictory rules match: "
                    + ", ".join(
                        f"{rule.rule_id} ({rule.answer})"
                        for rule in full_matches
                    )
                ),
            )

        primary = full_matches[0]
        scope = _normalised_fact_scope(facts)

        if scope in answered:
            return CoverageResult(
                state="covered-explicit",
                rule_ids=(primary.rule_id,),
                answer=primary.answer,
                reason=(
                    f"exact answered group matched by rule "
                    f"{primary.rule_id} ({primary.answer})"
                ),
            )

        return CoverageResult(
            state="covered",
            rule_ids=(primary.rule_id,),
            answer=primary.answer,
            reason=(
                f"matched rule {primary.rule_id} "
                f"({primary.answer})"
            ),
        )

    def _partial_candidates(self, ordered, facts):
        from app.preferences.dimensions import (
            ALLOWED_DIMENSIONS,
            normalise_dimension,
        )

        normalised = {}

        for dimension, value in facts.items():
            if dimension not in ALLOWED_DIMENSIONS:
                continue

            normalised[dimension] = normalise_dimension(
                dimension, value
            )

        candidates = []

        for rule in ordered:
            if len(rule.conditions) < 2:
                continue

            misses = [
                dimension
                for dimension, expected in rule.conditions
                if normalised.get(dimension) != expected
            ]

            if len(misses) == 1:
                candidates.append((rule, misses[0]))

        return candidates

    def _condition_holds(self, rule, facts, dimension) -> bool:
        from app.preferences.dimensions import (
            ALLOWED_DIMENSIONS,
            normalise_dimension,
        )

        expected = dict(rule.conditions).get(dimension)

        if dimension not in facts or dimension not in ALLOWED_DIMENSIONS:
            return False

        observed = normalise_dimension(dimension, facts[dimension])

        return observed == expected


def _normalised_fact_scope(facts) -> tuple:
    from app.preferences.dimensions import (
        ALLOWED_DIMENSIONS,
        normalise_dimension,
    )

    scope = []

    for dimension, value in facts.items():
        if dimension not in ALLOWED_DIMENSIONS:
            continue

        scope.append((
            dimension,
            normalise_dimension(dimension, value),
        ))

    return tuple(sorted(scope, key=lambda pair: pair[0]))
