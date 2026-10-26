import json

from app.preferences.suggestions import Suggestion


class PreferenceReviewRepository:
    """
    Persistence boundary for Phase 15E preference review state.

    This repository stores suggestion rows, accepted preference
    example evidence, and the append-only review event ledger. It
    performs no lifecycle reasoning: status-transition legality,
    staleness checks, and atomicity belong to the review domain
    layer, which calls these primitives.

    Transaction ownership remains with the caller.
    """

    STATUSES = (
        "proposed",
        "accepted",
        "rejected",
        "superseded",
    )

    def __init__(self, connection):
        self.connection = connection

    # --------------------------------------------------
    # Suggestions
    # --------------------------------------------------

    def save_suggestion(self, suggestion: Suggestion) -> bool:
        """
        Insert one suggestion row. Returns True when inserted,
        False when an identical suggestion_id already exists (the
        existing row is left untouched, preserving history).
        """

        if not isinstance(suggestion, Suggestion):
            raise TypeError(
                "suggestion must be a Suggestion"
            )

        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO preference_suggestions (
                suggestion_id,
                media_id,
                analysis_fingerprint,
                matched_rule_id,
                rule_version,
                derivation_version,
                source_example_ids_json,
                proposed_answer,
                coverage_state,
                reason,
                status,
                computed_at,
                superseded_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion.suggestion_id,
                suggestion.media_id,
                suggestion.analysis_fingerprint,
                suggestion.matched_rule_id,
                suggestion.rule_version,
                suggestion.derivation_version,
                json.dumps(
                    list(suggestion.source_example_ids),
                    sort_keys=True,
                ),
                suggestion.proposed_answer,
                suggestion.coverage_state,
                suggestion.reason,
                suggestion.status,
                suggestion.computed_at,
                suggestion.superseded_by,
            ),
        )

        return cursor.rowcount == 1

    def get_suggestion(
        self, suggestion_id: str
    ):
        """
        Return the Suggestion for an id, rebuilt through the
        Suggestion constructor so stored rows are re-validated on
        read, or None when absent.
        """

        row = self.connection.execute(
            """
            SELECT
                suggestion_id,
                media_id,
                analysis_fingerprint,
                matched_rule_id,
                rule_version,
                derivation_version,
                source_example_ids_json,
                proposed_answer,
                coverage_state,
                reason,
                status,
                computed_at,
                superseded_by
            FROM preference_suggestions
            WHERE suggestion_id = ?
            """,
            (suggestion_id,),
        ).fetchone()

        if row is None:
            return None

        return Suggestion(
            suggestion_id=row[0],
            media_id=row[1],
            analysis_fingerprint=row[2],
            matched_rule_id=row[3],
            rule_version=row[4],
            derivation_version=row[5],
            source_example_ids=tuple(json.loads(row[6] or "[]")),
            proposed_answer=row[7],
            coverage_state=row[8],
            reason=row[9] or "",
            status=row[10],
            computed_at=row[11] or "",
            superseded_by=row[12],
        )

    def list_suggestions(
        self, status=None, media_id=None
    ) -> list:
        """
        List suggestion rows, optionally filtered by status and/or
        media, ordered by row insertion.
        """

        query = """
            SELECT
                suggestion_id,
                media_id,
                analysis_fingerprint,
                matched_rule_id,
                rule_version,
                derivation_version,
                source_example_ids_json,
                proposed_answer,
                coverage_state,
                reason,
                status,
                computed_at,
                superseded_by
            FROM preference_suggestions
        """
        clauses = []
        params = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        if media_id is not None:
            clauses.append("media_id = ?")
            params.append(media_id)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " ORDER BY rowid"

        rows = self.connection.execute(query, params).fetchall()

        return [self._row_to_suggestion(row) for row in rows]

    def set_status(
        self,
        suggestion_id: str,
        new_status: str,
        superseded_by=None,
    ) -> None:
        """
        Update one row's status (and optional supersession link).
        Legality of the transition is the caller's responsibility.
        """

        if new_status not in self.STATUSES:
            raise ValueError(
                f"unknown suggestion status '{new_status}'"
            )

        cursor = self.connection.execute(
            """
            UPDATE preference_suggestions
            SET status = ?,
                superseded_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE suggestion_id = ?
            """,
            (new_status, superseded_by, suggestion_id),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                f"unknown suggestion '{suggestion_id}'"
            )

    # --------------------------------------------------
    # Review events (append-only)
    # --------------------------------------------------

    def append_event(
        self,
        suggestion_id: str,
        event_type: str,
        previous_status=None,
        new_status=None,
        actor="system",
        detail=None,
    ) -> int:
        """
        Append one review event row. Event rows are never updated
        or deleted through this repository.
        """

        cursor = self.connection.execute(
            """
            INSERT INTO preference_review_events (
                suggestion_id,
                event_type,
                previous_status,
                new_status,
                actor,
                detail
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion_id,
                event_type,
                previous_status,
                new_status,
                actor or "system",
                detail,
            ),
        )

        return cursor.lastrowid

    def events_for(self, suggestion_id: str) -> list:
        """
        All event rows for one suggestion, oldest first.
        """

        rows = self.connection.execute(
            """
            SELECT
                event_type,
                previous_status,
                new_status,
                actor,
                detail,
                created_at
            FROM preference_review_events
            WHERE suggestion_id = ?
            ORDER BY id
            """,
            (suggestion_id,),
        ).fetchall()

        return [
            {
                "event_type": row[0],
                "previous_status": row[1],
                "new_status": row[2],
                "actor": row[3],
                "detail": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    # --------------------------------------------------
    # Accepted preference examples (immutable evidence)
    # --------------------------------------------------

    def save_example(
        self,
        example_id: str,
        facts_json: str,
        answer: str,
        source_suggestion_id=None,
        actor="system",
    ) -> None:
        """
        Insert one accepted preference-example evidence row.
        Rows are immutable: corrections insert new rows keyed by a
        new example id; this method never updates.
        """

        if not isinstance(example_id, str) or not example_id:
            raise ValueError(
                "example_id must be a non-empty string"
            )

        self.connection.execute(
            """
            INSERT INTO preference_examples (
                example_id,
                facts_json,
                answer,
                source_suggestion_id,
                actor
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                example_id,
                facts_json,
                answer,
                source_suggestion_id,
                actor or "system",
            ),
        )

    def get_example(self, example_id: str):
        """
        Return one accepted-example row as a dict, or None.
        """

        row = self.connection.execute(
            """
            SELECT
                example_id,
                facts_json,
                answer,
                source_suggestion_id,
                actor,
                created_at
            FROM preference_examples
            WHERE example_id = ?
            """,
            (example_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "example_id": row[0],
            "facts_json": row[1],
            "answer": row[2],
            "source_suggestion_id": row[3],
            "actor": row[4],
            "created_at": row[5],
        }

    def list_examples(self) -> list:
        """
        All accepted-example rows, oldest first.
        """

        rows = self.connection.execute(
            """
            SELECT
                example_id,
                facts_json,
                answer,
                source_suggestion_id,
                actor,
                created_at
            FROM preference_examples
            ORDER BY rowid
            """
        ).fetchall()

        return [
            {
                "example_id": row[0],
                "facts_json": row[1],
                "answer": row[2],
                "source_suggestion_id": row[3],
                "actor": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def _row_to_suggestion(self, row) -> Suggestion:
        return Suggestion(
            suggestion_id=row[0],
            media_id=row[1],
            analysis_fingerprint=row[2],
            matched_rule_id=row[3],
            rule_version=row[4],
            derivation_version=row[5],
            source_example_ids=tuple(json.loads(row[6] or "[]")),
            proposed_answer=row[7],
            coverage_state=row[8],
            reason=row[9] or "",
            status=row[10],
            computed_at=row[11] or "",
            superseded_by=row[12],
        )
