"""
Deterministic preference-example sampler (Phase 15, Phase D,
version 1.0.0).

Question-selection mechanism, not an intelligence engine. Given
library facts plus current preference rules, it answers one
question: which concrete example should be asked about next.

Selection is a pure function of (population, rules, explicit
scopes, asked ids, max count): no randomness, no timestamps, no
filesystem or environment reads, no similarity scoring. Coverage
state from the Phase B evaluator is the authoritative signal:
uncovered files first, then ambiguous, then partial; covered files
are never asked again. Within a tier, files round-robin across
distinct technical scopes with media_id ordering, so one batch
explores boundaries instead of repeating one class.

Session state (WizardSession) tracks explicit answers only. It
holds no inferred preferences and performs no compilation,
coverage, or policy work; those remain Phase A, B, and C
responsibilities.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.preferences.coverage import CoverageEvaluator
from app.preferences.dimensions import (
    ALLOWED_DIMENSIONS,
    ANSWERS,
    normalise_dimension,
)
from app.preferences.examples import PreferenceExample


# Semantic version of the sampling, ordering, session, and stopping
# behaviour. Any change MUST bump this version in the same change.
SAMPLER_VERSION = "1.0.0"

#: Default bound on candidates returned per selection call.
DEFAULT_MAX_CANDIDATES = 10

#: Coverage states that justify a question, in ask order.
_TIER_ORDER = {
    "uncovered": 0,
    "ambiguous": 1,
    "partial": 2,
}


@dataclass(frozen=True, slots=True)
class Candidate:
    """
    One question-worthy file with its deterministic rationale.

    media_id            : stable technical identity supplied by the
                          caller (never invented here).
    facts               : normalised allowlisted facts as an
                          immutable sorted tuple.
    coverage_state      : Phase B state driving the selection.
    tier                : ask priority (0 uncovered, 1 ambiguous,
                          2 partial).
    reason              : deterministic explanation naming the
                          coverage state and rule/dimension basis.
    rule_ids            : referenced rule identities in rule order.
    differing_dimension : set for partial candidates, else None.
    """

    media_id: str

    facts: Tuple[Tuple[str, Any], ...] = ()

    coverage_state: str = "uncovered"

    tier: int = 0

    reason: str = ""

    rule_ids: Tuple[str, ...] = ()

    differing_dimension: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "media_id": self.media_id,
            "facts": [
                {"dimension": dimension, "value": value}
                for dimension, value in self.facts
            ],
            "coverage_state": self.coverage_state,
            "tier": self.tier,
            "reason": self.reason,
            "rule_ids": list(self.rule_ids),
            "differing_dimension": self.differing_dimension,
        }


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """
    One deterministic selection pass.

    candidates : ordered Candidate records (at most max_count).
    stats      : population accounting with fixed keys, so callers
                 can distinguish empty libraries from fully covered
                 ones without inspecting candidates.
    stopped    : True when no further authorised question exists
                 (or the bound was reached).
    stop_reason: machine-readable cause (empty-population,
                 no-useful-candidates, max-count-reached,
                 candidates-available).
    """

    candidates: Tuple[Candidate, ...] = ()

    stats: Tuple[Tuple[str, int], ...] = ()

    stopped: bool = True

    stop_reason: str = "empty-population"

    def stats_dict(self) -> Dict[str, int]:
        return dict(self.stats)


def _normalise_facts(facts: Mapping) -> Tuple[Tuple[str, Any], ...]:
    """
    Canonical allowlisted facts for one file. Extra keys (titles,
    actors, genres and any other non-allowlisted metadata) are
    ignored by construction and can never influence selection.
    Invalid values raise ValueError; callers treat such files as
    unusable rather than guessing.
    """

    if not isinstance(facts, Mapping):
        raise ValueError("facts must be a mapping")

    scope = []

    for dimension, value in facts.items():
        if dimension not in ALLOWED_DIMENSIONS:
            continue

        scope.append((
            dimension,
            normalise_dimension(dimension, value),
        ))

    return tuple(sorted(scope, key=lambda pair: pair[0]))


def _prepare_population(population) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Validate and deterministically order the population. Entries
    need a non-empty string media_id and a facts mapping. Duplicate
    media ids collapse to one entry; ordering is by media_id, so
    input order and filesystem iteration order cannot leak in.
    """

    entries = list(population or [])
    by_id: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError(
                "population entries must be mappings with "
                "'media_id' and 'facts'"
            )

        media_id = entry.get("media_id")
        facts = entry.get("facts")

        if not isinstance(media_id, str) or not media_id:
            raise ValueError(
                "population entries need a non-empty string "
                "media_id"
            )

        if not isinstance(facts, Mapping):
            raise ValueError(
                f"facts for '{media_id}' must be a mapping"
            )

        by_id.setdefault(media_id, dict(facts))

    return [(media_id, by_id[media_id]) for media_id in sorted(by_id)]


