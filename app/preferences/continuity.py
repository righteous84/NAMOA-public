"""
Future-scan continuity (Phase 15, Phase F, version 1.0.0).

Stateless evaluation of scanned files against accepted preference
state: established accepted preferences apply automatically through
the existing policy machinery, while new or unresolved cases become
deterministic review work. Continuity never invents preferences,
never auto-accepts, never modifies accepted records, and never
touches execution. Accepted decisions are inputs, never outputs.

Per-file outcomes:

- apply   : covered or covered-explicit with a constraining answer
            (Keep, Balanced); the effective policy is derived and
            carried for the normal intelligence pipeline.
- review  : partial, ambiguous, uncovered, or invalid facts; a
            suggestion is attached wherever the Phase C generator
            supports one, otherwise the reason alone routes review.
- none    : covered with a non-constraining answer (Optimise,
            Leave-alone); the existing pipeline proceeds unchanged.

Changed fingerprints are reported, never acted on beyond fresh
evaluation: identical inputs always reproduce identical outcomes.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.models.user_policy import UserPolicy
from app.preferences.coverage import CoverageEvaluator
from app.preferences.dimensions import (
    ALLOWED_DIMENSIONS,
    normalise_dimension,
)
from app.preferences.intent import UserIntent
from app.preferences.policy import (
    PreferenceConstraint,
    resolve_effective_policy,
)
from app.preferences.suggestions import (
    Suggestion,
    generate_for_file,
)


# Semantic version of the continuity evaluation: outcome kinds,
# tier mapping to actions, fingerprint scheme, and staleness
# reporting. Any change MUST bump this version in the same change.
CONTINUITY_VERSION = "1.0.0"

CONTINUITY_ACTIONS = frozenset({
    "apply",
    "review",
    "none",
})

#: Answers that narrow policy and therefore justify an apply
#: outcome when their rule covers a file. Optimise and
#: Leave-alone carry no policy effect by Phase C contract.
CONSTRAINING_ANSWERS = frozenset({
    "Keep",
    "Balanced",
})


@dataclass(frozen=True, slots=True)
class PreferenceScanState:
    """
    Accepted preference inputs for one scan/evaluation pass.

    Bundles everything continuity needs beyond the scanned files
    themselves: accepted ordered preference rules, the normalised
    scopes of accepted examples, the user intent, and prior file
    fingerprints. All fields optional; an empty state means no
    preference evidence, and evaluation then behaves exactly as
    without preferences. Read-only input: evaluation never
    mutates rules, examples, intent, or fingerprints.
    """

    rules: Tuple = ()

    explicit_scopes: Tuple = ()

    intent: Optional[UserIntent] = None

    prior_fingerprints: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        if self.intent is not None and not isinstance(
            self.intent, UserIntent
        ):
            raise ValueError("intent must be a UserIntent")

        for pair in self.prior_fingerprints:
            if (
                not isinstance(pair, (tuple, list))
                or len(pair) != 2
            ):
                raise ValueError(
                    "prior_fingerprints must hold "
                    "(media_id, fingerprint) pairs"
                )


def fingerprint_facts(facts: Mapping) -> str:
    """
    Stable identity for one file's scanned facts. Canonical JSON
    over the raw mapping; any fact change yields a different
    fingerprint, identical facts always yield the same one.
    """

    if not isinstance(facts, Mapping):
        raise ValueError("facts must be a mapping")

    canonical = json.dumps(
        dict(facts),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FileContinuity:
    """
    One file's continuity outcome.

    media_id           : stable technical identity supplied by the
                         caller.
    fingerprint        : fingerprint of the evaluated facts.
    coverage_state     : Phase B state (or uncovered for invalid
                         or empty facts).
    action             : apply, review, or none.
    answer             : matched answer driving the outcome, if any.
    rule_ids           : referenced rule identities in rule order.
    effective_policy   : derived UserPolicy for apply outcomes,
                         else None. Never widened by construction.
    policy_payload     : attributable snapshot of effective_policy,
                         else None.
    suggestion         : proposed Suggestion for review outcomes
                         where generation supports one, else None.
    reason             : deterministic human explanation.
    changed_since_prior: True when a prior fingerprint was supplied
                         and differs; re-evaluation, never action.
    """

    media_id: str

    fingerprint: str

    coverage_state: str

    action: str

    answer: Optional[str] = None

    rule_ids: Tuple[str, ...] = ()

    effective_policy: Optional[UserPolicy] = None

    policy_payload: Optional[Dict[str, Any]] = None

    suggestion: Optional[Suggestion] = None

    reason: str = ""

    changed_since_prior: bool = False

    def __post_init__(self):
        if self.action not in CONTINUITY_ACTIONS:
            raise ValueError(
                f"unknown continuity action '{self.action}'"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "media_id": self.media_id,
            "fingerprint": self.fingerprint,
            "coverage_state": self.coverage_state,
            "action": self.action,
            "answer": self.answer,
            "rule_ids": list(self.rule_ids),
            "policy_payload": (
                dict(self.policy_payload)
                if self.policy_payload is not None
                else None
            ),
            "suggestion": (
                self.suggestion.to_dict()
                if self.suggestion is not None
                else None
            ),
            "reason": self.reason,
            "changed_since_prior": self.changed_since_prior,
        }


@dataclass(frozen=True, slots=True)
class ContinuityResult:
    """
    One deterministic continuity pass over a population snapshot.
    """

    outcomes: Tuple[FileContinuity, ...] = ()

    stats: Tuple[Tuple[str, int], ...] = ()

    def stats_dict(self) -> Dict[str, int]:
        return dict(self.stats)


def _usable_scope(facts: Mapping):
    """
    Normalised allowlisted scope, or None when the facts cannot
    evidence any rule (invalid values or nothing usable).
    """

    try:
        scope = tuple(sorted(
            (
                dimension,
                normalise_dimension(dimension, value),
            )
            for dimension, value in facts.items()
            if dimension in ALLOWED_DIMENSIONS
        ))
    except ValueError:
        return None

    return scope or None


def evaluate_scan(
    *,
    files,
    rules,
    explicit_scopes=(),
    intent=None,
    base_policy=None,
    prior_fingerprints=None,
    computed_at: Optional[str] = None,
) -> ContinuityResult:
    """
    Evaluate one scanned population against accepted preference
    state. Pure function of its inputs: rules, explicit scopes,
    intent, base policy, file facts, and prior fingerprints.

    files              : iterable of {media_id, facts} mappings;
                         duplicate media ids collapse to the first
                         in media_id order.
    rules              : accepted ordered preference rules.
    explicit_scopes    : normalised scopes of accepted examples.
    intent             : UserIntent (default intent when omitted).
    base_policy        : operator policy (standard default when
                         omitted).
    prior_fingerprints : {media_id: fingerprint} from a previous
                         pass, used only to report change.
    computed_at        : timestamp for generated suggestions;
                         caller-supplied for determinism.

    Accepted records are only read (rule objects, versions,
    example scopes); nothing here writes, accepts, or mutates
    them. No suggestion is ever auto-accepted: review outcomes
    carry proposed suggestions only.
    """

    active_intent = intent if intent is not None else (
        UserIntent.default()
    )

    if not isinstance(active_intent, UserIntent):
        raise ValueError("intent must be a UserIntent")

    policy = base_policy if base_policy is not None else (
        UserPolicy.default()
    )

    if not isinstance(policy, UserPolicy):
        raise ValueError("base_policy must be a UserPolicy")

    ordered_rules = list(rules or [])
    answered = list(explicit_scopes or ())
    prior = dict(prior_fingerprints or {})
    evaluator = CoverageEvaluator()

    prepared = _prepare_files(files)
    outcomes: List[FileContinuity] = []
    counts = {
        "total": len(prepared),
        "apply": 0,
        "review": 0,
        "none": 0,
        "invalid": 0,
        "changed": 0,
    }

    for media_id, facts in prepared:
        outcome = _evaluate_file(
            evaluator,
            media_id,
            facts,
            ordered_rules,
            answered,
            active_intent,
            policy,
            prior.get(media_id),
            computed_at,
        )
        outcomes.append(outcome)
        counts[outcome.action] += 1

        if outcome.coverage_state == "uncovered" and (
            outcome.reason.startswith("unusable facts")
        ):
            counts["invalid"] += 1

        if outcome.changed_since_prior:
            counts["changed"] += 1

    return ContinuityResult(
        outcomes=tuple(outcomes),
        stats=tuple(sorted(counts.items())),
    )


def _prepare_files(files) -> List[Tuple[str, Dict[str, Any]]]:
    by_id: Dict[str, Dict[str, Any]] = {}

    for entry in files or []:
        if not isinstance(entry, Mapping):
            raise ValueError(
                "scan entries must be mappings with "
                "'media_id' and 'facts'"
            )

        media_id = entry.get("media_id")
        facts = entry.get("facts")

        if not isinstance(media_id, str) or not media_id:
            raise ValueError(
                "scan entries need a non-empty string media_id"
            )

        if not isinstance(facts, Mapping):
            raise ValueError(
                f"facts for '{media_id}' must be a mapping"
            )

        by_id.setdefault(media_id, dict(facts))

    return [(media_id, by_id[media_id]) for media_id in sorted(by_id)]


def _evaluate_file(
    evaluator,
    media_id: str,
    facts: Dict[str, Any],
    ordered_rules,
    answered,
    intent,
    policy,
    prior_fingerprint,
    computed_at,
) -> FileContinuity:
    fingerprint = fingerprint_facts(facts)
    changed = (
        prior_fingerprint is not None
        and prior_fingerprint != fingerprint
    )

    if _usable_scope(facts) is None:
        return FileContinuity(
            media_id=media_id,
            fingerprint=fingerprint,
            coverage_state="uncovered",
            action="review",
            reason=(
                "unusable facts: no valid allowlisted evidence; "
                "review required"
            ),
            changed_since_prior=changed,
        )

    result = evaluator.evaluate(ordered_rules, facts, answered)

    rule_ids = tuple(result.rule_ids)

    if result.state in ("covered", "covered-explicit"):
        if result.answer in CONSTRAINING_ANSWERS:
            matched = next(
                rule for rule in ordered_rules
                if rule.rule_id == rule_ids[0]
            )
            effective = resolve_effective_policy(
                policy,
                [
                    intent,
                    PreferenceConstraint(
                        rule_id=matched.rule_id,
                        answer=result.answer,
                    ),
                ],
                facts,
            )
            return FileContinuity(
                media_id=media_id,
                fingerprint=fingerprint,
                coverage_state=result.state,
                action="apply",
                answer=result.answer,
                rule_ids=rule_ids,
                effective_policy=effective,
                policy_payload=effective.to_policy_payload(),
                reason=(
                    f"established {result.answer} preference "
                    f"applies via rule {rule_ids[0]}; effective "
                    "policy derived without widening"
                ),
                changed_since_prior=changed,
            )

        return FileContinuity(
            media_id=media_id,
            fingerprint=fingerprint,
            coverage_state=result.state,
            action="none",
            answer=result.answer,
            rule_ids=rule_ids,
            reason=(
                f"preference established ({result.answer}); "
                "existing pipeline proceeds unchanged"
            ),
            changed_since_prior=changed,
        )

    suggestions = generate_for_file(
        media_id=media_id,
        analysis_fingerprint=fingerprint,
        rules=ordered_rules,
        facts=facts,
        explicit_scopes=answered,
        computed_at=computed_at,
    )

    return FileContinuity(
        media_id=media_id,
        fingerprint=fingerprint,
        coverage_state=result.state,
        action="review",
        answer=result.answer,
        rule_ids=rule_ids,
        suggestion=suggestions[0] if suggestions else None,
        reason=(
            f"{result.state}: {result.reason}"
            if result.reason
            else result.state
        ),
        changed_since_prior=changed,
    )
