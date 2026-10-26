from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StandingDecision:
    """
    Current standing decision for one lineage + proposition.

    A refused state suppresses presentation.
    A revoked state explicitly restores presentation.
    """

    id: int
    media_id: int
    proposition: str
    state: str
    actor: str
    reason: str | None
    created_at: str
    updated_at: str


class StandingDecisionRepository:
    """
    Persistence boundary for standing user decisions.

    This repository stores presentation-level decisions only.
    It never changes analysis, recommendations, validity, approval,
    or execution state.

    Current state is represented by standing_decisions.
    Immutable user-action history is represented by
    standing_decision_events.

    Transaction ownership remains with the caller.
    """

    STATE_REFUSED = "refused"
    STATE_REVOKED = "revoked"

    EVENT_REFUSED = "refused"
    EVENT_REVOKED = "revoked"

    def __init__(self, connection):
        self.connection = connection

    def get(
        self,
        media_id: int,
        proposition: str,
    ) -> StandingDecision | None:
        row = self.connection.execute(
            """
            SELECT
                id,
                media_id,
                proposition,
                state,
                actor,
                reason,
                created_at,
                updated_at
            FROM standing_decisions
            WHERE media_id = ?
              AND proposition = ?
            """,
            (
                media_id,
                proposition,
            ),
        ).fetchone()

        if row is None:
            return None

        return self._from_row(row)

    def get_refused_propositions(
        self,
        media_id: int,
    ) -> tuple[str, ...]:
        rows = self.connection.execute(
            """
            SELECT proposition
            FROM standing_decisions
            WHERE media_id = ?
              AND state = ?
            ORDER BY proposition
            """,
            (
                media_id,
                self.STATE_REFUSED,
            ),
        ).fetchall()

        return tuple(row[0] for row in rows)

    def list_for_media(
        self,
        media_id: int,
    ) -> list[StandingDecision]:
        rows = self.connection.execute(
            """
            SELECT
                id,
                media_id,
                proposition,
                state,
                actor,
                reason,
                created_at,
                updated_at
            FROM standing_decisions
            WHERE media_id = ?
            ORDER BY id
            """,
            (media_id,),
        ).fetchall()

        return [
            self._from_row(row)
            for row in rows
        ]

    def refuse(
        self,
        media_id: int,
        proposition: str,
        *,
        actor: str,
        reason: str | None = None,
    ) -> StandingDecision:
        return self._set_state(
            media_id,
            proposition,
            self.STATE_REFUSED,
            actor=actor,
            reason=reason,
        )

    def revoke(
        self,
        media_id: int,
        proposition: str,
        *,
        actor: str,
        reason: str | None = None,
    ) -> StandingDecision:
        return self._set_state(
            media_id,
            proposition,
            self.STATE_REVOKED,
            actor=actor,
            reason=reason,
        )

    def events_for(
        self,
        media_id: int,
        proposition: str,
    ) -> list[dict]:
        decision = self.get(
            media_id,
            proposition,
        )

        if decision is None:
            return []

        rows = self.connection.execute(
            """
            SELECT
                id,
                event_type,
                actor,
                reason,
                created_at
            FROM standing_decision_events
            WHERE standing_decision_id = ?
            ORDER BY id
            """,
            (decision.id,),
        ).fetchall()

        return [
            {
                "id": row[0],
                "event_type": row[1],
                "actor": row[2],
                "reason": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def _set_state(
        self,
        media_id: int,
        proposition: str,
        state: str,
        *,
        actor: str,
        reason: str | None,
    ) -> StandingDecision:
        if not isinstance(media_id, int):
            raise TypeError("media_id must be an int")

        proposition = str(proposition or "").strip()
        if not proposition:
            raise ValueError("proposition is required")

        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")

        if state not in (
            self.STATE_REFUSED,
            self.STATE_REVOKED,
        ):
            raise ValueError(
                f"unsupported standing decision state: {state!r}"
            )

        current = self.get(
            media_id,
            proposition,
        )

        cursor = self.connection.cursor()

        if current is None:
            cursor.execute(
                """
                INSERT INTO standing_decisions (
                    media_id,
                    proposition,
                    state,
                    actor,
                    reason
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    media_id,
                    proposition,
                    state,
                    actor,
                    reason,
                ),
            )

            decision_id = cursor.lastrowid

        else:
            cursor.execute(
                """
                UPDATE standing_decisions
                SET
                    state = ?,
                    actor = ?,
                    reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    state,
                    actor,
                    reason,
                    current.id,
                ),
            )

            decision_id = current.id

        cursor.execute(
            """
            INSERT INTO standing_decision_events (
                standing_decision_id,
                event_type,
                actor,
                reason
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                decision_id,
                state,
                actor,
                reason,
            ),
        )

        return self.get(
            media_id,
            proposition,
        )

    @staticmethod
    def _from_row(row) -> StandingDecision:
        return StandingDecision(
            id=row[0],
            media_id=row[1],
            proposition=row[2],
            state=row[3],
            actor=row[4],
            reason=row[5],
            created_at=row[6],
            updated_at=row[7],
        )