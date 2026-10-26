"""
Persistence boundary for durable Preferences Wizard progress
(Phase 16 correction, migration 042).

This repository stores exactly two things:

- per-logical-media Wizard answers (`preference_wizard_progress`),
  keyed by logical media identity (the active lineage id as text),
  never by a file observation id; and
- a single cursor/flag row (`preference_wizard_state`).

It carries NO preference authority. It performs no compilation,
coverage, suggestion, acceptance, or execution reasoning. Accepted
preferences remain owned exclusively by the existing preference
review lifecycle. Transaction ownership remains with the caller.
"""

from app.preferences.dimensions import ANSWERS


class PreferenceWizardProgressRepository:
    """Read/write access to durable Wizard progress."""

    def __init__(self, connection):
        self.connection = connection

    # --------------------------------------------------
    # Progress
    # --------------------------------------------------

    def answered(self) -> dict:
        """Map every durably answered media_id to its answer."""

        rows = self.connection.execute(
            """
            SELECT media_id, answer
            FROM preference_wizard_progress
            ORDER BY media_id
            """
        ).fetchall()

        return {row[0]: row[1] for row in rows}

    def answered_ids(self) -> set:
        """The set of logical media ids the Wizard has answered."""

        return set(self.answered())

    def get_answer(self, media_id):
        row = self.connection.execute(
            """
            SELECT answer
            FROM preference_wizard_progress
            WHERE media_id = ?
            """,
            (str(media_id),),
        ).fetchone()

        return row[0] if row is not None else None

    def record_answer(self, media_id, answer) -> None:
        """
        Durably record one explicit answer for a logical media item.
        Re-answering the same logical item replaces its answer in
        place; the media identity is the durable key.
        """

        if answer not in ANSWERS:
            raise ValueError(
                f"unknown preference answer '{answer}'"
            )

        media_id = str(media_id or "").strip()

        if not media_id:
            raise ValueError("media_id is required")

        self.connection.execute(
            """
            INSERT INTO preference_wizard_progress (
                media_id,
                answer
            )
            VALUES (?, ?)
            ON CONFLICT (media_id) DO UPDATE SET
                answer = excluded.answer,
                updated_at = CURRENT_TIMESTAMP
            """,
            (media_id, answer),
        )

    def restore_answer(self, media_id, answer) -> None:
        """Reinstate one previously known answer (cancel support)."""

        self.record_answer(media_id, answer)

    def delete(self, media_ids) -> None:
        """Delete progress rows for the given logical media ids."""

        ids = [str(media_id) for media_id in media_ids]

        if not ids:
            return

        placeholders = ", ".join("?" for _ in ids)

        self.connection.execute(
            f"""
            DELETE FROM preference_wizard_progress
            WHERE media_id IN ({placeholders})
            """,
            ids,
        )

    # --------------------------------------------------
    # Cursor / flags
    # --------------------------------------------------

    def _ensure_state(self) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO preference_wizard_state (id)
            VALUES (1)
            """
        )

    def state(self) -> dict:
        """
        The single cursor/flag record. Read-only: never creates the
        row (creation belongs to the explicit write paths), so a read
        can never hold a write transaction open.
        """

        row = self.connection.execute(
            """
            SELECT last_media_id, stopped, completed, reset_at,
                   updated_at
            FROM preference_wizard_state
            WHERE id = 1
            """
        ).fetchone()

        return {
            "last_media_id": row[0] if row else None,
            "stopped": bool(row[1]) if row else False,
            "completed": bool(row[2]) if row else False,
            "reset_at": row[3] if row else None,
            "updated_at": row[4] if row else None,
        }

    def mark_started(self) -> None:
        """A Wizard interaction is in progress again."""

        self._ensure_state()

        self.connection.execute(
            """
            UPDATE preference_wizard_state
            SET stopped = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """
        )

    def mark_stopped(
        self,
        *,
        last_media_id=None,
        completed=None,
    ) -> None:
        """Record that the user intentionally stopped/continued."""

        self._ensure_state()

        assignments = [
            "stopped = 1",
            "updated_at = CURRENT_TIMESTAMP",
        ]
        values = []

        if last_media_id is not None:
            assignments.append("last_media_id = ?")
            values.append(str(last_media_id))

        if completed is not None:
            assignments.append("completed = ?")
            values.append(1 if completed else 0)

        self.connection.execute(
            f"""
            UPDATE preference_wizard_state
            SET {", ".join(assignments)}
            WHERE id = 1
            """,
            values,
        )

    def set_last_media(self, media_id) -> None:
        self._ensure_state()

        self.connection.execute(
            """
            UPDATE preference_wizard_state
            SET last_media_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (str(media_id),),
        )

    def reset(self) -> None:
        """
        Explicit Wizard reset: clear progress and cursor flags only.
        Never touches suggestions, review events, accepted examples,
        observations, lineage, policy, or execution history.
        """

        self.connection.execute(
            "DELETE FROM preference_wizard_progress"
        )

        self._ensure_state()

        self.connection.execute(
            """
            UPDATE preference_wizard_state
            SET last_media_id = NULL,
                stopped = 0,
                completed = 0,
                reset_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """
        )
