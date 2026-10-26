"""
Preference suggestions (Phase 15, Phase C, version 1.0.0).

A suggestion is proposed preference knowledge awaiting user
acceptance. It references assessment and rule data; it never copies
OpportunityAssessment payloads. Suggestions carry zero authority:
nothing here approves, executes, or mutates production state. All
state lives in memory; durable persistence belongs to a later
explicitly approved phase.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple


# Semantic version of the suggestion record, identity scheme, and
# lifecycle transitions. Any change MUST bump this version in the
# same change.
SUGGESTION_VERSION = "1.0.0"

SUGGESTION_STATUSES = frozenset({
    "proposed",
    "accepted",
    "rejected",
    "superseded",
})


def suggestion_id_for(
    matched_rule_id: str,
    media_id: str,
    analysis_fingerprint: str,
    derivation_version: str,
    proposed_answer,
) -> str:
    """
    Stable deterministic suggestion identity. Identical rule, media,
    facts fingerprint, derivation, and proposed answer always
    produce the identical id, so regeneration cannot duplicate.
    Timestamps are excluded from identity by construction.
    """

    canonical = json.dumps(
        {
            "rule": matched_rule_id,
            "media": media_id,
            "fingerprint": analysis_fingerprint,
            "derivation": derivation_version,
            "answer": proposed_answer,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return f"sugg-{digest[:12]}"


@dataclass(frozen=True, slots=True)
class Suggestion:
    """
    One preference suggestion for one file.

    References, never copies, assessment and rule data: matched rule
    id plus versions, source example ids, and the analysis
    fingerprint needed to detect staleness. proposed_answer may be
    None when coverage is ambiguous and no single answer is
    supportable (review routing, never a guess).
    """

    suggestion_id: str

    media_id: str

    analysis_fingerprint: str

    matched_rule_id: str

    rule_version: str

    derivation_version: str = SUGGESTION_VERSION

    source_example_ids: Tuple[str, ...] = ()

    proposed_answer: Optional[str] = None

    coverage_state: str = "uncovered"

    reason: str = ""

    status: str = "proposed"

    computed_at: str = ""

    superseded_by: Optional[str] = None

    def __post_init__(self):
        for field_name in (
            "suggestion_id",
            "media_id",
            "analysis_fingerprint",
            "matched_rule_id",
            "rule_version",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{field_name} must be a non-empty string"
                )

        if self.status not in SUGGESTION_STATUSES:
            raise ValueError(
                f"unknown suggestion status '{self.status}'"
            )

        derived = suggestion_id_for(
            self.matched_rule_id,
            self.media_id,
            self.analysis_fingerprint,
            self.derivation_version,
            self.proposed_answer,
        )

        if self.suggestion_id != derived:
            raise ValueError(
                f"suggestion_id '{self.suggestion_id}' does not "
                f"match derived identity '{derived}'"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "media_id": self.media_id,
            "analysis_fingerprint": self.analysis_fingerprint,
            "matched_rule_id": self.matched_rule_id,
            "rule_version": self.rule_version,
            "derivation_version": self.derivation_version,
            "source_example_ids": list(self.source_example_ids),
            "proposed_answer": self.proposed_answer,
            "coverage_state": self.coverage_state,
            "reason": self.reason,
            "status": self.status,
            "computed_at": self.computed_at,
            "superseded_by": self.superseded_by,
        }


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_for_file(
    *,
    media_id: str,
    analysis_fingerprint: str,
    rules,
    facts: Mapping,
    explicit_scopes=(),
    computed_at: Optional[str] = None,
) -> List[Suggestion]:
    """
    Deterministic suggestion generation for one file.

    Evaluates coverage over the supplied rules and facts, then
    proposes only where a matched rule supports an answer: partial
    states propose their rule's answer, ambiguous states propose
    review (answer None). Covered states need nothing (preference
    already established); uncovered states have no rule basis to
    propose from (review routing, not a suggestion). No suggestion
    is generated for Leave-alone matches: the file is excluded from
    future suggestions while analysis stays unaffected.
    """

    from app.preferences.coverage import CoverageEvaluator

    if not isinstance(media_id, str) or not media_id:
        raise ValueError("media_id must be a non-empty string")

    if not isinstance(analysis_fingerprint, str) or (
        not analysis_fingerprint
    ):
        raise ValueError(
            "analysis_fingerprint must be a non-empty string"
        )

    result = CoverageEvaluator().evaluate(
        list(rules or []), dict(facts or {}), explicit_scopes
    )

    if result.state not in ("partial", "ambiguous"):
        return []

    if result.state == "partial" and result.answer == "Leave-alone":
        return []

    rule_versions = {}
    source_ids: Tuple[str, ...] = ()

    for rule in list(rules or []):
        if rule.rule_id in result.rule_ids:
            rule_versions[rule.rule_id] = rule.derivation_version

            if result.state == "partial":
                source_ids = tuple(rule.source_example_ids)

    if result.state == "partial":
        matched = result.rule_ids[0]
        suggestions = [
            Suggestion(
                suggestion_id=suggestion_id_for(
                    matched,
                    media_id,
                    analysis_fingerprint,
                    rule_versions[matched],
                    result.answer,
                ),
                media_id=media_id,
                analysis_fingerprint=analysis_fingerprint,
                matched_rule_id=matched,
                rule_version=rule_versions[matched],
                source_example_ids=source_ids,
                proposed_answer=result.answer,
                coverage_state=result.state,
                reason=result.reason,
                computed_at=(
                    computed_at
                    if computed_at is not None
                    else _utcnow()
                ),
            )
        ]
    else:
        suggestions = [
            Suggestion(
                suggestion_id=suggestion_id_for(
                    rule_id,
                    media_id,
                    analysis_fingerprint,
                    rule_versions[rule_id],
                    None,
                ),
                media_id=media_id,
                analysis_fingerprint=analysis_fingerprint,
                matched_rule_id=rule_id,
                rule_version=rule_versions[rule_id],
                source_example_ids=(),
                proposed_answer=None,
                coverage_state=result.state,
                reason=result.reason,
                computed_at=(
                    computed_at
                    if computed_at is not None
                    else _utcnow()
                ),
            )
            for rule_id in result.rule_ids
        ]

    return suggestions


class SuggestionStore:
    """
    In-memory suggestion lifecycle. All transitions are explicit,
    attributed, and reversible via supersession records; nothing
    persists beyond the process. Bulk acceptance validates every
    item first so a single failure accepts nothing.
    """

    def __init__(self):
        self._records: Dict[str, Suggestion] = {}
        self._transitions: List[Dict[str, Any]] = []

    def propose(self, suggestions) -> List[Suggestion]:
        stored = []

        for suggestion in suggestions or []:
            existing = self._records.get(suggestion.suggestion_id)

            if existing is not None and existing.status in (
                "proposed",
                "accepted",
            ):
                stored.append(existing)
                continue

            self._records[suggestion.suggestion_id] = suggestion
            stored.append(suggestion)

        return stored

    def get(self, suggestion_id: str) -> Optional[Suggestion]:
        return self._records.get(suggestion_id)

    def accept(self, suggestion_id: str) -> Suggestion:
        return self._transition(
            suggestion_id, "accepted", require_status=("proposed",)
        )

    def reject(self, suggestion_id: str) -> Suggestion:
        return self._transition(
            suggestion_id, "rejected", require_status=("proposed",)
        )

    def change(self, suggestion_id: str, new_answer: str):
        """
        Replace one suggestion with an explicit answer: the old
        record is superseded (linked forward) and a fresh proposed
        record carries the new answer with identical identity
        inputs except the answer itself.
        """

        current = self._require_proposed(suggestion_id)

        replacement = Suggestion(
            suggestion_id=suggestion_id_for(
                current.matched_rule_id,
                current.media_id,
                current.analysis_fingerprint,
                current.rule_version,
                new_answer,
            ),
            media_id=current.media_id,
            analysis_fingerprint=current.analysis_fingerprint,
            matched_rule_id=current.matched_rule_id,
            rule_version=current.rule_version,
            source_example_ids=current.source_example_ids,
            proposed_answer=new_answer,
            coverage_state=current.coverage_state,
            reason=current.reason,
            computed_at=_utcnow(),
        )

        superseded = Suggestion(
            suggestion_id=current.suggestion_id,
            media_id=current.media_id,
            analysis_fingerprint=current.analysis_fingerprint,
            matched_rule_id=current.matched_rule_id,
            rule_version=current.rule_version,
            source_example_ids=current.source_example_ids,
            proposed_answer=current.proposed_answer,
            coverage_state=current.coverage_state,
            reason=current.reason,
            status="superseded",
            computed_at=current.computed_at,
            superseded_by=replacement.suggestion_id,
        )

        self._records[current.suggestion_id] = superseded
        self._records[replacement.suggestion_id] = replacement
        self._transitions.append({
            "suggestion_id": current.suggestion_id,
            "from": "proposed",
            "to": "superseded",
            "superseded_by": replacement.suggestion_id,
        })

        return replacement

    def bulk_accept(self, suggestion_ids) -> List[Suggestion]:
        """
        Atomic bulk acceptance: every id must reference a proposed
        suggestion or nothing is accepted. Per-item attribution is
        preserved in the transition log.
        """

        ids = list(suggestion_ids or [])

        for suggestion_id in ids:
            self._require_proposed(suggestion_id)

        return [self.accept(suggestion_id) for suggestion_id in ids]

    def supersede_stale(
        self,
        current_rule_versions: Mapping,
        current_fingerprint: str,
    ) -> List[Suggestion]:
        """
        Invalidate proposed suggestions whose rule version or facts
        fingerprint no longer matches current inputs. Accepted and
        rejected records are history and are never rewritten.
        """

        stale = []

        for suggestion_id, record in list(self._records.items()):
            if record.status != "proposed":
                continue

            current_version = (current_rule_versions or {}).get(
                record.matched_rule_id
            )

            if (
                current_version != record.rule_version
                or record.analysis_fingerprint != current_fingerprint
            ):
                updated = Suggestion(
                    suggestion_id=record.suggestion_id,
                    media_id=record.media_id,
                    analysis_fingerprint=record.analysis_fingerprint,
                    matched_rule_id=record.matched_rule_id,
                    rule_version=record.rule_version,
                    source_example_ids=record.source_example_ids,
                    proposed_answer=record.proposed_answer,
                    coverage_state=record.coverage_state,
                    reason=record.reason,
                    status="superseded",
                    computed_at=record.computed_at,
                )
                self._records[suggestion_id] = updated
                self._transitions.append({
                    "suggestion_id": suggestion_id,
                    "from": "proposed",
                    "to": "superseded",
                    "superseded_by": None,
                })
                stale.append(updated)

        return stale

    def transitions(self) -> List[Dict[str, Any]]:
        return [dict(entry) for entry in self._transitions]

    def _require_proposed(self, suggestion_id: str) -> Suggestion:
        record = self._records.get(suggestion_id)

        if record is None:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.status != "proposed":
            raise ValueError(
                f"suggestion '{suggestion_id}' is "
                f"{record.status}, not proposed"
            )

        return record

    def _transition(
        self, suggestion_id: str, new_status: str, require_status
    ) -> Suggestion:
        record = self._records.get(suggestion_id)

        if record is None:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.status not in require_status:
            raise ValueError(
                f"suggestion '{suggestion_id}' is "
                f"{record.status}, not proposed"
            )

        updated = Suggestion(
            suggestion_id=record.suggestion_id,
            media_id=record.media_id,
            analysis_fingerprint=record.analysis_fingerprint,
            matched_rule_id=record.matched_rule_id,
            rule_version=record.rule_version,
            source_example_ids=record.source_example_ids,
            proposed_answer=record.proposed_answer,
            coverage_state=record.coverage_state,
            reason=record.reason,
            status=new_status,
            computed_at=record.computed_at,
        )

        self._records[suggestion_id] = updated
        self._transitions.append({
            "suggestion_id": suggestion_id,
            "from": record.status,
            "to": new_status,
        })

        return updated
