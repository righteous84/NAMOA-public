"""
Preference review lifecycle (Phase 15, Phase E, version 1.0.0).

Durable explicit review over Phase C suggestion records: propose,
accept, reject, change, reopen, bulk accept, and stale
supersession, all against the append-only review event ledger.
Ambiguous suggestions stay ambiguous until a user resolves them;
nothing here guesses, averages, or auto-approves.

Transition matrix (anything else raises):

    proposed  -> accepted   (staleness proof required)
    proposed  -> rejected
    proposed  -> superseded (via change or stale pass)
    rejected  -> proposed   (via reopen only: a new explicit
                             review action)
    accepted  -> accepted   (idempotent no-op, no new event)
    accepted/rejected/superseded -> anything else: refused

Accepted history is immutable: accepted and rejected records are
never rewritten; corrections supersede with forward links.
Transaction ownership remains with the caller: bulk operations
validate every item before writing any item.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from app.preferences.dimensions import ANSWERS
from app.preferences.examples import PreferenceExample
from app.preferences.suggestions import (
    SUGGESTION_VERSION,
    Suggestion,
    suggestion_id_for,
)


# Semantic version of the review lifecycle: transition matrix,
# staleness rules, bulk atomicity, and example derivation. Any
# change MUST bump this version in the same change.
REVIEW_VERSION = "1.0.0"

_ALLOWED_TRANSITIONS = {
    "proposed": frozenset({"accepted", "rejected", "superseded"}),
    "rejected": frozenset({"proposed"}),
    "accepted": frozenset({"accepted"}),
    "superseded": frozenset(),
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_transition(old_status: str, new_status: str) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(old_status, frozenset())

    if new_status == old_status and old_status == "accepted":
        return

    if new_status not in allowed:
        raise ValueError(
            f"transition '{old_status}' -> '{new_status}' is "
            "not permitted"
        )


def propose_review(repository, suggestions, actor="system"):
    """
    Persist proposed suggestions idempotently: identical active
    records are returned as-is; only genuinely new rows get a
    'proposed' event. Returns the stored records in input order.
    """

    stored = []

    for suggestion in suggestions or []:
        existing = repository.get_suggestion(
            suggestion.suggestion_id
        )

        if existing is not None and existing.status in (
            "proposed",
            "accepted",
        ):
            stored.append(existing)
            continue

        if existing is not None:
            raise ValueError(
                f"suggestion '{suggestion.suggestion_id}' "
                f"already decided as {existing.status}; reopen "
                "it explicitly instead of re-proposing"
            )

        repository.save_suggestion(suggestion)
        repository.append_event(
            suggestion.suggestion_id,
            "proposed",
            previous_status=None,
            new_status="proposed",
            actor=actor,
        )
        stored.append(suggestion)

    return stored


def accept_review(
    repository,
    suggestion_id: str,
    actor: str,
    expected_rule_version: str,
    expected_fingerprint: str,
    facts=None,
):
    """
    Accept one proposed suggestion after proving it is current:
    the caller supplies the presently observed rule version and
    analysis fingerprint, which must equal the stored row, or
    acceptance fails with nothing written. Ambiguous suggestions
    (no proposed answer) cannot be accepted; resolve them with
    change() first. With facts supplied, an explicit
    PreferenceExample evidence row is stored atomically alongside.
    Re-accepting an accepted suggestion is an idempotent no-op.
    """

    record = _get_existing(repository, suggestion_id)

    if record.status == "accepted":
        return record, None

    _check_transition(record.status, "accepted")

    if record.proposed_answer is None:
        raise ValueError(
            f"suggestion '{suggestion_id}' is ambiguous and "
            "requires explicit resolution before acceptance"
        )

    if (
        record.rule_version != expected_rule_version
        or record.analysis_fingerprint != expected_fingerprint
    ):
        raise ValueError(
            f"suggestion '{suggestion_id}' is stale: stored "
            f"({record.rule_version}, "
            f"{record.analysis_fingerprint}) does not match "
            "current inputs"
        )

    _check_transition("proposed", "accepted")
    repository.set_status(suggestion_id, "accepted")
    repository.append_event(
        suggestion_id,
        "accepted",
        previous_status="proposed",
        new_status="accepted",
        actor=actor,
    )

    example_id = None

    if facts is not None:
        if not isinstance(facts, Mapping) or not facts:
            raise ValueError(
                "acceptance facts must be a non-empty mapping"
            )

        example_id = f"accepted:{suggestion_id}"
        validated = PreferenceExample(
            example_id=example_id,
            facts=dict(facts),
            answer=record.proposed_answer,
        )
        repository.save_example(
            example_id,
            json.dumps(
                dict(validated.facts),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
            validated.answer,
            source_suggestion_id=suggestion_id,
            actor=actor,
        )

    return repository.get_suggestion(suggestion_id), example_id


def reject_review(repository, suggestion_id: str, actor: str,
                  reason=None):
    """
    Reject one proposed suggestion. Rejection records a decision;
    it never creates, alters, or implies a different preference.
    """

    record = _require_status(repository, suggestion_id, "proposed")

    _check_transition("proposed", "rejected")
    repository.set_status(suggestion_id, "rejected")
    repository.append_event(
        suggestion_id,
        "rejected",
        previous_status="proposed",
        new_status="rejected",
        actor=actor,
        detail=reason,
    )

    return repository.get_suggestion(suggestion_id)


def change_review(
    repository,
    suggestion_id: str,
    actor: str,
    new_answer: str,
    computed_at: Optional[str] = None,
):
    """
    Replace one proposed suggestion with an explicit different
    answer from the closed vocabulary. The original record is
    superseded with a forward link (never rewritten); the fresh
    proposed record carries the new answer. Unknown answers raise
    before anything is written.
    """

    if new_answer not in ANSWERS:
        raise ValueError(
            f"unknown preference answer '{new_answer}'"
        )

    current = _require_status(repository, suggestion_id, "proposed")

    replacement_id = suggestion_id_for(
        current.matched_rule_id,
        current.media_id,
        current.analysis_fingerprint,
        current.rule_version,
        new_answer,
    )

    if repository.get_suggestion(replacement_id) is not None:
        raise ValueError(
            f"replacement suggestion '{replacement_id}' already "
            "exists; resolve it instead of duplicating"
        )

    replacement = Suggestion(
        suggestion_id=replacement_id,
        media_id=current.media_id,
        analysis_fingerprint=current.analysis_fingerprint,
        matched_rule_id=current.matched_rule_id,
        rule_version=current.rule_version,
        source_example_ids=current.source_example_ids,
        proposed_answer=new_answer,
        coverage_state=current.coverage_state,
        reason=current.reason,
        computed_at=(
            computed_at if computed_at is not None else _utcnow()
        ),
    )

    _check_transition("proposed", "superseded")
    repository.save_suggestion(replacement)
    repository.append_event(
        replacement_id,
        "proposed",
        previous_status=None,
        new_status="proposed",
        actor=actor,
        detail=f"changed from suggestion '{suggestion_id}'",
    )
    repository.set_status(
        suggestion_id, "superseded",
        superseded_by=replacement_id,
    )
    repository.append_event(
        suggestion_id,
        "changed",
        previous_status="proposed",
        new_status="superseded",
        actor=actor,
        detail=f"superseded by '{replacement_id}'",
    )

    return replacement


def reopen_review(repository, suggestion_id: str, actor: str):
    """
    Return one rejected suggestion to proposed as a new explicit
    review action. Accepted and superseded records are history and
    can never be reopened.
    """

    record = _require_status(repository, suggestion_id, "rejected")

    _check_transition("rejected", "proposed")
    repository.set_status(suggestion_id, "proposed")
    repository.append_event(
        suggestion_id,
        "reopened",
        previous_status="rejected",
        new_status="proposed",
        actor=actor,
    )

    return repository.get_suggestion(suggestion_id)


def bulk_accept_review(
    repository,
    suggestion_ids,
    actor: str,
    expected: Mapping,
):
    """
    Atomic bulk acceptance: every id must reference a proposed
    suggestion whose stored rule version and fingerprint match the
    caller-supplied expectations, or nothing is accepted. Expected
    maps suggestion_id to (rule_version, fingerprint). Per-item
    attribution is preserved in the event log.
    """

    ids = list(suggestion_ids or [])
    expected = dict(expected or {})
    validated = []

    for suggestion_id in ids:
        record = repository.get_suggestion(suggestion_id)

        if record is None:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.status != "proposed":
            raise ValueError(
                f"suggestion '{suggestion_id}' is "
                f"{record.status}, not proposed"
            )

        if record.proposed_answer is None:
            raise ValueError(
                f"suggestion '{suggestion_id}' is ambiguous and "
                "requires explicit resolution before acceptance"
            )

        want = expected.get(suggestion_id)

        if want is None:
            raise ValueError(
                f"suggestion '{suggestion_id}' has no staleness "
                "expectation; refusing bulk acceptance"
            )

        rule_version, fingerprint = want

        if (
            record.rule_version != rule_version
            or record.analysis_fingerprint != fingerprint
        ):
            raise ValueError(
                f"suggestion '{suggestion_id}' is stale"
            )

        validated.append(record)

    accepted = []

    for record in validated:
        _check_transition("proposed", "accepted")
        repository.set_status(record.suggestion_id, "accepted")
        repository.append_event(
            record.suggestion_id,
            "accepted",
            previous_status="proposed",
            new_status="accepted",
            actor=actor,
        )
        accepted.append(
            repository.get_suggestion(record.suggestion_id)
        )

    return accepted


def supersede_stale_review(
    repository,
    current_rule_versions: Mapping,
    current_fingerprint: str,
    actor="system",
):
    """
    Invalidate proposed suggestions whose rule version or facts
    fingerprint no longer matches current inputs. Accepted and
    rejected records are history and are never rewritten.
    """

    stale = []

    for record in repository.list_suggestions(status="proposed"):
        current_version = (current_rule_versions or {}).get(
            record.matched_rule_id
        )

        if (
            current_version == record.rule_version
            and record.analysis_fingerprint == current_fingerprint
        ):
            continue

        _check_transition("proposed", "superseded")
        repository.set_status(record.suggestion_id, "superseded")
        repository.append_event(
            record.suggestion_id,
            "superseded",
            previous_status="proposed",
            new_status="superseded",
            actor=actor,
        )
        stale.append(repository.get_suggestion(record.suggestion_id))

    return stale


def conflicting_evidence(
    repository, media_id: str, rules=()
) -> Dict[str, Any]:
    """
    Conflicting evidence for one file's review: every proposed
    answer-less suggestion for the media with its rule ids, the
    source examples behind those rules (resolved from the supplied
    rules; empty when the rules are not supplied), and reasons.
    Empty when nothing ambiguous awaits.
    """

    rows = repository.list_suggestions(
        status="proposed", media_id=media_id
    )

    pending = [row for row in rows if row.proposed_answer is None]

    by_rule = {rule.rule_id: rule for rule in (rules or [])}

    rule_ids = []
    example_ids = []

    for row in pending:
        if row.matched_rule_id not in rule_ids:
            rule_ids.append(row.matched_rule_id)

        rule = by_rule.get(row.matched_rule_id)

        basis = (
            tuple(row.source_example_ids)
            if row.source_example_ids
            else tuple(rule.source_example_ids)
            if rule is not None
            else ()
        )

        for example_id in basis:
            if example_id not in example_ids:
                example_ids.append(example_id)

    return {
        "media_id": media_id,
        "ambiguous": len(pending) > 0,
        "rule_ids": rule_ids,
        "source_example_ids": example_ids,
        "reasons": [row.reason for row in pending],
    }


def _get_existing(repository, suggestion_id):
    record = repository.get_suggestion(suggestion_id)

    if record is None:
        raise ValueError(
            f"unknown suggestion '{suggestion_id}'"
        )

    return record


def _require_status(repository, suggestion_id, status):
    record = _get_existing(repository, suggestion_id)

    if record.status != status:
        raise ValueError(
            f"suggestion '{suggestion_id}' is "
            f"{record.status}, not {status}"
        )

    return record


def load_accepted_scan_state(repository):
    """
    Read-only construction of accepted preference inputs for one
    scan/evaluation pass. Reads accepted PreferenceExample rows,
    rebuilds validated examples, compiles the ordered rules, and
    returns a PreferenceScanState. Returns None when no accepted
    examples exist (including when the preference tables are
    absent, e.g. databases migrated before Phase 15E): callers
    treat None as "no preference evidence" and behave exactly as
    without preferences. Corrupt stored rows raise loudly rather
    than silently dropping accepted user decisions. Performs no
    writes and no transitions.
    """

    from app.preferences.compiler import PreferenceCompiler
    from app.preferences.continuity import PreferenceScanState

    try:
        rows = repository.list_examples()
    except Exception as error:
        message = str(error).lower()

        if "no such table" in message:
            return None

        raise

    if not rows:
        return None

    examples = []

    for row in rows:
        facts = row.get("facts_json") or "{}"

        examples.append(
            PreferenceExample(
                example_id=row["example_id"],
                facts=json.loads(facts),
                answer=row["answer"],
            )
        )

    compiled = PreferenceCompiler().compile(examples)

    return PreferenceScanState(
        rules=tuple(compiled.rules),
        explicit_scopes=tuple(
            example.normalised_scope() for example in examples
        ),
        intent=None,
        prior_fingerprints=(),
    )
