"""
Preference Experience application service (Phase 16 GUI boundary).

Thin orchestration over the Phase 15 preference domain
(`app/preferences/`) and the durable Phase 15E review ledger.
This service owns NO intelligence of its own:

- candidate selection comes only from `select_candidates` /
  `select_next` (sampling.py);
- rule compilation comes only from `PreferenceCompiler`;
- coverage states come only from `CoverageEvaluator`;
- suggestion generation comes only from `generate_for_file`;
- review transitions come only from `review.py` functions;
- future-scan states come only from `evaluate_scan`.

Wizard sessions are held in a process-local in-memory store keyed
by session id (the web layer is stateless; the session id travels
in hidden form fields and query parameters, following the existing
self-contained POST convention). Draft session details remain
process-local, but the authoritative Wizard cursor is durable:
every explicit answer is written to `preference_wizard_progress`
(migration 042) against the logical media identity, and
`preference_wizard_state` records the last completed item, the
intentional-stop flag, current-population completion, and explicit
reset. Continuation therefore survives an application/service
restart. Cancelling a session restores the pre-session durable
progress; `Reset Wizard` clears Wizard progress only and never
touches accepted preferences, review history, execution history,
observations, or lineage.

UserIntent handling: intents are captured per wizard session for
display context only. Durable intent ownership/storage and
scan-pipeline delivery are unresolved (Phase16.md section 6), so
this service invents no intent table, no intent writes, and no
delivery path. The scan path continues to use accepted examples
only, through the existing `_scan_preference_state` provider.
"""

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone

from app.database.repositories.execution_repository import (
    ExecutionRepository,
)

from app.database.repositories.preference_review_repository import (
    PreferenceReviewRepository,
)

from app.database.repositories.preference_wizard_progress_repository import (
    PreferenceWizardProgressRepository,
)

from app.preferences.compiler import PreferenceCompiler
from app.preferences.continuity import (
    evaluate_scan,
    fingerprint_facts,
)
from app.preferences.coverage import CoverageEvaluator
from app.preferences.dimensions import ANSWERS
from app.preferences.examples import PreferenceExample
from app.preferences.intent import UserIntent
from app.preferences.review import (
    accept_review,
    bulk_accept_review,
    change_review,
    conflicting_evidence,
    load_accepted_scan_state,
    propose_review,
    reopen_review,
    reject_review,
)
from app.preferences.sampling import (
    example_from_answer,
    select_candidates,
    select_next,
    WizardSession,
)
from app.preferences.suggestions import generate_for_file


_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()


#: Review-facing coverage labels (mirrors the template vocabulary).
#: Used only to label a file that has no review decision of its own.
_COVERAGE_LABELS_FOR_SERVICE = {
    "covered": ("Covered", "current"),
    "covered-explicit": ("Covered by an explicit preference", "current"),
    "partial": ("Partially covered", "pending"),
    "ambiguous": ("Needs clarification", "unknown"),
    "uncovered": ("Not yet covered", "missing"),
}


#: Per-file recommendation summary fields shared by Review Suggestions
#: and the Optimisation Carousel. Each entry is
#: (key, label, category, signal_rule, fact_key). The signal rule
#: names and fact keys are the EXISTING authoritative vocabularies;
#: this table introduces no new recommendation intelligence. A field
#: is a CHANGE when a surviving optimize/remux signal addresses it, a
#: NO CHANGE when only a preserve/constraint signal addresses it, and
#: NO RECOMMENDATION when no signal addresses it.
RECOMMENDATION_FIELD_SPECS = (
    ("codec", "Video codec", "Video", "codec_rule", "codec"),
    ("audio_codec", "Audio codec", "Audio", "audio_rule", "audio_codec"),
    (
        "resolution",
        "Resolution",
        "Picture",
        "resolution_rule",
        "resolution",
    ),
    (
        "bitrate",
        "Video bitrate",
        "Picture",
        "bitrate_rule",
        "bitrate_class",
    ),
    ("container", "Container", "Format", "container_rule", "container"),
    (
        "audio_channels",
        "Audio channels",
        "Audio",
        None,
        "audio_channels",
    ),
)

#: Signal directions that propose a change (existing decision-engine
#: vocabulary).
_OPTIMIZE_DIRECTIONS = frozenset({"optimize", "remux"})