def select_candidates(
    population,
    rules,
    explicit_scopes=(),
    asked_ids=(),
    max_count: int = DEFAULT_MAX_CANDIDATES,
) -> SelectionResult:
    """
    Deterministic candidate selection over one population snapshot.

    Every file not already asked is coverage-evaluated; files in
    uncovered, ambiguous, or partial states become candidates in
    tier order with round-robin across distinct technical scopes
    (media_id ordering inside each scope). Covered files, files
    with invalid or empty normalised facts, and already-asked files
    are counted in stats and never selected.
    """

    if not isinstance(max_count, int) or max_count <= 0:
        raise ValueError("max_count must be a positive integer")

    ordered_rules = list(rules or [])
    answered = list(explicit_scopes or ())
    asked = set(asked_ids or ())
    evaluator = CoverageEvaluator()

    prepared = _prepare_population(population)
    total = len(prepared)

    if total == 0:
        return SelectionResult(
            candidates=(),
            stats=_stats_tuple(0, 0, 0, 0, 0, 0),
            stopped=True,
            stop_reason="empty-population",
        )

    tiers: Dict[int, Dict[tuple, List[Candidate]]] = {}
    asked_skipped = 0
    covered_skipped = 0
    invalid_skipped = 0
    empty_skipped = 0

    for media_id, facts in prepared:
        if media_id in asked:
            asked_skipped += 1
            continue

        try:
            scope = _normalise_facts(facts)
        except ValueError:
            invalid_skipped += 1
            continue

        if not scope:
            empty_skipped += 1
            continue

        result = evaluator.evaluate(
            ordered_rules, dict(facts), answered
        )

        if result.state not in _TIER_ORDER:
            covered_skipped += 1
            continue

        tier = _TIER_ORDER[result.state]
        reason = (
            f"{result.state}: {result.reason}"
            if result.reason
            else result.state
        )

        candidate = Candidate(
            media_id=media_id,
            facts=scope,
            coverage_state=result.state,
            tier=tier,
            reason=reason,
            rule_ids=tuple(result.rule_ids),
            differing_dimension=result.differing_dimension,
        )

        tiers.setdefault(tier, {}).setdefault(scope, []).append(
            candidate
        )

    ordered_candidates: List[Candidate] = []

    for tier in sorted(tiers):
        groups = tiers[tier]
        ordered_groups = sorted(
            groups.values(), key=lambda items: items[0].media_id
        )
        index = 0
        pending = True

        while pending:
            pending = False

            for group in ordered_groups:
                if index < len(group):
                    ordered_candidates.append(group[index])
                    pending = True

            index += 1

    stats = _stats_tuple(
        total,
        asked_skipped,
        covered_skipped,
        invalid_skipped,
        empty_skipped,
        len(ordered_candidates),
    )

    if not ordered_candidates:
        return SelectionResult(
            candidates=(),
            stats=stats,
            stopped=True,
            stop_reason="no-useful-candidates",
        )

    if len(ordered_candidates) > max_count:
        return SelectionResult(
            candidates=tuple(ordered_candidates[:max_count]),
            stats=stats,
            stopped=True,
            stop_reason="max-count-reached",
        )

    return SelectionResult(
        candidates=tuple(ordered_candidates),
        stats=stats,
        stopped=False,
        stop_reason="candidates-available",
    )


def select_next(
    population,
    rules,
    explicit_scopes=(),
    asked_ids=(),
) -> Optional[Candidate]:
    """
    The single next question: first candidate of a max-one
    selection, or None when sampling must stop.
    """

    result = select_candidates(
        population,
        rules,
        explicit_scopes,
        asked_ids,
        max_count=1,
    )

    if not result.candidates:
        return None

    return result.candidates[0]


