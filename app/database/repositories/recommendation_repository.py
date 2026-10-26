"""
Recommendation persistence (Sprint 10 correction).

Thin repository over the recommendations / recommendation_events
tables (migration 024). Rows are durable historical results of
analysis runs:

- created by the canonical pipeline when a run produces an opportunity
  assessment, in state 'proposed'
- evolved ONLY through validated lifecycle transitions, each of which
  appends an immutable event row
- never deleted; newer recommendations never rewrite older ones

Execution linkage is stored on the recommendation; execution state
itself remains owned exclusively by the execution job and is mirrored
here only by ExecutionService at job transition points.
"""

import json

from app.models.recommendation import (
    RecommendationRecord,
    assert_transition,
)


class RecommendationError(ValueError):
    """Raised for illegal recommendation lifecycle operations."""


class RecommendationRepository:

    def __init__(self, connection):

        self.connection = connection

    # ---------------------------------------------------------
    # creation
    # ---------------------------------------------------------

    def create_proposed(
        self,
        *,
        media_id: int,
        analysis_run_id: int,
        file_observation_id: int | None,
        opportunity: str,
        opportunity_score: float | None,
        confidence: float | None,
        estimated_saving_percent: float | None,
        estimated_saved_bytes: int | None,
        risk: str | None,
        rationale: list,
        contributing_rules: list,
        intelligence_identity: str | None,
        opportunity_level: str = "none",
        summary: str | None = None,
    ) -> int:
        """
        Persist the recommendation AS PRODUCED BY ITS RUN, in state
        'proposed', recording the 'proposed' lifecycle event.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO recommendations (
                media_id,
                analysis_run_id,
                file_observation_id,
                opportunity,
                opportunity_score,
                confidence,
                estimated_saving_percent,
                estimated_saved_bytes,
                risk,
                rationale_json,
                contributing_rules_json,
                intelligence_identity,
                opportunity_level,
                summary,
                state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'proposed')
            """,
            (
                media_id,
                analysis_run_id,
                file_observation_id,
                opportunity,
                opportunity_score,
                confidence,
                estimated_saving_percent,
                estimated_saved_bytes,
                risk,
                json.dumps(list(rationale or [])),
                json.dumps(
                    list(contributing_rules or [])
                ),
                intelligence_identity,
                opportunity_level,
                summary,
            ),
        )

        recommendation_id = cursor.lastrowid

        self._record_event(
            cursor,
            recommendation_id=recommendation_id,
            event_type="proposed",
            previous_state=None,
            new_state="proposed",
            actor="pipeline",
            detail=None,
        )

        return recommendation_id

    # ---------------------------------------------------------
    # reads
    # ---------------------------------------------------------

    def get(self, recommendation_id):

        row = self.connection.execute(
            """
            SELECT *
            FROM recommendations
            WHERE id = ?
            """,
            (recommendation_id,),
        ).fetchone()

        if row is None:
            return None

        return self._record_from_row(row)

    def get_by_run(self, analysis_run_id):

        rows = self.connection.execute(
            """
            SELECT *
            FROM recommendations
            WHERE analysis_run_id = ?
            ORDER BY id
            """,
            (analysis_run_id,),
        ).fetchall()

        return [
            self._record_from_row(row)
            for row in rows
        ]

    def latest_for_media(
        self,
        media_id: int,
        *,
        states: tuple | None = None,
    ):

        if states:

            placeholders = ",".join(
                "?" for _ in states
            )

            rows = self.connection.execute(
                f"""
                SELECT *
                FROM recommendations
                WHERE media_id = ?
                  AND state IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                (media_id, *states),
            ).fetchone()

        else:

            rows = self.connection.execute(
                """
                SELECT *
                FROM recommendations
                WHERE media_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (media_id,),
            ).fetchone()

        if rows is None:
            return None

        return self._record_from_row(rows)

    def list_by_media(self, media_id):

        rows = self.connection.execute(
            """
            SELECT *
            FROM recommendations
            WHERE media_id = ?
            ORDER BY id DESC
            """,
            (media_id,),
        ).fetchall()

        return [
            self._record_from_row(row)
            for row in rows
        ]

    def get_by_execution_job(self, execution_job_id):

        row = self.connection.execute(
            """
            SELECT *
            FROM recommendations
            WHERE execution_job_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (execution_job_id,),
        ).fetchone()

        if row is None:
            return None

        return self._record_from_row(row)

    def find_proposed_for_run(
        self,
        media_id: int,
        analysis_run_id: int,
    ):

        rows = self.connection.execute(
            """
            SELECT *
            FROM recommendations
            WHERE media_id = ?
              AND analysis_run_id = ?
              AND state = 'proposed'
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                media_id,
                analysis_run_id,
            ),
        ).fetchone()

        if rows is None:

            return self.latest_for_media(
                media_id,
                states=("proposed",),
            )

        return self._record_from_row(rows)

    def events_for(self, recommendation_id):

        rows = self.connection.execute(
            """
            SELECT
                event_type,
                previous_state,
                new_state,
                execution_job_id,
                actor,
                detail,
                created_at
            FROM recommendation_events
            WHERE recommendation_id = ?
            ORDER BY id
            """,
            (recommendation_id,),
        ).fetchall()

        return [
            {
                "event_type": row[0],
                "previous_state": row[1],
                "new_state": row[2],
                "execution_job_id": row[3],
                "actor": row[4],
                "detail": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    # ---------------------------------------------------------
    # lifecycle transitions
    # ---------------------------------------------------------

    def transition(
        self,
        recommendation_id: int,
        *,
        new_state: str,
        expected_current: tuple,
        actor: str = "system",
        detail: str | None = None,
        execution_job_id: int | None = None,
    ) -> RecommendationRecord:
        """
        Move one recommendation to `new_state`, validating the
        transition against the persisted current state and appending
        the corresponding immutable event.
        """

        current = self.get(recommendation_id)

        if current is None:
            raise RecommendationError(
                f"recommendation {recommendation_id} not found"
            )

        if current.state not in expected_current:
            raise RecommendationError(
                f"recommendation {recommendation_id} is "
                f"'{current.state}'; expected one of "
                f"{sorted(expected_current)}"
            )

        assert_transition(current.state, new_state)

        cursor = self.connection.cursor()

        cursor.execute(
            """
            UPDATE recommendations
            SET
                state = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                new_state,
                recommendation_id,
            ),
        )

        event_type = (
            new_state
            if new_state in (
                "accepted",
                "rejected",
                "queued",
            )
            else "state_changed"
        )

        self._record_event(
            cursor,
            recommendation_id=recommendation_id,
            event_type=event_type,
            previous_state=current.state,
            new_state=new_state,
            actor=actor,
            detail=detail,
            execution_job_id=(
                execution_job_id
                if execution_job_id is not None
                else current.execution_job_id
            ),
        )

        self.connection.commit()

        return self.get(recommendation_id)

    def attach_presentation_snapshot(
        self,
        recommendation_id: int,
        *,
        priority_score: float | None,
        rank_at_presentation: int | None,
        components: dict | None,
        rationale: list | None,
    ) -> None:
        """
        Freeze the prioritisation-layer presentation values onto the
        record (invoked at acceptance time with exactly what the
        prioritised queue showed).
        """

        self.connection.execute(
            """
            UPDATE recommendations
            SET
                priority_score = ?,
                rank_at_presentation = ?,
                components_json = ?,
                rationale_json = COALESCE(?, rationale_json),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                priority_score,
                rank_at_presentation,
                (
                    json.dumps(components)
                    if components is not None
                    else None
                ),
                (
                    json.dumps(list(rationale))
                    if rationale is not None
                    else None
                ),
                recommendation_id,
            ),
        )

    def link_execution(
        self,
        recommendation_id: int,
        execution_job_id: int,
    ) -> None:
        """
        Durable recommendation-to-execution linkage. The job remains
        the single execution authority.
        """

        self.connection.execute(
            """
            UPDATE recommendations
            SET
                execution_job_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                execution_job_id,
                recommendation_id,
            ),
        )

        self.connection.commit()

    # ---------------------------------------------------------
    # internals
    # ---------------------------------------------------------

    @staticmethod
    def _record_event(
        cursor,
        *,
        recommendation_id: int,
        event_type: str,
        previous_state: str | None,
        new_state: str | None,
        actor: str,
        detail: str | None,
        execution_job_id: int | None = None,
    ) -> None:

        cursor.execute(
            """
            INSERT INTO recommendation_events (
                recommendation_id,
                event_type,
                previous_state,
                new_state,
                execution_job_id,
                actor,
                detail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation_id,
                event_type,
                previous_state,
                new_state,
                execution_job_id,
                actor,
                detail,
            ),
        )

    def _record_from_row(self, row) -> RecommendationRecord:

        # Positional access keeps this repository independent of the
        # caller's row_factory. Order mirrors migration 024 DDL with
        # the migration 029 appended columns (opportunity_level,
        # summary) last.
        def _load(value, fallback):
            if value is None:
                return fallback
            try:
                loaded = json.loads(value)
            except (TypeError, ValueError):
                return fallback
            return loaded

        return RecommendationRecord(
            id=row[0],
            media_id=row[1],
            analysis_run_id=row[2],
            file_observation_id=row[3],
            opportunity=row[4],
            opportunity_score=row[5],
            confidence=row[6],
            estimated_saving_percent=row[7],
            estimated_saved_bytes=row[8],
            risk=row[9],
            priority_score=row[10],
            rank_at_presentation=row[11],
            components=_load(row[12], {}),
            rationale=_load(row[13], []),
            contributing_rules=_load(row[14], []),
            intelligence_identity=row[15],
            state=row[16],
            execution_job_id=row[17],
            created_at=row[18],
            updated_at=row[19],
            opportunity_level=(
                row[20]
                if len(row) > 20 and row[20] is not None
                else "none"
            ),
            summary=(
                row[21]
                if len(row) > 21
                else None
            ),
        )