def _is_truthy(value):
    """Form-value truthiness for checkbox/boolean fields."""

    if isinstance(value, bool):
        return value

    if isinstance(value, (list, tuple)):
        return any(_is_truthy(item) for item in value)

    return str(value or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _display_dimension_value(dimension, value):
    """Display formatting for one measured recommendation fact."""

    if value is None:
        return None

    if dimension == "resolution":
        try:
            height = int(value)
        except (TypeError, ValueError):
            return str(value)

        if height >= 2160:
            return "2160p"
        if height >= 1080:
            return "1080p"
        if height >= 720:
            return "720p"
        return "480p"

    if dimension == "bitrate_class":
        try:
            bps = int(value)
        except (TypeError, ValueError):
            return str(value)

        if bps >= 1_000_000:
            return f"{bps / 1_000_000:.1f} Mbps"

        return f"{bps / 1000:.0f} kbps"

    if dimension == "audio_channels":
        try:
            return f"{int(value)} channels"
        except (TypeError, ValueError):
            return str(value)

    if dimension in ("codec", "audio_codec", "container"):
        return str(value).upper()

    return str(value)


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def create_session_record(intent, population, fingerprint):
    """Create one wizard session record; returns (session_id, record)."""

    session_id = uuid.uuid4().hex

    record = {
        "session": WizardSession(
            session_id=session_id,
            population_fingerprint=fingerprint,
        ),
        "intent": intent,
        "population": population,
        "created_at": _utcnow(),
    }

    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = record

    return session_id, record


def get_session_record(session_id):
    """Return the live session record, or None when unknown."""

    if not session_id:
        return None

    with _SESSIONS_LOCK:
        return _SESSIONS.get(session_id)


def save_session_record(session_id, record):
    """Replace the stored session record (answers/finish only)."""

    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = record


def drop_session_record(session_id):
    """Cancel semantics: dropping the record discards the session."""

    with _SESSIONS_LOCK:
        _SESSIONS.pop(session_id, None)


def clear_session_records():
    """Test support: drop every session record."""

    with _SESSIONS_LOCK:
        _SESSIONS.clear()


def _parse_resolution_height(value):
    """Parse a persisted 'WxH' resolution string to a height int."""

    if value is None:
        return None

    text = str(value).strip()

    if "x" not in text.lower():
        return None

    try:
        return int(text.lower().split("x", 1)[1])
    except (ValueError, IndexError):
        return None


class PreferenceService:
    """
    Application boundary for the Phase 16 preference experience.

    Constructed with injected repositories/services; owns the
    review-ledger connection commit after mutating review calls
    (caller-owns-transactions convention, mirroring
    StandingDecisionService).
    """

    def __init__(
        self,
        *,
        connection,
        media_repository,
        analysis_repository,
        validity_service,
        user_policy_service,
    ):
        self._connection = connection
        self._media_repository = media_repository
        self._analysis_repository = analysis_repository
        self._validity_service = validity_service
        self._user_policy_service = user_policy_service
        self._review_repository = PreferenceReviewRepository(
            connection
        )
        # Durable Wizard progress (migration 042). This records which
        # logical media items the Wizard has answered and its cursor
        # flags. It carries no preference authority: acceptance and
        # rule compilation remain owned by the review lifecycle.
        self._wizard_progress = (
            PreferenceWizardProgressRepository(connection)
        )
        # Existing execution authority, read-only here, used to
        # distinguish a made decision from completed execution.
        self._execution_repository = ExecutionRepository(connection)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def build_population(self):
        """
        Build the wizard population from active lineages with
        currently valid persisted analysis facts.

        Returns (usable, unusable_count) where each usable entry is
        {media_id, file_name, file_path, file_size_bytes, facts}.
        Facts use the same raw pipeline-style keys as
        `save_to_db` preference_facts (resolution height int,
        codec, bitrate_class int, container, audio_codec, hdr,
        source_label, size_class int, audio_channels); absent
        values are omitted, never invented.
        """

        usable = []
        unusable = 0

        for lineage in (
            self._media_repository.get_active_lineages()
        ):
            try:
                facts = self._facts_for_lineage(lineage)
            except Exception:
                unusable += 1
                continue

            if not facts:
                unusable += 1
                continue

            try:
                CoverageEvaluator().evaluate([], dict(facts))
            except ValueError:
                unusable += 1
                continue

            usable.append(
                {
                    "media_id": str(lineage.id),
                    "file_name": lineage.file_name,
                    "file_path": lineage.file_path,
                    "file_size_bytes": lineage.file_size_bytes,
                    "facts": facts,
                }
            )

        usable.sort(key=lambda entry: entry["media_id"])

        return usable, unusable

    def _facts_for_lineage(self, lineage):
        """Read persisted analysis facts for one lineage, or None."""

        validity = self._validity_service.get_validity(
            lineage.id,
            current_size_bytes=lineage.file_size_bytes,
            current_file_mtime_ns=lineage.file_mtime_ns,
        )

        run = validity.valid_analysis_run

        if run is None:
            return None

        record = self._analysis_repository.get_media_analysis(
            run.id
        )

        if record is None:
            return None

        facts = {}

        height = _parse_resolution_height(record.resolution)

        if height is not None:
            facts["resolution"] = height

        if record.video_codec:
            facts["codec"] = record.video_codec

        if record.bitrate:
            facts["bitrate_class"] = int(record.bitrate)

        if record.container:
            facts["container"] = record.container

        if lineage.file_size_bytes:
            facts["size_class"] = int(lineage.file_size_bytes)

        audio_tracks = getattr(record, "audio_tracks", None)

        if audio_tracks:
            facts["audio_channels"] = int(audio_tracks)

        return facts

    @staticmethod
    def population_fingerprint(population):
        """Deterministic fingerprint over one population snapshot."""

        digest_input = sorted(
            json.dumps(
                {
                    "media_id": entry["media_id"],
                    "fingerprint": fingerprint_facts(
                        entry["facts"]
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for entry in population
        )

        return hashlib.sha256(
            json.dumps(
                digest_input,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------
    # Accepted (durable) state
    # ------------------------------------------------------------------

    def accepted_state(self):
        """
        Read-only accepted preference state (rules plus explicit
        scopes), or None when no accepted examples exist.
        """

        return load_accepted_scan_state(self._review_repository)

    def established_rules(self):
        """Accepted ordered rules and explicit scopes, or ([], ())."""

        state = self.accepted_state()

        if state is None:
            return [], ()

        return list(state.rules), tuple(state.explicit_scopes)

    # ------------------------------------------------------------------
    # Wizard sessions
    # ------------------------------------------------------------------

    def start_wizard(
        self,
        *,
        compatibility=None,
        quality_ceiling=None,
        optimisation=None,
        mode="fresh",
    ):
        """
        Validate one UserIntent triple, snapshot the population,
        and open a wizard session. Unknown vocabulary raises
        ValueError (the UI renders a 400); missing values fall
        back to the established defaults. Mode "continue" marks
        the session to select questions against session answers
        plus established (accepted) rules, so already-decided
        files are never re-asked; mode "fresh" selects from
        session answers only. Unknown modes raise ValueError.
        """

        if mode not in ("fresh", "continue"):
            raise ValueError(
                f"unknown wizard mode '{mode}'"
            )

        intent = UserIntent(
            compatibility=(
                compatibility or UserIntent.default().compatibility
            ),
            quality_ceiling=(
                quality_ceiling
                or UserIntent.default().quality_ceiling
            ),
            optimisation=(
                optimisation
                or UserIntent.default().optimisation
            ),
        )

        population, unusable = self.build_population()

        fingerprint = self.population_fingerprint(population)

        session_id, record = create_session_record(
            intent, population, fingerprint
        )

        record["use_established"] = (mode == "continue")

        # Snapshot durable progress at session start so Cancel can
        # restore exactly the pre-session decisions. The Wizard's
        # authoritative cursor is the durable store, not this record.
        record["progress_baseline"] = self._wizard_progress.answered()

        self._wizard_progress.mark_started()

        self._connection.commit()

        save_session_record(session_id, record)

        return session_id, record, unusable

    @staticmethod
    def asked_ids(record):
        """Media ids already answered in this session."""

        return [
            media_id
            for media_id, _ in record["session"].answers
        ]

    def selection_asked_ids(self, record):
        """
        Media ids excluded from question selection.

        A continuing session excludes both its own answers and every
        logical media item the Wizard has durably answered, so an
        answered item is never asked again across a restart. A fresh
        (explicit start-over) session excludes only its own answers
        and deliberately re-asks from the beginning.
        """

        ids = list(self.asked_ids(record))

        if record.get("use_established"):
            for media_id in self._wizard_progress.answered_ids():
                if media_id not in ids:
                    ids.append(media_id)

        return ids

    def durable_progress(self):
        """Durable Wizard progress summary (authoritative cursor)."""

        answers = self._wizard_progress.answered()

        state = self._wizard_progress.state()

        return {
            "answered": len(answers),
            "last_media_id": state.get("last_media_id"),
            "stopped": state.get("stopped"),
            "completed": state.get("completed"),
            "reset_at": state.get("reset_at"),
            "answers": answers,
        }

    def _progress_lookup(self, media_id):
        """File name for one durable progress media id, if known."""

        population, _ = self.build_population()

        for entry in population:
            if entry["media_id"] == str(media_id):
                return entry["file_name"]

        return None

    def reset_wizard(self):
        """
        Explicit Wizard reset. Clears durable Wizard progress and
        cursor flags only; accepted preferences, review history,
        execution history, observations and lineage are untouched.
        """

        self._wizard_progress.reset()

        self._connection.commit()

        return self.wizard_intro_view()

    @staticmethod
    def population_lookup(record):
        """Map media_id to its population entry for this session."""

        return {
            entry["media_id"]: entry
            for entry in record["population"]
        }

    def session_examples(self, record):
        """Explicit PreferenceExamples for every session answer."""

        lookup = self.population_lookup(record)

        examples = []

        for media_id, answer in record["session"].answers:
            entry = lookup.get(media_id)

            if entry is None:
                continue

            examples.append(
                example_from_answer(
                    record["session"].session_id,
                    media_id,
                    answer,
                    entry["facts"],
                )
            )

        return examples

    def session_rules(self, record):
        """Compile session answers; returns (rules, scopes, result)."""

        examples = self.session_examples(record)

        result = PreferenceCompiler().compile(examples)

        scopes = tuple(
            example.normalised_scope() for example in examples
        )

        return list(result.rules), scopes, result

    def next_candidate(self, record, rules, scopes):
        """Authoritative next question, or None at sufficiency."""

        population = [
            {
                "media_id": entry["media_id"],
                "facts": entry["facts"],
            }
            for entry in record["population"]
        ]

        return select_next(
            population,
            rules,
            scopes,
            self.selection_asked_ids(record),
        )

    def selection_state(self, record, rules, scopes):
        """Full selection result (stats and stop reason included)."""

        population = [
            {
                "media_id": entry["media_id"],
                "facts": entry["facts"],
            }
            for entry in record["population"]
        ]

        return select_candidates(
            population,
            rules,
            scopes,
            self.selection_asked_ids(record),
        )

    def record_session_answer(self, record, media_id, answer):
        """
        Record one explicit answer and persist it durably against the
        logical media item immediately, so progress survives a
        process restart even when the user only stops.
        """

        session = record["session"].record_answer(media_id, answer)

        record["session"] = session

        self._wizard_progress.record_answer(media_id, answer)

        self._wizard_progress.set_last_media(media_id)

        self._connection.commit()

        save_session_record(session.session_id, record)

        return record

    def undo_session_answer(self, record):
        """
        Drop the most recent answer, restore durable progress for that
        logical media item to its pre-session value, and return the
        updated record.
        """

        dropped = None

        if record["session"].answers:
            dropped = record["session"].answers[-1][0]

        session = record["session"].undo_last_answer()

        record["session"] = session

        if dropped is not None:
            baseline = record.get("progress_baseline", {})

            if dropped in baseline:
                self._wizard_progress.restore_answer(
                    dropped, baseline[dropped]
                )
            else:
                self._wizard_progress.delete([dropped])

            if session.answers:
                self._wizard_progress.set_last_media(
                    session.answers[-1][0]
                )

            self._connection.commit()

        save_session_record(session.session_id, record)

        return record

    def finish_session(self, record):
        """Mark the session finished; returns the updated record."""

        session = record["session"].finish()

        record["session"] = session

        save_session_record(session.session_id, record)

        return record

    # ------------------------------------------------------------------
    # Coverage over a population
    # ------------------------------------------------------------------

    @staticmethod
    def coverage_for_population(population, rules, scopes):
        """Evaluate every population file; returns {media_id: result}."""

        evaluator = CoverageEvaluator()

        results = {}

        for entry in population:
            results[entry["media_id"]] = evaluator.evaluate(
                list(rules or []),
                dict(entry["facts"]),
                scopes,
            )

        return results

    # ------------------------------------------------------------------
    # Review lifecycle (durable; every call commits on success)
    # ------------------------------------------------------------------

    def _commit(self):
        self._review_repository.connection.commit()

    def list_suggestions(self, status=None, media_id=None):
        return self._review_repository.list_suggestions(
            status=status, media_id=media_id
        )

    def get_suggestion(self, suggestion_id):
        return self._review_repository.get_suggestion(
            suggestion_id
        )

    def suggestion_events(self, suggestion_id):
        return self._review_repository.events_for(suggestion_id)

    def _propose_new_only(self, generated, *, actor):
        """
        Propose generated suggestions while respecting decided
        lifecycle state: rows whose ids already exist in a
        decided (non-proposed) status are skipped, never
        re-proposed, so normal generation can never attempt an
        invalid transition. Decided rows are left untouched;
        identical active rows remain idempotent through
        `propose_review`. Returns (stored, proposed_new,
        skipped_decided).
        """

        fresh = []
        skipped_decided = 0
        already_active = 0

        for suggestion in generated:
            existing = self._review_repository.get_suggestion(
                suggestion.suggestion_id
            )

            if existing is None:
                fresh.append(suggestion)
            elif existing.status == "proposed":
                fresh.append(suggestion)
                already_active += 1
            else:
                skipped_decided += 1

        stored = propose_review(
            self._review_repository, fresh, actor=actor
        )

        self._commit()

        return stored, len(fresh) - already_active, skipped_decided

    def refresh_suggestions(self, *, actor="human"):
        """
        Generate suggestions from accepted rules over the current
        population and propose the undecided ones (idempotent).
        Returns {generated, proposed, skipped_decided,
        stored_total}. Never writes suggestions from uncovered
        files or Leave-alone matches: generation itself yields
        none there. Already-decided rows are skipped, never
        re-proposed.
        """

        rules, scopes = self.established_rules()

        population, _ = self.build_population()

        generated = []

        for entry in population:
            generated.extend(
                generate_for_file(
                    media_id=entry["media_id"],
                    analysis_fingerprint=fingerprint_facts(
                        entry["facts"]
                    ),
                    rules=rules,
                    facts=entry["facts"],
                    explicit_scopes=scopes,
                )
            )

        stored, proposed_new, skipped = self._propose_new_only(
            generated, actor=actor
        )

        return {
            "generated": len(generated),
            "proposed": proposed_new,
            "skipped_decided": skipped,
            "stored_total": len(
                self._review_repository.list_suggestions()
            ),
            "stored": stored,
        }

    def save_session_suggestions(self, record, *, actor="human"):
        """
        Compile one finished session and propose its undecided
        suggestions for review. Already-decided rows are
        skipped, never re-proposed, so saving twice (or saving
        overlapping sessions) cannot attempt an invalid
        transition. Suggestions gain zero authority here; they
        become preferences only through explicit acceptance on
        the review flow.
        """

        rules, scopes, _ = self.session_rules(record)

        generated = []

        for entry in record["population"]:
            generated.extend(
                generate_for_file(
                    media_id=entry["media_id"],
                    analysis_fingerprint=fingerprint_facts(
                        entry["facts"]
                    ),
                    rules=rules,
                    facts=entry["facts"],
                    explicit_scopes=scopes,
                )
            )

        stored, proposed_new, skipped = self._propose_new_only(
            generated, actor=actor
        )

        return {
            "rules": rules,
            "generated": len(generated),
            "proposed": proposed_new,
            "skipped_decided": skipped,
            "stored": stored,
        }

    def accept_suggestion(
        self,
        suggestion_id,
        *,
        actor="human",
    ):
        """
        Accept one suggestion, proving currency from presently
        observed state. Stale or ambiguous rows raise ValueError with
        nothing written. Caller-supplied proof is never accepted.
        """

        return self._accept_with_observed_proof(
            suggestion_id, actor
        )

    def _accept_with_observed_proof(self, suggestion_id, actor):
        """
        Shared acceptance: derive observed currency proof server-side
        and accept. Ambiguous rows are refused by the authoritative
        backend before proof comparison.
        """

        record = self._review_repository.get_suggestion(
            suggestion_id
        )

        if record is None:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.proposed_answer is None:
            # Ambiguous rows cannot be accepted; the backend
            # refuses them before any proof comparison, so the
            # stored values below never decide anything.
            accepted, example_id = accept_review(
                self._review_repository,
                suggestion_id,
                actor,
                record.rule_version,
                record.analysis_fingerprint,
                facts=None,
            )

            self._commit()

            return accepted, example_id

        population, _ = self.build_population()

        facts = None

        for entry in population:
            if entry["media_id"] == record.media_id:
                facts = dict(entry["facts"])
                break

        if facts is None:
            raise ValueError(
                "media facts for this suggestion are no "
                "longer available; it cannot be accepted"
            )

        observed_fingerprint = fingerprint_facts(facts)
        observed_rule_version = self._observed_rule_version(
            record
        )

        accepted, example_id = accept_review(
            self._review_repository,
            suggestion_id,
            actor,
            observed_rule_version,
            observed_fingerprint,
            facts=facts,
        )

        self._commit()

        return accepted, example_id

    def specify_recommendation(
        self, suggestion_id, answer, *, actor="human"
    ):
        """
        Explicitly specify a recommendation for a Needs More Context
        item using the existing Wizard answer vocabulary. The chosen
        answer is recorded on the review lifecycle and accepted as
        the user's explicit decision; no guessing and no separate
        preference system. The item leaves Needs More Context and, for
        an actionable answer, enters Waiting for Execution. Nothing
        here claims any execution occurred.
        """

        if answer not in ANSWERS:
            raise ValueError(
                f"unknown preference answer '{answer}'"
            )

        record = self._review_repository.get_suggestion(
            suggestion_id
        )

        if record is None:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.status != "proposed":
            raise ValueError(
                f"suggestion '{suggestion_id}' is "
                f"{record.status}, not proposed"
            )

        if record.proposed_answer != answer:
            replacement = change_review(
                self._review_repository,
                suggestion_id,
                actor,
                answer,
            )

            target_id = replacement.suggestion_id
        else:
            target_id = suggestion_id

        accepted, example_id = self._accept_with_observed_proof(
            target_id, actor
        )

        return accepted, example_id

    def _observed_rule_version(self, record):
        """
        Presently applicable derivation version for one stored
        row: the current accepted rule's version where the
        matched rule is established, else the stored value (the
        only value the existing architecture makes available
        for unaccepted basis rules).
        """

        rules, _ = self.established_rules()

        for rule in rules:
            if rule.rule_id == record.matched_rule_id:
                return rule.derivation_version

        return record.rule_version

    def reject_suggestion(
        self, suggestion_id, *, actor="human", reason=None
    ):
        rejected = reject_review(
            self._review_repository,
            suggestion_id,
            actor,
            reason=reason,
        )

        self._commit()

        return rejected

    def change_suggestion(
        self, suggestion_id, new_answer, *, actor="human"
    ):
        replacement = change_review(
            self._review_repository,
            suggestion_id,
            actor,
            new_answer,
        )

        self._commit()

        return replacement

    def reopen_suggestion(self, suggestion_id, *, actor="human"):
        record = reopen_review(
            self._review_repository, suggestion_id, actor
        )

        self._commit()

        return record

    def accept_all_suggestions(self, *, actor="human"):
        """
        Atomic bulk acceptance over currently proposed rows. The
        `expected` map is derived internally from presently
        observed state per row (observed fingerprint; resolved
        or stored rule version, as in `accept_suggestion`); no
        caller-supplied map is accepted. Anything missing,
        stale, or ambiguous fails the whole batch with zero
        writes, enforced by the authoritative backend.
        """

        rows = self._review_repository.list_suggestions(
            status="proposed"
        )

        population, _ = self.build_population()

        lookup = {
            entry["media_id"]: entry for entry in population
        }

        rules, _ = self.established_rules()

        by_rule = {rule.rule_id: rule for rule in rules}

        expected = {}

        for row in rows:
            if row.proposed_answer is None:
                # Ambiguous rows are refused by the backend
                # before proof comparison; stored values here
                # decide nothing.
                expected[row.suggestion_id] = (
                    row.rule_version,
                    row.analysis_fingerprint,
                )
                continue

            entry = lookup.get(row.media_id)

            if entry is None:
                # No current facts: omit the expectation so the
                # backend refuses the batch rather than trusting
                # a vanished basis.
                continue

            rule = by_rule.get(row.matched_rule_id)

            expected[row.suggestion_id] = (
                (
                    rule.derivation_version
                    if rule is not None
                    else row.rule_version
                ),
                fingerprint_facts(entry["facts"]),
            )

        ids = [row.suggestion_id for row in rows]

        accepted = bulk_accept_review(
            self._review_repository, ids, actor, expected
        )

        self._commit()

        return accepted

    def ambiguous_evidence(self, media_id):
        """Conflicting evidence for one file's ambiguous review."""

        rules, _ = self.established_rules()

        return conflicting_evidence(
            self._review_repository, media_id, rules
        )

    # ------------------------------------------------------------------
    # Future-scan status (read-only recomputation, never a queue)
    # ------------------------------------------------------------------

    def continuity_status(self):
        """
        Recompute continuity over the current population from
        accepted state. Returns {available, outcomes, stats} or
        {available: False} when no accepted examples exist. The
        default intent applies here: durable intent delivery is
        unresolved, so no session or stored intent is used.
        """

        state = self.accepted_state()

        if state is None:
            return {"available": False}

        population, _ = self.build_population()

        result = evaluate_scan(
            files=[
                {
                    "media_id": entry["media_id"],
                    "facts": entry["facts"],
                }
                for entry in population
            ],
            rules=list(state.rules),
            explicit_scopes=tuple(state.explicit_scopes),
            base_policy=(
                self._user_policy_service.get_effective_policy()
            ),
        )

        return {
            "available": True,
            "outcomes": [outcome.to_dict() for outcome in result.outcomes],
            "stats": result.stats_dict(),
        }

    # ------------------------------------------------------------------
    # Intent vocabulary (display only; vocabularies are closed)
    # ------------------------------------------------------------------

    @staticmethod
    def intent_vocab():
        """Closed UserIntent vocabularies plus defaults for forms."""

        from app.preferences.intent import (
            COMPATIBILITY_TARGETS,
            OPTIMISATION_PREFERENCES,
            QUALITY_CEILINGS,
        )

        defaults = UserIntent.default()

        return {
            "compatibility": sorted(COMPATIBILITY_TARGETS),
            "quality_ceiling": sorted(QUALITY_CEILINGS),
            "optimisation": sorted(OPTIMISATION_PREFERENCES),
            "defaults": defaults.to_dict(),
        }

    @staticmethod
    def default_intent_dict():
        """The default intent triple (no durable intent exists)."""

        return UserIntent.default().to_dict()

    # ------------------------------------------------------------------
    # Wizard view models (JSON-safe plain dicts for handlers)
    # ------------------------------------------------------------------

    def selection_rules(self, record):
        """
        Rules driving question selection and coverage feedback:
        always the session's own compiled rules, plus the
        accepted (established) rules when this session continues
        existing progress. Session rules come first so newer
        explicit answers take precedence in display; ambiguity
        detection itself is order-independent. Compilation of
        the session's own answers (`session_rules`) is
        unaffected: selection input, not a second compiler.
        """

        rules, scopes, result = self.session_rules(record)

        if not record.get("use_established"):
            return rules, scopes, result

        accepted_rules, accepted_scopes = self.established_rules()

        known = {rule.rule_id for rule in rules}

        combined = list(rules) + [
            rule for rule in accepted_rules
            if rule.rule_id not in known
        ]

        seen_scopes = set(scopes)

        combined_scopes = tuple(scopes) + tuple(
            scope for scope in accepted_scopes
            if scope not in seen_scopes
        )

        return combined, combined_scopes, result

    def coverage_summary(self):
        """
        Compact coverage summary over the current population under
        the accepted rules: state counts, population total, and the
        count of files still needing analysis. Read-only.
        """

        population, unusable = self.build_population()

        rules, scopes = self.established_rules()

        coverage = self.coverage_for_population(
            population, rules, scopes
        )

        state_counts = {}

        for result in coverage.values():
            state_counts[result.state] = (
                state_counts.get(result.state, 0) + 1
            )

        names = {
            entry["media_id"]: entry["file_name"]
            for entry in population
        }

        return {
            "states": state_counts,
            "population_total": len(population),
            "unusable": unusable,
            "population": population,
            "names": names,
        }

    def wizard_intro_view(self):
        """
        Intro data: vocab, durable progress, and a compact coverage
        summary. Progress and continuation both read the same durable
        store, so displayed progress and actual continuation can
        never disagree.
        """

        state = self.accepted_state()

        if state is None:
            established = {
                "has_state": False,
                "rules": 0,
                "examples": 0,
            }
        else:
            established = {
                "has_state": True,
                "rules": len(state.rules),
                "examples": len(state.explicit_scopes),
            }

        summary = self.coverage_summary()

        durable = self.durable_progress()

        last_name = None

        if durable.get("last_media_id") is not None:
            last_name = summary["names"].get(
                str(durable["last_media_id"])
            )

        progress = {
            "has_progress": durable["answered"] > 0,
            "answered": durable["answered"],
            "last_media_id": durable.get("last_media_id"),
            "last_file_name": last_name,
            "stopped": durable.get("stopped"),
            "completed": durable.get("completed"),
            "reset_at": durable.get("reset_at"),
        }

        return {
            "mode": "intro",
            "vocab": self.intent_vocab(),
            "established": established,
            "progress": progress,
            "coverage": {
                "states": summary["states"],
                "population_total": summary["population_total"],
                "unusable": summary["unusable"],
            },
        }

    def _question_view(self, record):
        """Build the current question (or sufficiency) view."""

        rules, scopes, _ = self.selection_rules(record)

        session_rules, _, _ = self.session_rules(record)

        candidate = self.next_candidate(record, rules, scopes)

        selection = self.selection_state(record, rules, scopes)

        coverage = self.coverage_for_population(
            record["population"], rules, scopes
        )

        state_counts = {}

        for result in coverage.values():
            state_counts[result.state] = (
                state_counts.get(result.state, 0) + 1
            )

        lookup = self.population_lookup(record)

        durable = self.durable_progress()

        view = {
            "session_id": record["session"].session_id,
            "intent": record["intent"].to_dict(),
            "continued": bool(record.get("use_established")),
            "progress": record["session"].progress(),
            "durable_progress": {
                "answered": durable["answered"],
            },
            "population_total": len(record["population"]),
            "selection_stats": selection.stats_dict(),
            "stop_reason": selection.stop_reason,
            "feedback": {
                "answered": len(record["session"].answers),
                "rules_compiled": len(session_rules),
                "coverage_states": state_counts,
            },
        }

        if candidate is None:
            view["mode"] = "sufficient"
            view["candidate"] = None
            view["file"] = None
        else:
            entry = lookup.get(candidate.media_id, {})

            view["mode"] = "question"
            view["candidate"] = candidate.to_dict()
            view["file"] = {
                "media_id": candidate.media_id,
                "file_name": entry.get("file_name"),
                "file_path": entry.get("file_path"),
                "file_size_bytes": entry.get("file_size_bytes"),
            }

        return view

    def wizard_start_view(
        self, compatibility=None, quality_ceiling=None,
        optimisation=None, mode="fresh",
    ):
        """Open a session and return its first question view."""

        session_id, record, unusable = self.start_wizard(
            compatibility=compatibility,
            quality_ceiling=quality_ceiling,
            optimisation=optimisation,
            mode=mode,
        )

        if not record["population"]:
            drop_session_record(session_id)

            return {"mode": "empty", "unusable": unusable}

        view = self._question_view(record)
        view["unusable"] = unusable

        return view

    def wizard_view(self, session_id):
        """Current view for a live session (question/sufficient)."""

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        if record["session"].finished:
            return self.wizard_completion_view(session_id)

        return self._question_view(record)

    def wizard_answer_view(self, session_id, media_id, answer):
        """Record one answer and return the resulting view."""

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        if record["session"].finished:
            raise ValueError(
                "this wizard session is already finished"
            )

        lookup = self.population_lookup(record)

        if media_id not in lookup:
            raise ValueError("unknown media for this session")

        record = self.record_session_answer(
            record, media_id, answer
        )

        return self._question_view(record)

    def wizard_undo_view(self, session_id):
        """Drop the most recent answer and return the view."""

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        if record["session"].finished:
            raise ValueError(
                "this wizard session is already finished"
            )

        record = self.undo_session_answer(record)

        return self._question_view(record)

    def wizard_completion_view(self, session_id):
        """Completion view: rules established, early/sufficient marked."""

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        rules, scopes, result = self.session_rules(record)

        selection_rules, selection_scopes, _ = (
            self.selection_rules(record)
        )

        selection = self.selection_state(
            record, selection_rules, selection_scopes
        )

        sufficient = selection.stopped and (
            selection.stop_reason
            in ("no-useful-candidates", "empty-population")
        )

        # Durable cursor: the user has intentionally stopped here;
        # whether the eligible population is complete is derived from
        # authoritative selection, not guessed.
        self._wizard_progress.mark_stopped(completed=bool(sufficient))

        self._connection.commit()

        lookup = self.population_lookup(record)

        answers = []

        for media_id, answer in record["session"].answers:
            entry = lookup.get(media_id, {})

            answers.append(
                {
                    "media_id": media_id,
                    "answer": answer,
                    "file_name": entry.get("file_name"),
                }
            )

        return {
            "mode": "complete",
            "session_id": record["session"].session_id,
            "intent": record["intent"].to_dict(),
            "continued": bool(record.get("use_established")),
            "early": bool(not sufficient),
            "sufficient": bool(sufficient),
            "stop_reason": selection.stop_reason,
            "answers": answers,
            "rules": [rule.to_dict() for rule in rules],
            "conflicts": list(result.conflicts),
            "finished": record["session"].finished,
        }

    def wizard_finish_view(self, session_id):
        """Mark finished (early or at sufficiency) and show completion."""

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        record = self.finish_session(record)

        return self.wizard_completion_view(session_id)

    def wizard_cancel_view(self, session_id):
        """
        Cancel discards this session's answers. Durable progress is
        restored to exactly its pre-session state: media the session
        first answered lose their progress row again, and media the
        session re-answered return to their previous answer.
        """

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        baseline = record.get("progress_baseline", {})

        for media_id, _answer in record["session"].answers:
            if media_id in baseline:
                self._wizard_progress.restore_answer(
                    media_id, baseline[media_id]
                )
            else:
                self._wizard_progress.delete([media_id])

        self._connection.commit()

        drop_session_record(session_id)

        return {"mode": "cancelled"}

    def wizard_save_view(self, session_id, *, actor="human"):
        """
        Propose the finished session's suggestions for review.
        Requires at least one answer; the session is marked
        finished. Returned suggestions carry zero authority until
        explicitly accepted on the review flow.
        """

        record = get_session_record(session_id)

        if record is None:
            raise ValueError(
                "unknown or expired wizard session"
            )

        if not record["session"].answers:
            raise ValueError(
                "answer at least one question before saving"
            )

        record = self.finish_session(record)

        self._wizard_progress.mark_stopped()

        self._connection.commit()

        saved = self.save_session_suggestions(
            record, actor=actor
        )

        return {
            "mode": "saved",
            "session_id": record["session"].session_id,
            "rules": [
                rule.to_dict() for rule in saved["rules"]
            ],
            "generated": saved["generated"],
            "stored": [row.to_dict() for row in saved["stored"]],
        }

    # ------------------------------------------------------------------
    # Preference Centre + review view models
    # ------------------------------------------------------------------

    def centre_view(self):
        """
        Everything the launch screen renders, read-only: intent,
        established preferences, compact coverage summary, durable
        Wizard progress, and future-scan status. No media listing and
        no review dashboard: those belong to the Review Suggestions
        surface.
        """

        summary = self.coverage_summary()

        rules, _scopes = self.established_rules()

        state = self.accepted_state()

        durable = self.durable_progress()

        last_name = None

        if durable.get("last_media_id") is not None:
            last_name = summary["names"].get(
                str(durable["last_media_id"])
            )

        return {
            "intent": self.default_intent_dict(),
            "intent_note": (
                "NAMOA defaults. Per-profile intent persistence "
                "is not yet established, so these defaults apply "
                "until that architecture is approved."
            ),
            "rules": [rule.to_dict() for rule in rules],
            "accepted_examples": (
                len(state.explicit_scopes) if state else 0
            ),
            "population_total": summary["population_total"],
            "unusable": summary["unusable"],
            "coverage_states": summary["states"],
            "progress": {
                "has_progress": durable["answered"] > 0,
                "answered": durable["answered"],
                "last_media_id": durable.get("last_media_id"),
                "last_file_name": last_name,
                "stopped": durable.get("stopped"),
                "completed": durable.get("completed"),
            },
            "continuity": self.continuity_view(
                summary["population"]
            ),
        }

    def review_rows(self, population=None):
        """
        Proposed suggestions enriched for display: file names,
        display-only staleness, and whether the basis rule is
        currently established. Currency proof is derived
        server-side at accept time and is never exposed here:
        no consumer may treat display data as acceptance proof.
        """

        if population is None:
            population, _ = self.build_population()

        lookup = {
            entry["media_id"]: entry for entry in population
        }

        rules, _ = self.established_rules()

        by_rule = {rule.rule_id: rule for rule in rules}

        completion = self.execution_completion()

        rows = []

        for row in self.list_suggestions(status="proposed"):
            entry = lookup.get(row.media_id)

            current_fp = (
                fingerprint_facts(entry["facts"])
                if entry is not None
                else None
            )

            rule = by_rule.get(row.matched_rule_id)

            # Display-only staleness: the media facts moved, or an
            # established basis rule changed version underneath the
            # row. A rule unknown to the accepted set is not stale;
            # it is pre-establishment session basis (flagged via
            # `established` so the UI can say so honestly).
            # Enforcement stays with the backend currency proof.
            stale = (
                entry is None
                or current_fp != row.analysis_fingerprint
                or (
                    rule is not None
                    and rule.derivation_version != row.rule_version
                )
            )

            rows.append(
                {
                    "suggestion": row.to_dict(),
                    "file_name": (
                        entry["file_name"]
                        if entry is not None
                        else None
                    ),
                    "file_size_bytes": (
                        entry["file_size_bytes"]
                        if entry is not None
                        else None
                    ),
                    "facts": (
                        dict(entry["facts"])
                        if entry is not None
                        else None
                    ),
                    "media_available": entry is not None,
                    "stale": bool(stale),
                    "established": rule is not None,
                    "recommendation": self.recommendation_context(
                        row.media_id,
                        facts=(
                            dict(entry["facts"])
                            if entry is not None
                            else None
                        ),
                    ),
                    # Cross-path execution posture for this
                    # lineage, read from the existing execution
                    # authority. Cards use this to avoid
                    # presenting a misleading actionable Accept
                    # once the lineage is queued/active or
                    # completed. History is preserved; only the
                    # actionable presentation is gated.
                    "execution_completed": (
                        row.media_id in completion["completed"]
                    ),
                    "execution_active": (
                        row.media_id in completion["active"]
                    ),
                    "user_decision": self._user_decision_for(
                        row.media_id, row.suggestion_id
                    ),
                }
            )

        return rows

    @staticmethod
    def _decision_label(event_type):
        return {
            "accepted": "Accepted by you",
            "rejected": "Rejected by you",
            "changed": "Changed by you",
        }.get(event_type)

    def _user_decision_for(self, media_id, exclude_id):
        """
        Visible per-file decision state derived from the existing
        event ledger: the latest explicit review action on a
        non-proposed sibling row for the same media. Only
        accepted/rejected/changed events qualify; those event
        types are produced solely by explicit review actions, so
        the label describes what the user did, never media
        processing. A bare system supersede yields neutral
        "Superseded", and no history yields None.
        """

        latest = None

        for row in self.list_suggestions(media_id=media_id):
            if (
                row.suggestion_id == exclude_id
                or row.status == "proposed"
            ):
                continue

            for event in self.suggestion_events(
                row.suggestion_id
            ):
                label = self._decision_label(
                    event.get("event_type")
                )

                if label is None:
                    continue

                stamped = event.get("created_at") or ""

                if latest is None or stamped >= latest[0]:
                    latest = (stamped, label)

        if latest is not None:
            return latest[1]

        for row in self.list_suggestions(media_id=media_id):
            if (
                row.suggestion_id != exclude_id
                and row.status == "superseded"
            ):
                return "Superseded"

        return None

    def recommendation_groups(self, population=None):
        """
        Per-media review groups over every suggestion ever stored:
        media identity, all rows newest-first, and the visible
        user decision where the ledger shows one. Read-only
        aggregation of authoritative rows; no new state.
        """

        if population is None:
            population, _ = self.build_population()

        names = {
            entry["media_id"]: entry["file_name"]
            for entry in population
        }

        grouped = {}

        for row in self.list_suggestions():
            grouped.setdefault(row.media_id, []).append(row)

        groups = []

        for media_id in sorted(grouped):
            rows = grouped[media_id]

            decision = self._user_decision_for(media_id, "")

            if decision is None and any(
                row.status == "superseded" for row in rows
            ):
                decision = "Superseded"

            groups.append(
                {
                    "media_id": media_id,
                    "file_name": names.get(media_id),
                    "media_available": media_id in names,
                    "rows": [row.to_dict() for row in rows],
                    "user_decision": decision,
                }
            )

        return groups

    #: Answers that represent an actionable execution decision. A
    #: decision made is distinct from execution completed.
    REVIEW_ACTIONABLE_ANSWERS = frozenset({"Balanced", "Optimise"})

    def execution_completion(self):
        """
        Read-only map of logical media item -> execution posture,
        derived solely from the existing execution authority.
        `completed` means an authoritative successful execution
        exists; it is never inferred from acceptance or suggestion
        existence.
        """

        completed = self._execution_repository.completed_media_ids()

        active = self._execution_repository.active_media_ids()

        return {
            "completed": {str(media_id) for media_id in completed},
            "active": {str(media_id) for media_id in active},
        }

    def review_file_status(
        self,
        suggestions,
        coverage_state,
        *,
        execution_completed,
        execution_active=False,
    ):
        """
        Deterministic review status label for one logical media item
        from authoritative state only:

        - Optimisation Completed : successful execution exists;
        - Optimisation Requested : a non-terminal execution job
          exists but no successful execution yet (queued work is
          never labelled completed);
        - Waiting for Execution  : an accepted actionable decision
          exists but execution has not completed;
        - Needs your Choice      : a proposed answered suggestion
          awaits a decision;
        - Needs More Context     : a proposed ambiguous suggestion
          cannot yet be supported;
        - Preference established : an accepted non-actionable decision;
        - otherwise the coverage label.
        """

        accepted_actionable = [
            row
            for row in suggestions
            if row.status == "accepted"
            and row.proposed_answer in self.REVIEW_ACTIONABLE_ANSWERS
        ]

        proposed = [
            row for row in suggestions if row.status == "proposed"
        ]

        ambiguous = [
            row for row in proposed if row.proposed_answer is None
        ]

        answered_proposed = [
            row for row in proposed if row.proposed_answer is not None
        ]

        accepted_any = [
            row for row in suggestions if row.status == "accepted"
        ]

        if execution_completed:
            return {
                "key": "completed",
                "label": "Optimisation Completed",
                "kind": "current",
            }

        if execution_active:
            return {
                "key": "requested",
                "label": "Optimisation Requested",
                "kind": "running",
            }

        if accepted_actionable:
            return {
                "key": "waiting",
                "label": "Waiting for Execution",
                "kind": "running",
            }

        if answered_proposed:
            return {
                "key": "needs_choice",
                "label": "Needs your Choice",
                "kind": "pending",
            }

        if ambiguous:
            return {
                "key": "context",
                "label": "Needs More Context",
                "kind": "unknown",
            }

        if accepted_any:
            return {
                "key": "established",
                "label": "Preference established",
                "kind": "current",
            }

        label, kind = _COVERAGE_LABELS_FOR_SERVICE.get(
            coverage_state, (coverage_state, "unknown")
        )

        return {
            "key": "coverage",
            "label": label,
            "kind": kind,
        }

    def review_population_view(self):
        """
        Every population file with its review posture: coverage
        state under accepted rules, its suggestion rows, its
        deterministic review status, its execution posture, and any
        visible user decision. Read-only aggregation; no new state.
        """

        population, unusable = self.build_population()

        rules, scopes = self.established_rules()

        coverage = self.coverage_for_population(
            population, rules, scopes
        )

        completion = self.execution_completion()

        grouped = {}

        for row in self.list_suggestions():
            grouped.setdefault(row.media_id, []).append(row)

        files = []

        for entry in population:
            media_id = entry["media_id"]

            result = coverage[media_id]

            rows = grouped.get(media_id, [])

            status = self.review_file_status(
                rows,
                result.state,
                execution_completed=(
                    media_id in completion["completed"]
                ),
                execution_active=(
                    media_id in completion["active"]
                ),
            )

            context_row = next(
                (
                    row
                    for row in rows
                    if row.status == "proposed"
                    and row.proposed_answer is None
                ),
                None,
            )

            files.append(
                {
                    "media_id": media_id,
                    "file_name": entry["file_name"],
                    "file_size_bytes": entry["file_size_bytes"],
                    "coverage_state": result.state,
                    "coverage_label": _COVERAGE_LABELS_FOR_SERVICE.get(
                        result.state, (result.state, "")
                    )[0],
                    "suggestions": [row.to_dict() for row in rows],
                    "suggestion_count": len(rows),
                    "status": status,
                    "has_suggestions": bool(rows),
                    "execution_active": (
                        media_id in completion["active"]
                    ),
                    "user_decision": self._user_decision_for(
                        media_id, ""
                    ),
                    "context_suggestion_id": (
                        context_row.suggestion_id
                        if context_row is not None
                        else None
                    ),
                }
            )

        return {
            "files": files,
            "unusable": unusable,
            "population_total": len(population),
        }

    def review_view(self, view="needs"):
        """
        Review lists grouped by lifecycle status, read-only. All
        category populations and their counts are computed on every
        load, so no tab's count depends on another tab having been
        visited first.
        """

        allowed = (
            "needs",
            "recommendations",
            "context",
            "waiting",
            "all",
        )

        if view not in allowed:
            raise ValueError(
                f"unknown review view '{view}'"
            )

        population, _ = self.build_population()

        proposed = self.review_rows(population)

        history = [
            row.to_dict()
            for row in self.list_suggestions()
            if row.status != "proposed"
        ]

        ambiguous = []

        for row in proposed:
            suggestion = row["suggestion"]

            if suggestion["proposed_answer"] is None:
                evidence = self.ambiguous_evidence(
                    suggestion["media_id"]
                )

                ambiguous.append(
                    {
                        "suggestion_id": (
                            suggestion["suggestion_id"]
                        ),
                        "media_id": suggestion["media_id"],
                        "file_name": row["file_name"],
                        "evidence": evidence,
                    }
                )

        answered_proposed = [
            row
            for row in proposed
            if row["suggestion"].get("proposed_answer") is not None
        ]

        groups = self.recommendation_groups(population)

        files_view = self.review_population_view()

        files = files_view["files"]

        by_key = {}

        for item in files:
            by_key.setdefault(item["status"]["key"], []).append(item)

        categories = {
            "needs_choice": len(by_key.get("needs_choice", [])),
            "recommendations": len(groups),
            "context": len(by_key.get("context", [])),
            "waiting": len(by_key.get("waiting", [])),
            "all": len(files),
            "completed": len(by_key.get("completed", [])),
        }

        counts = {}

        for row in self.list_suggestions():
            counts[row.status] = counts.get(row.status, 0) + 1

        return {
            "view": view,
            "proposed": proposed,
            "answered_proposed": answered_proposed,
            "all_proposed": proposed,
            "history": history,
            "ambiguous": ambiguous,
            "groups": groups,
            "files_view": files_view,
            "context_items": by_key.get("context", []),
            "waiting_items": by_key.get("waiting", []),
            "completed_items": by_key.get("completed", []),
            "counts": counts,
            "categories": categories,
        }

    # ------------------------------------------------------------------
    # Shared per-file recommendation context + unified decision model
    #
    # Review Suggestions and the Optimisation Carousel both read the
    # SAME review items and the SAME recommendation context built
    # here. Accept/Reject/Manual Choice all route through the existing
    # review lifecycle methods above; there is no second decision
    # backend and no carousel-specific state.
    # ------------------------------------------------------------------

    def recommendation_context(self, media_id, facts=None):
        """
        Per-file recommendation summary derived from the existing
        optimisation recommendation for this logical media item: the
        current valid OpportunityAssessment's persisted decision
        signals plus the current measured facts. No recommendation is
        computed here; the surviving/preserving signal states the
        decision engine already produced are only formatted.

        Each field carries an explicit status:

        - change            : a surviving optimize/remux signal
                              proposes a different target value;
        - no-change         : a preserve/constraint signal considered
                              the field and leaves it unchanged;
        - no-recommendation : no signal addresses the field.

        That distinction is preserved only where the existing data
        model supports it, and is never fabricated.
        """

        facts = dict(facts or {})

        assessment = None

        try:
            validity = self._validity_service.get_validity(
                int(media_id)
            )

            assessment = validity.current_opportunity

        except (TypeError, ValueError):
            assessment = None

        signals = list(
            getattr(assessment, "signals", ()) or ()
        )

        fields = []

        for key, label, category, rule, fact_key in (
            RECOMMENDATION_FIELD_SPECS
        ):
            matching = [
                signal
                for signal in signals
                if rule is not None
                and getattr(signal, "rule", "") == rule
            ]

            change_signal = next(
                (
                    signal
                    for signal in matching
                    if getattr(signal, "direction", "")
                    in _OPTIMIZE_DIRECTIONS
                    and getattr(signal, "target_state", None)
                ),
                None,
            )

            preserve_signal = next(
                (
                    signal
                    for signal in matching
                    if getattr(signal, "direction", "")
                    == "preserve"
                ),
                None,
            )

            current = _display_dimension_value(
                fact_key, facts.get(fact_key)
            )

            if change_signal is not None:
                current = (
                    getattr(change_signal, "current_state", None)
                    or current
                )
                status = "change"
                recommended = getattr(
                    change_signal, "target_state", None
                )
            elif preserve_signal is not None:
                current = (
                    getattr(preserve_signal, "current_state", None)
                    or current
                )
                status = "no-change"
                recommended = current
            else:
                status = "no-recommendation"
                recommended = None

            fields.append(
                {
                    "key": key,
                    "label": label,
                    "category": category,
                    "current": current,
                    "recommended": recommended,
                    "minimum": current,
                    "status": status,
                    "editable": status == "change",
                }
            )

        change_fields = [
            field for field in fields if field["status"] == "change"
        ]

        priority_label = None

        if assessment is not None:
            priority_label = getattr(
                assessment, "priority_label", None
            )

        return {
            "available": assessment is not None,
            "level": (
                getattr(assessment, "opportunity_level", "none")
                if assessment is not None
                else "none"
            ),
            "priority_label": priority_label,
            "one_liner": priority_label,
            "has_change": bool(change_fields),
            "change_count": len(change_fields),
            "fields": fields,
        }

    def manual_choice(
        self, suggestion_id, selection, *, actor="human"
    ):
        """
        Manual Choice: the user declines the recommendation as
        presented and specifies the desired values.

        The editor's fields are the SAME recommendation fields the
        summary chips render (``recommendation_context``). The user's
        per-field selection is mapped to the existing closed
        preference-answer vocabulary and persisted through the
        existing review lifecycle: ``change_review`` supersedes the
        current record with a forward link and proposes a replacement
        carrying the chosen answer. This method therefore produces the
        existing Superseded state; it does not invent a new status and
        does not execute anything.

        ``selection`` keys: one entry per editable field key with the
        value "recommended" or "current"; optional "leave_alone"; or
        an explicit "answer" drawn from the closed vocabulary.
        """

        record = self._review_repository.get_suggestion(
            suggestion_id
        )

        if record is None:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

        if record.status != "proposed":
            raise ValueError(
                f"suggestion '{suggestion_id}' is "
                f"{record.status}, not proposed"
            )

        selection = dict(selection or {})

        explicit = selection.get("answer")

        if explicit:
            if explicit not in ANSWERS:
                raise ValueError(
                    f"unknown preference answer '{explicit}'"
                )

            answer = explicit

        elif _is_truthy(selection.get("leave_alone")):
            answer = "Leave-alone"

        else:
            context = self.recommendation_context(
                record.media_id
            )

            change_fields = [
                field
                for field in context["fields"]
                if field["status"] == "change"
            ]

            if not change_fields:
                raise ValueError(
                    "There are no editable recommendation fields "
                    "for this file; choose an explicit outcome "
                    "instead."
                )

            adopted = sum(
                1
                for field in change_fields
                if selection.get(field["key"]) == "recommended"
            )

            if adopted == 0:
                answer = "Keep"
            elif adopted == len(change_fields):
                answer = "Optimise"
            else:
                answer = "Balanced"

        if answer == record.proposed_answer:
            raise ValueError(
                "That matches the current recommendation; use "
                "Accept instead of Manual Choice."
            )

        replacement = change_review(
            self._review_repository,
            suggestion_id,
            actor,
            answer,
        )

        self._commit()

        return replacement

    def carousel_view(self, index=0, *, advance=False):
        """
        Optimisation Carousel view: one unresolved decision-ready
        review item at a time, drawn from the SAME review items and
        recommendation context as Review Suggestions. Read-only; all
        decisions go through the shared review lifecycle.
        """

        review = self.review_view("needs")

        items = sorted(
            review["answered_proposed"],
            key=lambda row: str(
                row["suggestion"].get("media_id") or ""
            ),
        )

        total = len(items)

        if total == 0:
            return {
                "mode": "carousel",
                "empty": True,
                "total": 0,
                "index": 0,
                "position": 0,
                "item": None,
                "recommendation": None,
                "advance": bool(advance),
                "categories": review["categories"],
            }

        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 0

        index = max(0, min(index, total - 1))

        item = items[index]

        recommendation = self.recommendation_context(
            item["suggestion"]["media_id"],
            facts=item.get("facts"),
        )

        return {
            "mode": "carousel",
            "empty": False,
            "total": total,
            "index": index,
            "position": index + 1,
            "item": item,
            "recommendation": recommendation,
            "advance": bool(advance),
            "categories": review["categories"],
        }

    def continuity_view(self, population=None):
        """
        Future-scan status recomputed from accepted state
        (read-only; never a persisted queue).
        """

        status = self.continuity_status()

        if not status.get("available"):
            return {
                "available": False,
                "note": (
                    "No accepted preferences yet, so there is "
                    "nothing to apply to new scans."
                ),
            }

        if population is None:
            population, _ = self.build_population()

        names = {
            entry["media_id"]: entry["file_name"]
            for entry in population
        }

        review_items = []

        for outcome in status["outcomes"]:
            if outcome["action"] != "review":
                continue

            review_items.append(
                {
                    "media_id": outcome["media_id"],
                    "file_name": names.get(outcome["media_id"]),
                    "coverage_state": outcome["coverage_state"],
                    "reason": outcome["reason"],
                    "has_suggestion": (
                        outcome["suggestion"] is not None
                    ),
                }
            )

        return {
            "available": True,
            "stats": status["stats"],
            "review_items": review_items,
        }