def example_from_answer(
    session_id: str,
    media_id: str,
    answer: str,
    facts: Mapping,
) -> PreferenceExample:
    """
    Convert one explicit user answer into a PreferenceExample with
    a deterministic example id. Only explicit answers create
    evidence; nothing here infers, backs off, or defaults.
    """

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a non-empty string")

    if not isinstance(media_id, str) or not media_id:
        raise ValueError("media_id must be a non-empty string")

    return PreferenceExample(
        example_id=f"{session_id}:{media_id}",
        facts=dict(facts or {}),
        answer=answer,
    )


def _stats_tuple(
    total: int,
    asked: int,
    covered: int,
    invalid: int,
    empty: int,
    selected: int,
) -> Tuple[Tuple[str, int], ...]:
    return (
        ("total", total),
        ("asked_skipped", asked),
        ("covered_skipped", covered),
        ("invalid_skipped", invalid),
        ("empty_skipped", empty),
        ("selected", selected),
    )


@dataclass(frozen=True, slots=True)
class WizardSession:
    """
    In-memory wizard session: explicit answers only.

    session_id            : stable caller-supplied identity.
    population_fingerprint: caller-supplied fingerprint of the
        population the answers were given against.
    answers               : ((media_id, answer), ...) in answer
        order; re-answering a file replaces its entry in place.
    finished              : finish-early or completed flag.
    sampler_version       : sampler behaviour version.

    The session holds no inferred preferences, performs no
    compilation or coverage, and persists nothing. Cancelling is
    dropping the record; resuming is rehydrating it via from_dict.
    """

    session_id: str

    population_fingerprint: str = ""

    answers: Tuple[Tuple[str, str], ...] = ()

    finished: bool = False

    sampler_version: str = "1.0.0"

    def __post_init__(self):
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError(
                "session_id must be a non-empty string"
            )

        for media_id, answer in self.answers:
            if not isinstance(media_id, str) or not media_id:
                raise ValueError(
                    "answer entries need a non-empty media_id"
                )

            if answer not in ANSWERS:
                raise ValueError(
                    f"unknown preference answer '{answer}'"
                )

    def record_answer(
        self, media_id: str, answer: str
    ) -> "WizardSession":
        """
        Append a new answer, or replace the existing entry for the
        same file in place (positions mirror question order, so
        going back revisits the same slot). Earlier answers are
        never implicitly dropped: only the re-answered file changes.
        """

        if answer not in ANSWERS:
            raise ValueError(
                f"unknown preference answer '{answer}'"
            )

        if not isinstance(media_id, str) or not media_id:
            raise ValueError(
                "media_id must be a non-empty string"
            )

        updated = [
            (media_id, answer)
            if known_id == media_id
            else (known_id, known_answer)
            for known_id, known_answer in self.answers
        ]

        if all(known_id != media_id for known_id, _ in self.answers):
            updated.append((media_id, answer))

        return WizardSession(
            session_id=self.session_id,
            population_fingerprint=self.population_fingerprint,
            answers=tuple(updated),
            finished=self.finished,
            sampler_version=self.sampler_version,
        )

    def undo_last_answer(self) -> "WizardSession":
        """
        Go back one step: drop the most recent answer so the file
        can be asked again. Earlier answers are untouched.
        """

        return WizardSession(
            session_id=self.session_id,
            population_fingerprint=self.population_fingerprint,
            answers=tuple(self.answers[:-1]),
            finished=self.finished,
            sampler_version=self.sampler_version,
        )

    def finish(self) -> "WizardSession":
        """Mark finished early (or complete); answers stand as is."""

        return WizardSession(
            session_id=self.session_id,
            population_fingerprint=self.population_fingerprint,
            answers=tuple(self.answers),
            finished=True,
            sampler_version=self.sampler_version,
        )

    def progress(self) -> Dict[str, Any]:
        return {
            "answered": len(self.answers),
            "finished": self.finished,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "population_fingerprint": self.population_fingerprint,
            "answers": [
                {"media_id": media_id, "answer": answer}
                for media_id, answer in self.answers
            ],
            "finished": self.finished,
            "sampler_version": self.sampler_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "WizardSession":
        if not isinstance(data, Mapping):
            raise ValueError("session data must be a mapping")

        return cls(
            session_id=data.get("session_id", ""),
            population_fingerprint=data.get(
                "population_fingerprint", ""
            ),
            answers=tuple(
                (entry.get("media_id", ""), entry.get("answer", ""))
                for entry in (data.get("answers") or [])
            ),
            finished=bool(data.get("finished", False)),
            sampler_version=str(
                data.get("sampler_version", "1.0.0")
            ),
        )
